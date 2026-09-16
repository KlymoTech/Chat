/* Run after tsc compiles the pure contract into the path supplied by argv[2]. */
const assert = require('node:assert/strict');
const path = require('node:path');
const { createDrafts, buildApproval } = require(path.resolve(process.argv[2]));
let cases = 0;
function test(name, fn) { fn(); cases += 1; console.log(`PASS ${name}`); }
const block = { id: 'P0001-R0001', type: 'question', status: 'candidate', selected_text: null,
  visual: {kind:'question', text:'Which is NOT correct?', complete:true}, bbox_px:[0,0,200,100] };
function fixture() {
  const record = {schema_version:2, extraction_revision:7, source_sha256:'a'.repeat(64), review_status:'needs_review',
    pages:[{number:1, native_text:'Which is correct?', visual_text:block.visual.text, selected_text:null, image:'pages/page_0001.png', blocks:[structuredClone(block)]}],
    issues:[{id:'I1',page:1,code:'CRITICAL_WORD_CONFLICT',message:'NOT differs',status:'open'}]};
  const drafts = createDrafts(record); drafts[0].confirmed=true; drafts[0].reason='Compared the actual image';
  return {record,drafts};
}
test('sends revision and complete structured source review', () => {
  const {record,drafts}=fixture(); const value=buildApproval(record,drafts,[{id:'I1',action:'source_verified',reason:'Image contains NOT'}]);
  assert.equal(value.extractionRevision,7); assert.equal(value.pages[0].selectedText,block.visual.text);
  assert.equal(value.pages[0].structureConfirmed,true); assert.equal(value.pages[0].blocks[0].structure.kind,'question');
  assert.equal(value.issueResolutions[0].action,'source_verified');
});
test('no automatic page approval', () => { const {record}=fixture(); assert.equal(createDrafts(record)[0].confirmed,false); });
test('rejects absent revision', () => { const {record,drafts}=fixture(); delete record.extraction_revision; assert.throws(()=>buildApproval(record,drafts,[])); });
test('rejects unconfirmed source', () => { const {record,drafts}=fixture(); drafts[0].confirmed=false; assert.throws(()=>buildApproval(record,drafts,[])); });
test('rejects omitted source regions', () => { const {record,drafts}=fixture(); drafts[0].blocks=[]; assert.throws(()=>buildApproval(record,drafts,[])); });
test('rejects duplicate source regions', () => { const {record,drafts}=fixture(); drafts[0].blocks.push(drafts[0].blocks[0]); assert.throws(()=>buildApproval(record,drafts,[])); });
test('rejects structured/transcript divergence', () => { const {record,drafts}=fixture(); drafts[0].blocks[0].text='wrong'; assert.throws(()=>buildApproval(record,drafts,[])); });
test('rejects truncated model reading', () => { const {record,drafts}=fixture(); drafts[0].blocks[0].structureJson=JSON.stringify({...block.visual,complete:false}); assert.throws(()=>buildApproval(record,drafts,[])); });
test('technical issues cannot be waived', () => { const {record,drafts}=fixture(); record.issues[0].technical=true; assert.throws(()=>buildApproval(record,drafts,[{id:'I1',action:'source_verified',reason:'approve'}])); });
test('unresolved issues stay unresolved without invented reasons', () => { const {record,drafts}=fixture(); assert.deepEqual(buildApproval(record,drafts,[{id:'I1',action:'unresolved',reason:''}]).issueResolutions,[]); });
console.log(`${cases} contract tests passed`);
