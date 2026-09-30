from uuid import uuid4

from northstar_api.services.grounding import blocked_topic, blocked_topic_refusal, validate_answer
from northstar_api.services.ingestion import (
    approved_extraction_chunks,
    validate_embedding_batch,
)
from northstar_api.services.retrieval import Evidence, _rerank, answer_matches_question, normalized_query_terms, replace_evidence
from northstar_api.services.course_knowledge import assess_course_evidence


def evidence(text: str, score: float = 0.5) -> Evidence:
    return Evidence("chunk", str(uuid4()), str(uuid4()), "Book", None, text, score)


def test_blocked_topic_matches_before_retrieval() -> None:
    assert blocked_topic("Can you give legal advice?", ["legal advice"]) == "legal advice"
    assert blocked_topic("Can you give LEGAL-advice?", ["legal advice"]) == "legal advice"
    assert blocked_topic(
        "Can you give legal advice?", ["Do not answer questions about legal advice"]
    ) == "Do not answer questions about legal advice"
    assert blocked_topic("What is the refund policy?", ["legal advice"]) is None
    assert "legal advice" not in blocked_topic_refusal().casefold()


def test_grounding_rejects_numeric_mutation() -> None:
    source = [evidence("The measured value is -12.50 V.")]
    assert validate_answer("The measured value is -12.50 V.", source).allowed
    assert not validate_answer("The measured value is 12.50 V.", source).allowed


def test_rerank_boosts_exact_critical_terms() -> None:
    query = "Which result is NOT valid: -12.50 V?"
    ranked = _rerank(
        [evidence("The result is valid and 12.50 V.", 0.8), evidence("NOT valid: -12.50 V.", 0.6)],
        query,
        2,
    )
    assert "NOT valid" in ranked[0].text


def test_rerank_prioritizes_exact_entity_phrase_over_generic_code() -> None:
    ranked = _rerank(
        [
            evidence("The secret project code is BLUE-ORBIT-752.", 0.2),
            evidence("Sunday's code is 2 + 2 = 4.", 0.2),
        ],
        "Tell me the Sunday code.",
        2,
    )
    assert "Sunday" in ranked[0].text
    assert ranked[0].metadata["retrieval"]["query_terms"] == ["sunday"]


def test_answer_must_repeat_requested_entity() -> None:
    assert normalized_query_terms("What is the meta book code?") == ("meta", "book")
    assert answer_matches_question("The meta book code is moon-light-8.", "What is the meta book code?")
    assert not answer_matches_question("The secret project code is BLUE-ORBIT-752.", "What is the meta book code?")


def test_normalization_allows_question_grammar_without_broadening_course_scope() -> None:
    assert normalized_query_terms("When did the Indus Valley Civilization begin?") == (
        "indus", "valley", "civilization", "begin"
    )
    assert normalized_query_terms("Who created the Taj Mahal?") == ("create", "taj", "mahal")
    assert normalized_query_terms("When did India become a sovereign republic?") == (
        "india", "become", "sovereign", "republic"
    )


def test_course_assessment_accepts_authorized_indian_history_facts_with_inflections() -> None:
    cases = (
        ("The Indus valley Civilization began around 2500 BCE.", "When did the Indus Valley Civilization begin?"),
        ("Shah Jahan created the Taj Mahal.", "Who created the Taj Mahal?"),
        ("India then became a sovereign republic in 1950.", "When did India become a sovereign republic?"),
        ("India finally won its freedom on August 15, 1947.", "When did India finally win its freedom?"),
    )
    for text, question in cases:
        result = assess_course_evidence([evidence(text)], question, 1)
        assert result.blocked_reason is None
        assert result.evidence


def test_course_assessment_blocks_generic_or_ambiguous_evidence() -> None:
    items = [evidence("Sunday code is four.", 0.2), evidence("Sunday code is seven.", 0.2)]
    result = assess_course_evidence(items, "Tell me the Sunday code", 2)
    assert result.evidence == []
    assert result.blocked_reason == "ambiguous_course_evidence"


def test_approved_chunks_keep_page_and_region_provenance() -> None:
    chunks = approved_extraction_chunks(
        {
            "extraction_revision": 3,
            "pages": [
                {
                    "number": 7,
                    "printed_page_label": "10",
                    "blocks": [
                        {
                            "id": "P0007-R0001",
                            "type": "table",
                            "selected_text": "Item | Value\nA | -12.50",
                            "bbox_px": [10, 20, 300, 200],
                            "crop": "crops/P0007-R0001.png",
                        }
                    ],
                }
            ],
        }
    )
    assert len(chunks) == 1
    text, metadata = chunks[0]
    assert text.startswith("Item | Value")
    assert metadata["page_number"] == 7
    assert metadata["printed_page_label"] == "10"
    assert metadata["block_id"] == "P0007-R0001"
    assert metadata["chunk_type"] == "table"
    assert metadata["extraction_revision"] == 3


def test_rerank_preserves_retrieval_score_components() -> None:
    item = Evidence(
        "chunk",
        str(uuid4()),
        str(uuid4()),
        "Book",
        None,
        "exact policy identifier",
        0.75,
        dense_score=0.6,
        lexical_score=0.4,
        fusion_score=0.75,
    )
    ranked = _rerank([item], "policy identifier", 1)
    assert ranked[0].dense_score == 0.6
    assert ranked[0].lexical_score == 0.4
    assert ranked[0].fusion_score == 0.75


def test_replace_evidence_can_record_fusion_without_losing_dense_score() -> None:
    item = evidence("policy")
    item = replace_evidence(item, 0.8, lexical_score=0.2, fusion_score=0.8)
    assert item.score == item.fusion_score == 0.8
    assert item.lexical_score == 0.2


def test_embedding_batch_rejects_zero_non_finite_and_wrong_count() -> None:
    validate_embedding_batch([[1.0, 0.0]], 1, 2)
    for vectors, count in (([], 1), ([[0.0, 0.0]], 1), ([[float("nan"), 1.0]], 1)):
        try:
            validate_embedding_batch(vectors, count, 2)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid embeddings must not be published")
