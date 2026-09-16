// Offline contract smoke test; requires the project's TypeScript dev dependency.
// This executes the production payload builder, not a browser or live API test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const filename = path.join(root, 'frontend/src/lib/extraction-review-state.ts');
const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const compiled = new Module(filename, module);
compiled._compile(output.outputText, filename);
const { newPageDraft, buildPageReview } = compiled.exports;
const page = { number: 1, source_unit: 'pdf_page', native_text: 'Do NOT omit −12.50.', selected_text: 'Do NOT omit −12.50.',
  blocks: [{ id: 'P1', status: 'candidate', visual: { kind: 'question', text: 'Do NOT omit −12.50.', complete: true } }] };
let checks = 0;
const check = (run) => { run(); checks += 1; };
check(() => assert.equal(newPageDraft(page).confirmed, false));
check(() => assert.equal(newPageDraft(page).reason, ''));
check(() => assert.throws(() => buildPageReview(page, newPageDraft(page))));
const draft = { ...newPageDraft(page), confirmed: true, reason: 'Compared source.' };
check(() => assert.equal(buildPageReview(page, draft).selectedText, page.native_text));
check(() => assert.equal(buildPageReview(page, draft).structureConfirmed, true));
check(() => assert.throws(() => buildPageReview(page, { ...draft, structures: { P1: 'null' } })));
check(() => assert.throws(() => buildPageReview(page, { ...draft, structures: { P1: '{"kind":"question","text":"Source","complete":false}' } })));
check(() => assert.throws(() => buildPageReview(page, { ...draft, relationships: { P1: 'P2,P2' } })));
check(() => assert.throws(() => buildPageReview({ ...page, source_unit: 'bytes', blocks: [] }, { ...draft, text: 'Changed source' })));
check(() => assert.throws(() => buildPageReview({ ...page, blocks: [], native_text: '' }, { ...draft, text: '' })));
console.log(`${checks} extraction review payload assertions passed (not a browser integration test).`);
