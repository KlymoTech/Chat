# Hybrid document extraction

The [complete extraction design](HYBRID_EXTRACTION_PLAN.md) preserves all 15 sections
of the supplied specification with the NVIDIA-only model selection. This page
documents current behavior and the remaining implementation gaps.

Uploaded PDF, DOCX, TXT, Markdown, PNG, JPEG, and TIFF sources enter a review stage before indexing. The
original upload remains in object storage. The worker writes a versioned extraction archive under
`extractions/<tenant>/<source>/vNNNN.zip`, sets the source to `needs_review`, and stops.
The frontend shows the source pages, native text, independent vision reading, conflicts,
and editable approved text. A reviewer must confirm every source unit. Approval records
the reviewer, selected-text checksum, page-image checksum, time, and reason. Only the
approved text is then sent through the existing chunking and embedding pipeline.

## Evidence package

The archive contains `extracted.json`, `extracted_review.txt`,
`validation_report.txt`, `manifest.json`, and PDF page images. The manifest records
SHA-256 hashes for all artifacts. Page records retain native and visual candidates,
source page indexes, PDF page labels, image frame indexes, render dimensions, native block coordinates,
and issue IDs. Text files retain exact decoded characters and byte offsets. The TXT
reports are generated from the structured record. A source with unresolved issues is
reported as blocked and is never indexed automatically.

## NVIDIA-only vision configuration

The only vision provider is NVIDIA's hosted `meta/llama-3.2-11b-vision-instruct`
through `langchain_nvidia_ai_endpoints.ChatNVIDIA`. Both the hybrid document reader
and the website screenshot reader use this shared client. Other provider/model
settings are rejected; there is no local-model fallback.

```python
from langchain_nvidia_ai_endpoints import ChatNVIDIA

client = ChatNVIDIA(
    model="meta/llama-3.2-11b-vision-instruct",
    # Reads NVIDIA_API_KEY from the environment.
    temperature=1,
    top_p=1,
    max_completion_tokens=512,
)
```

Set `NVIDIA_API_KEY` in the local or deployment environment; never commit it.
`EXTRACTION_VISION_TIMEOUT_SECONDS` defaults to 120 and
`EXTRACTION_VISION_MAX_TOKENS` defaults to 512. The provider and model settings are
restricted to the values above. The completion parameter follows the
[ChatNVIDIA API](https://reference.langchain.com/python/langchain-nvidia-ai-endpoints/chat_models/ChatNVIDIA/max_tokens).

Send actual page/crop pixels in an `image_url` data URL alongside the extraction
instruction. The independent reading does not receive the native transcript.
Only `response.content` is a transcription candidate; `reasoning_content` must
never enter source text. Empty responses, missing completion status, refusals,
and output-limit termination fail the visual pass. With a 512-token limit, dense
pages may fail until region splitting is implemented; never shorten the extraction
to make it fit or mark a partial response as verified.

Run `python tests/check_local_vision_runtime.py` from `backend` with the API key
in the environment to probe actual image transport. This is a manual deployment
check, not an automatic per-document gate. A failed document visual pass creates
`VISION_UNAVAILABLE` and stays in review; native text is never silently promoted as verified.
After the model is available, reviewers can retry visual reading without reuploading the source.

## Extraction plan with the selected model

Keep the source-verification workflow from the specification:

1. Preserve the original and inventory every page, logical part, or image frame.
2. Extract native text and structure, and render paginated sources with coordinate mappings.
3. Use the NVIDIA model for independent visual inventory and bounded region transcription.
4. Reconcile native and visual candidates by source location; retain disagreements.
5. Validate coverage, text, tables, numbers, equations, question structure, and continuity.
6. Retry disputed regions with better source crops, at most three attempts per issue,
   using the same NVIDIA model; require human review for unresolved evidence.
7. Generate deterministic TXT/JSON, image evidence, manifest checksums, and correction history.
8. Release only after required checks and source-based reviews are complete.

Both `VISION_PRIMARY` and `VISION_REVIEW` in the original plan refer to this same
NVIDIA model. A second call is not independent model verification. Strict approval
still calls for a separate human reviewer for critical educational content.
The original Qwen/local-endpoint recommendation is superseded. Native parsers remain
part of the workflow. Remaining implementation gaps are listed below.

## Current acceptance boundary

PDF pages receive a native pass and a rendered visual pass. Exact agreement after
whitespace normalization selects the native candidate, but human review is still
required. Conflicts require source inspection. Image frames receive a visual reading
and always require source-based review. A failed visual reading blocks verified release.
TXT and Markdown use strict UTF-8
decoding and source bytes as primary evidence. DOCX native paragraphs and tables are
exported as a draft, but approval is blocked until a controlled visual page derivative
is available. No accuracy percentage is claimed without a labeled benchmark.

PDF and image pages write durable checkpoints under the extraction revision and can
resume from a verified contiguous page prefix after a worker retry. Large documents
still need streaming archive access, targeted crop retries, DOCX rendering,
specialist table/equation validation, and an
independent second review for critical educational content. The current worker has a
25-minute hard limit, so long textbooks are not yet an accepted processing class.
