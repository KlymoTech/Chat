# Hybrid extraction implementation — NVIDIA preserved

Date: 17 September 2026
Repository: ooarchitect92/Chat
Branch: feature/hybrid-extraction-nvidia-preserved-20260917
Base commit: ea215e3dd33f9f75a9e89909e65f791a68b0a195

## Delivery status

This change implements and connects the source-preserving extraction, validation, review UI, export, checkpoint and verified-ingestion paths described below. It is not a claim that every recommendation in the supplied plan is implemented, that every document can be recovered exactly, or that production acceptance is complete. Keep this branch unmerged until the outstanding checks below pass.

The supplied plan is the requirements basis: native extraction, independent page/region vision, reconciliation, validation, bounded recovery, source-based review, deterministic TXT/JSON/evidence exports. The user explicitly excluded Qwen and required the existing NVIDIA configuration to remain unchanged.

## NVIDIA and unrelated application behavior

No changes are made to services/vision.py, config.py, services/llm.py, pyproject.toml or uv.lock. The existing NVIDIA vision model remains meta/llama-3.2-11b-vision-instruct, with its existing client constructor, credentials, sampling, token and timeout configuration. No Qwen model, replacement endpoint, model download or GPU service is introduced. The existing NVIDIA text model and embedding adapter are not replaced.

Extraction prompts and validation are extended around the existing NVIDIA client. File ingestion is deliberately stricter: previously supplied file text is no longer sufficient evidence for indexing. Existing web/sitemap ingestion and downstream NVIDIA embedding calls are retained. No new training, retrieval or model-serving subsystem is introduced.

## Implemented workflow

Upload and preserved original -> native source inventory -> direct page/frame render -> independent visual inventory -> typed region readings -> native/visual comparison -> ten validation gates -> bounded crop recovery or source review -> deterministic draft evidence -> primary review for every source unit -> independent second review for critical content -> current-policy validation -> verified canonical content -> existing ingestion and embeddings.

Drafts remain available when extraction or approval is blocked. Processing coverage and candidate agreement are never reported as measured extraction accuracy.

### Canonical records and source identity

- Strict, bounded Pydantic contracts for regions, readings, table cells and question options.
- Duplicate JSON keys, non-finite numbers, invalid geometry and coercing boolean/number responses are rejected.
- SHA-256 source/configuration/image/crop identities, physical and rendered page numbers, frame indices, reading order and explicit source relationships.
- Native candidates, visual candidates, selected content and separately labeled derived descriptions remain distinct.

Files: extraction_schema.py, extraction_native.py, extraction_structure.py.

### PDF, Word, image and text adapters

PDF: pypdf inspection/native text plus PyMuPDF page renders, native geometry, spans, words, table candidates, embedded-image identities, annotations and form metadata. Native and visual disagreements remain issues rather than unconditional selection of one channel. Physical page identity and PDF page labels are retained.

Word: bounded OOXML ZIP/XML intake, original part hashes, ordered logical blocks, raw XML, runs, styles, numbering, table spans and relationships. Comments, deleted/hidden content, notes, text boxes, content controls and native mathematics are retained in labeled channels. A separate frozen-field/current-revision derivative is rendered with LibreOffice; renderer version, locale and font inventory are recorded. External dependencies/active embedded content block rendering. Ambiguous native-to-rendered mappings require explicit source links; merely resolving an issue does not waive that structural requirement.

Images: supported PNG/JPEG/TIFF sources, original pixels retained, frame accounting, EXIF-oriented processing derivatives and recorded resize scale. Source bytes remain in the evidence archive.

Text/Markdown: strict UTF-8 and BOM-tagged UTF-8/UTF-16/UTF-32 decoding, exact text, line endings, offsets, BOM and line records. No lossy ignore/replace decoding; no artificial physical page numbers; no model call for exact source bytes. Invalid encoding produces a blocked draft.

Files: extraction_native.py, extraction_word.py, extraction_pipeline.py.

### Independent NVIDIA reading and bounded recovery

The initial vision prompts receive images, not the native transcript. Inventory and transcription are separate calls. Actual input crops, prompt versions, raw output, parsed output, model identity, completion reason and parse failures are retained. Incomplete/truncated responses trigger bounded smaller crops, never a request to shorten source content. Technical failures cannot be waived by review. Region overlap and split boundaries remain explicit review issues.

The existing call/token settings are not increased. This protects the requested NVIDIA configuration but means dense material may remain blocked when the configured budget is insufficient.

Files: extraction_regions.py, extraction_pipeline.py.

### Tables, equations, questions and document continuity

Cell validation checks coordinates, spans, overlapping/absent grid positions, merge owners, explicit states, header references, units and declared dimensions. Numeric signs and critical-word/symbol disagreements are classified separately. Equations keep candidate markup and source crops rather than being solved. Question option labels/order and printed answers remain source records; absent answers are not generated.

Cross-page logical assembly requires reciprocal, reviewed links between adjacent same-type fragments. Original physical fragments are retained. Word logical mappings similarly require explicit current evidence where unique native matching is unavailable.

These controls do not constitute a universal specialist table/formula recognition engine. Complex split-region tables and ambiguous educational relationships still require source review and may remain blocked.

Files: extraction_structure.py, extraction_validation.py, extraction_review.py.

### Ten validation and release gates

1. Source/render integrity.
2. Schema, identities and geometry.
3. Detected-region/source-object accounting.
4. Native/visual text comparison.
5. Table cells and numbers.
6. Educational structures.
7. Source-based visual audit.
8. Document continuity and Word mappings.
9. Canonical/export consistency.
10. Human acceptance and critical-content second review.

Review fingerprints bind selected text, raw candidates, geometry, source evidence, relationships, configuration and relevant issue decisions. Changes invalidate affected approvals. Critical content requires a different second reviewer. Review updates are prepared atomically and rolled back entirely on invalid submissions. Corrections keep history; source anomalies are distinct from extraction defects. Illegibility remains a blocker.

Files: extraction_validation.py, extraction_review.py.

### Deterministic exports and recovery

Artifacts include extracted_review.txt, validation_report.txt, extracted.json, manifest.json, correction_history.json, the original source, page images, crops, actual model inputs and attempt records. Escaped source-bearing records prevent source delimiters from corrupting the TXT structure. Readable output and canonical/source records are checked for consistency. ZIP ordering and timestamps are deterministic for a fixed extraction record. Reserved export names cannot be overwritten by evidence assets.

Page checkpoints bind source, configuration, prompt, version, page and image checksums. Failed readings are not accepted as reusable checkpoints. A corrupted earlier checkpoint does not discard valid later pages. Storage failures propagate for job retry rather than masquerading as successfully completed source processing.

Files: extraction_package.py, extraction_checkpoint.py, extraction_storage.py.

### Application integration and review UI

The existing knowledge extraction endpoints remain in use. The review modal now sends extractionRevision, structured blocks, exact block-derived text, source relationships and explicit issue decisions, rather than the previous incomplete approval payload. It displays validation outcomes, current revision, source images, native/visual candidates, Word mapping issues and primary/second-review states. Reviews can be saved for a subset of units without releasing the document. Editing source decisions clears local confirmation. Technical failures require retry.

The review API preserves existing authentication and workspace headers, guards against workspace changes and reuses central session refresh. The backend approval endpoint retains existing permission/revision checks. The new review service preserves page-list aliases used by that endpoint.

The worker revalidates stored evidence using current gates before indexing. It uses verified canonical content, never an arbitrary file source.content value. A file without a preserved uploaded original cannot bypass extraction by supplying text.

Files: ingestion.py; frontend/src/lib/extraction-api.ts; frontend/src/lib/extraction-review-state.ts; frontend/src/components/extraction-review-modal.tsx.

### Verification tools

extraction_cli.py exports a local source evidence package using the existing configured environment. --probe-vision sends an image containing random values absent from the prompt, preserving the existing NVIDIA endpoint/model. This tests actual image reading, not extraction accuracy.

extraction_benchmark.py requires human-adjudicated annotations with a matching source checksum. It measures annotated block recall, exact text, critical tokens, table cells/header associations, equation representation, reading order and source links. Unannotated metric categories remain NOT_MEASURED. These are scoped exact-match measurements, not CER/WER or a universal accuracy percentage.

## Checks actually executed

| Check | Result | Scope |
| --- | --- | --- |
| Focused Python suite | 72 passed, 0 failed | Three committed extraction test modules, --noconftest |
| PDF extraction fixtures | Passed within that suite | Real generated PDFs and real pypdf/PyMuPDF parsing/rendering; vision mocked |
| Word rendering fixture | Passed, not skipped | Real LibreOffice render and recorded provenance |
| TIFF/text fixtures | Passed within that suite | Real multi-frame images and strict encoding/byte handling |
| Review payload assertions | 10 passed | Executes the production TypeScript payload builder after transpilation |
| TypeScript/TSX syntax | Four files transpiled without syntax diagnostics | Not full application semantic typechecking |
| Python syntax compilation | Passed | Local changed source/test modules |

The storage/worker tests compile the actual worker functions while replacing database/object-store/model dependencies with in-memory doubles. They are not full HTTP/PostgreSQL/S3 integration tests. The Vitest test source is included, but Vitest itself was not run in this environment.

No live NVIDIA call, customer textbook benchmark, full repository build, full application suite, browser end-to-end run, Ruff/mypy run or deployment was completed here. The unchanged NVIDIA client contract test is retained with its failure assertion adapted to the structured inventory stage; it was not executed locally because the NVIDIA dependency/full application environment is absent.

## Explicit scope gaps and acceptance still required

The suggested Docling, LangGraph, PDFium/pdfplumber and PaddleOCR/specialist-recognition integrations were not added. This branch uses the repository's existing PyMuPDF/pypdf, OOXML, Pillow, LibreOffice and LangChain/NVIDIA stack with explicit stage/checkpoint code. No alternative independently evaluated vision model was introduced.

This is not a complete implementation of every advanced detector or fidelity metric in the plan. In particular, complex cross-region table unification, formula-recognition alternatives, advanced inherited Word visibility semantics, image relationship accuracy and full multilingual textbook fidelity require further implementation/evaluation as appropriate. Raw source evidence is preserved and unresolved cases remain blocked.

Before merge/deployment: run the full repository CI and address any lint/type/integration regressions; run the browser review flow with two distinct authorized accounts; validate PostgreSQL transactions and S3 checkpoints/revision conflicts; execute the real NVIDIA image probe and labeled textbook benchmark; test long-document resource limits and worker crash recovery; verify renderer fonts and parser isolation in the deployment container. No container/GPU configuration was changed or deployment performed by this patch.

## Reproduce local verification

From the repository root, in the existing installed environment:

```bash
cd backend
PYTHONPATH=src python tests/check_hybrid_extraction_runtime.py
```

The standalone Node smoke runner requires TypeScript resolvable from NODE_PATH or the root installation. With TypeScript installed under frontend:

```bash
NODE_PATH=./frontend/node_modules node scripts/check-extraction-review.cjs
```

Existing NVIDIA credentials must be configured on the server; do not paste keys into source control. To run the real image probe and extraction together:

```bash
cd backend
PYTHONPATH=src python -m northstar_api.services.extraction_cli /path/to/textbook.pdf \
  --probe-vision --output /path/to/new-review-output
```

The output directory must not already exist. Start with validation_report.txt, then compare extracted_review.txt against retained source images. Make corrections through structured reviews, not by editing TXT independently. A successful export is not a verified release.
