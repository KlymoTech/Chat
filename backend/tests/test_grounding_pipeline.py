from uuid import uuid4

from northstar_api.services.grounding import blocked_topic, validate_answer
from northstar_api.services.ingestion import approved_extraction_chunks
from northstar_api.services.retrieval import Evidence, _rerank


def evidence(text: str, score: float = 0.5) -> Evidence:
    return Evidence("chunk", str(uuid4()), str(uuid4()), "Book", None, text, score)


def test_blocked_topic_matches_before_retrieval() -> None:
    assert blocked_topic("Can you give legal advice?", ["legal advice"]) == "legal advice"
    assert blocked_topic("What is the refund policy?", ["legal advice"]) is None


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
