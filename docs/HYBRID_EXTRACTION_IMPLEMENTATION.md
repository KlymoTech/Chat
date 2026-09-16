# Hybrid extraction source verification — implementation record

Branch: `feature/hybrid-extraction-source-verification`  
Base: `ea215e3dd33f9f75a9e89909e65f791a68b0a195`  
Scope: the supplied hybrid educational extraction specification, excluding Qwen.

## NVIDIA preservation

The existing `backend/src/northstar_api/services/vision.py` is not modified. Its Git blob remains `08557d6ceff846dc4e7351de9ff40b24657aad7c`. The provider stays NVIDIA and the model stays `meta/llama-3.2-11b-vision-instruct`. No configuration, environment, model-serving, inference parameters, API keys, chat models or embedding model files are changed. Both `VISION_PRIMARY` and `VISION_REVIEW` call this same original adapter. They are roles, not two independent models. Critical content still needs two different human reviewers.

## Existing architecture retained

The base already contained extraction, knowledge-upload/job handling, object-store checkpoints, revisioned evidence archives, permission/workspace-scoped review endpoints and an extraction modal. This change extends that architecture; it does not claim those existing features as newly created. Uploaded files still enter the existing ingestion worker, remain `NEEDS_REVIEW`, and enter downstream knowledge processing only after the existing approval endpoint observes all release checks passing. Embeddings, retrieval and answer generation are outside this change.

## Implemented or corrected

| Area | Behavior and implementation |
| --- | --- |
| Source identity | Exact original bytes, source/config hashes, stable region identities, strict ZIP/JSON validation, duplicate-key rejection, bounded members and expanded bytes. |
| PDF | Independent pypdf text plus PyMuPDF native geometry, spans, tables, annotations, widgets and direct renders. Native PDF work runs in bounded subprocesses, not concurrent PDF-library threads. Physical, printed, PDF-label and rendered numbering remain distinct. |
| Word | Ordered OOXML inventory, nested/merged tables, run properties, numbering/style XML, native equations, revisions, hidden content, text boxes, comments, notes and relationships. Frozen field/revision derivative and recorded LibreOffice/font/locale provenance. Ambiguous logical-to-page mappings require explicit reviewed source links. |
| Images | Multi-frame accounting, original pixels retained, EXIF orientation and resizing provenance, page/crop evidence; rendered image text remains a candidate. |
| Text | Strict UTF-8/BOM-labelled UTF-16/32 decoding, BOM/line endings/byte and character offsets, no fabricated pages, no ignored invalid bytes and no vision substitution for original text. |
| Independent vision | Native-free full-page inventory followed by typed region reads using the unchanged NVIDIA adapter. Complete raw responses, finish status, parse failures, model/prompt/input hashes retained. |
| Reconciliation | Native/visual comparisons expose numeric, sign, critical-word and symbol discrepancies. Missing native regions receive independent source-crop reads. Disputed candidates get a bounded source-based NVIDIA review proposal; no majority-wins or auto-approval rule. |
| Recovery | Distinct crop splitting, call/depth limits, source-bound checkpoints, failed-unit checkpoints and successful-page reuse. Storage failures propagate for worker retry rather than being mislabeled as document defects. |
| Tables | Explicit states, bounded occupancy, merged anchors, missing/duplicate coordinates, header associations and position checks. Arithmetic or model agreement never rewrites source values. |
| Educational structure | Printed numbering/options/answers, equations, captions, figures and reciprocal cross-page relationships; generated descriptions kept separate from source transcription. |
| Validation | Ten deterministic checks: source/render integrity, schema/identity, coverage, text, tables/numbers, educational structure, visual audit, continuity, export consistency and human acceptance. |
| Reviews | Atomic submissions; invalid input leaves records unchanged. Whole-page evidence fingerprints include geometry, structure, links and candidates. Edits invalidate stale signatures and linked-page acceptance. Distinct second reviewer required for critical content. |
| Corrections | Before/after source records, reviewer, reason, source identity and revision are preserved; the existing API stores the next immutable evidence revision. Source anomalies are labeled without correction. |
| Exports | Deterministic `extracted_review.txt`, `validation_report.txt`, `extracted.json`, `manifest.json`, correction history, page/crop/raw-call artifacts. Tagged records and the visible TXT projection are independently checked against canonical JSON. Drafts remain available when release is blocked. |
| Frontend | Fixed omitted revision/structured review payload. Added block ordering, text/structure editing, explicit issue dispositions, source zoom, revision-bound images, linked fragments, Word mappings, current reviewer state and accurate blocked/saved messages. |
| Benchmark utility | Requires human-adjudicated matching-source ground truth; reports text errors, block recall, table/header/equation/question-link and order metrics separately. No gold data means no accuracy claim. Resource-limited edit comparisons report NOT_MEASURED rather than a fabricated result. |
| Capability probe | Explicit opt-in live NVIDIA image-only random-value probe. The expected value is not included in the prompt. A passing probe proves only basic image input capability, not extraction accuracy. |
| CI | Branch/PR acceptance workflow for backend fixtures, frontend build/contract tests and an unchanged-NVIDIA-adapter guard. |

## Actual local validation

- 70 backend tests passed, including real PDF parsing/rendering, actual LibreOffice Word rendering, Word logical mapping, multiframe images, text encodings, source mutation, evidence tampering, table/header/merge validation, blocked release, independent reviews, stale-review invalidation, checkpoint restart and storage failures.
- 10 frontend wire-contract tests passed after strict TypeScript compilation of the pure contract.
- Python compilation passed for the changed backend modules.
- All vision responses in automated fixture tests were scripted. These are not live NVIDIA accuracy measurements.
- No uploaded customer textbook has been human-adjudicated or scored here.
- The complete repository backend/database/integration suite and full frontend application build were not run locally: this environment contains only the changed modules, not a full dependency-installed checkout.
- A preliminary GitHub Actions run failed before any runner steps executed. Its exact cause is not established. The final workflow must run successfully before treating CI as green.

## Run acceptance checks

From a complete checkout with backend dependencies installed:

```bash
PYTHONPATH=backend/src python -m pytest --noconftest -o addopts= -q backend/tests/test_extraction_source_verification.py
python -m compileall -q backend/src
cd frontend
npm ci
npm run build
npx tsc src/lib/extraction-review-contract.ts --target ES2022 --module commonjs --strict --outDir ../.extraction-contract
# Root output directory must use CommonJS semantics for the .js file.
node tests/check-extraction-review-contract.cjs ../.extraction-contract/extraction-review-contract.js
```

A missing LibreOffice installation skips the Word-render test; it does not prove Word rendering is operational. The CI workflow installs the controlled renderer explicitly. The original standalone `check_hybrid_extraction_runtime.py` from the base predates the current structured API and was not used as acceptance evidence.

## Live NVIDIA capability and benchmark commands

Use the deployment's existing NVIDIA settings, not a new Qwen endpoint:

```bash
PYTHONPATH=backend/src python -m northstar_api.services.extraction_benchmark \
  --probe-nvidia --output nvidia-image-capability.json

PYTHONPATH=backend/src python -m northstar_api.services.extraction_benchmark \
  --candidate extracted.json --ground-truth adjudicated-source.json \
  --output extraction-benchmark.json
```

The probe makes one actual provider call when explicitly run and may consume the normal provider quota. Ground truth must include `human_adjudicated: true`, an `adjudicator`, the matching `source_sha256`, and canonical-style `pages` with human-aligned source block IDs. Do not relabel the model's own extraction as ground truth. Benchmark results are separate artifacts and never overwrite signed extraction records.

## Compatibility and operational gates

Existing completed source content is not reprocessed automatically. Retry pending extractions to regenerate version-4 prompt/validator evidence; older checkpoints intentionally fail identity validation rather than being silently reused. Keep original immutable archives for audit. There are no database migrations in this change.

The attached document proposed Docling, PDFium, LangGraph and optional specialist recognizers. This branch retains the application's existing pypdf/PyMuPDF/OOXML and explicit checkpoint workflow instead of introducing competing parser/orchestration stacks. Docling/PDFium/LangGraph adapters and additional specialist OCR/formula-recognition integrations are **not implemented** here. Difficult sources remain blocked rather than being guessed through these absent adapters. This is a disclosed departure from the suggested stack, not a claim that every optional library was added.

Before production acceptance: run full repository CI, exercise authenticated tenant/workspace API approval and immutable object-store writes against the real deployment, run the NVIDIA probe, evaluate human-adjudicated representative educational documents, and resource/load-test long books. Process resource limits and macro/link restrictions are not a complete operating-system sandbox; deploy parser/render workers with read-only filesystems, least privilege and denied network access. Provider/network behavior, arbitrary corrupted documents, formula recognizer fidelity and universal document completeness are not certified by unit fixtures.

This implementation deliberately reports `NOT_MEASURED` without ground truth and never describes page coverage as extraction accuracy. It does not claim universal perfect extraction or a production-certified full rollout.
