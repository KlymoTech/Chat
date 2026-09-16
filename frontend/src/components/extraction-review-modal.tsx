import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { apiErrorMessage } from '@/lib/api-error-message';
import { buildApproval, createDrafts, type BlockDraft, type EvidenceRecord, type IssueDraft, type PageDraft, type SourceStructure } from '@/lib/extraction-review-contract';
import { loadExtraction, submitExtractionReview } from '@/lib/extraction-review-api';
import { Button, Modal } from '@/components/ui';
import type { KnowledgeSource } from '@/types';

export function ExtractionReviewModal({ source, onClose, onApproved }: {
  source: KnowledgeSource; onClose: () => void; onApproved: (message?: string) => void;
}) {
  const [record, setRecord] = useState<EvidenceRecord | null>(null);
  const [drafts, setDrafts] = useState<PageDraft[]>([]);
  const [decisions, setDecisions] = useState<IssueDraft[]>([]);
  const [current, setCurrent] = useState(0);
  const [loadedImage, setLoadedImage] = useState<{ sourceId: string; revision: number; page: number; url: string } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setRecord(null); setCurrent(0); setError('');
    void loadExtraction(source.id).then((value) => {
      if (!active) return;
      setRecord(value); setDrafts(createDrafts(value));
      setDecisions(value.issues.map((issue) => ({ id: issue.id,
        action: issue.status === 'resolved' ? issue.disposition ?? 'unresolved' : 'unresolved',
        reason: issue.resolution_reason ?? '' })));
    }).catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load extraction evidence.')); });
    return () => { active = false; };
  }, [source.id]);

  const page = record?.pages[current];
  const draft = drafts[current];
  const revision = record?.extraction_revision;
  const imageUrl = loadedImage && page && loadedImage.sourceId === source.id && loadedImage.revision === record?.extraction_revision && loadedImage.page === page.number ? loadedImage.url : null;
  useEffect(() => {
    setLoadedImage(null);
    if (!page?.image || revision === undefined) return;
    let active = true;
    let url: string | null = null;
    void api.knowledge.extractionPage(source.id, page.number).then((blob) => {
      url = URL.createObjectURL(blob);
      if (active) setLoadedImage({ sourceId: source.id, revision, page: page.number, url });
      else URL.revokeObjectURL(url);
    }).catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load source page.')); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [source.id, revision, page?.number, page?.image]);

  const updatePage = (patch: Partial<PageDraft>) => setDrafts((values) => values.map((value, i) => i === current ? { ...value, ...patch, confirmed: false } : value));
  const updateBlock = (id: string, patch: Partial<BlockDraft>) => {
    if (!draft) return;
    updatePage({ blocks: draft.blocks.map((block) => block.id === id ? { ...block, ...patch } : block) });
  };
  const updateText = (block: BlockDraft, text: string) => {
    try {
      const structure = JSON.parse(block.structureJson) as SourceStructure | null;
      if (!structure) throw new Error('No visual structure is available. Retry extraction.');
      updateBlock(block.id, { text, structureJson: JSON.stringify({ ...structure, text }, null, 2) });
    } catch { setError('Correct the structured JSON before editing the region transcript.'); }
  };
  const updateStructure = (block: BlockDraft, structureJson: string) => {
    let text = block.text;
    try {
      const parsed = JSON.parse(structureJson) as SourceStructure | null;
      if (parsed && typeof parsed.text === 'string') text = parsed.text;
    } catch { /* Keep invalid intermediate JSON visible; submission remains blocked. */ }
    updateBlock(block.id, { structureJson, text });
  };
  const moveBlock = (index: number, direction: -1 | 1) => {
    if (!draft || index + direction < 0 || index + direction >= draft.blocks.length) return;
    const blocks = [...draft.blocks];
    [blocks[index], blocks[index + direction]] = [blocks[index + direction]!, blocks[index]!];
    updatePage({ blocks });
  };

  const download = async () => {
    try {
      const blob = await api.knowledge.extractionArchive(source.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `${source.name}-extraction-review.zip`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (cause) { setError(apiErrorMessage(cause, 'Unable to download evidence.')); }
  };

  const approve = async () => {
    if (!record) return;
    setSaving(true); setError('');
    try {
      const result = await submitExtractionReview(source.id, buildApproval(record, drafts, decisions));
      onApproved(result.status === 'needs_review'
        ? 'Review saved. Release remains blocked until outstanding checks and independent reviews are complete.'
        : 'Verified extraction accepted; knowledge processing has been scheduled.');
    } catch (cause) { setError(apiErrorMessage(cause, cause instanceof Error ? cause.message : 'Unable to save review.')); }
    finally { setSaving(false); }
  };
  const retry = async () => {
    setSaving(true); setError('');
    try { await api.knowledge.retryExtraction(source.id); onApproved('Extraction retry started; NVIDIA configuration is unchanged.'); }
    catch (cause) { setError(apiErrorMessage(cause, 'Unable to retry extraction.')); }
    finally { setSaving(false); }
  };

  const issues = record?.issues.filter((issue) => issue.page === page?.number || issue.page === 0) ?? [];
  const confirmed = drafts.filter((item) => item.confirmed).length;
  const technicalFailure = record?.issues.some((issue) => issue.technical);
  const projectedText = draft?.blocks.length ? draft.blocks.map((block) => block.text).join('\n') : draft?.text ?? '';
  return <Modal open onClose={onClose} size="lg" title={`Review extraction: ${source.name}`}
    description="Source images and canonical records are evidence. Unresolved content never becomes verified knowledge."
    footer={<><Button variant="secondary" onClick={() => void download()} disabled={!record}>Download TXT, JSON and evidence</Button>
      {technicalFailure && <Button variant="secondary" onClick={() => void retry()} disabled={saving}>Retry failed extraction</Button>}
      <Button variant="secondary" onClick={onClose}>Close</Button>
      <Button onClick={() => void approve()} disabled={saving || !record || Boolean(technicalFailure) || !drafts.length || confirmed !== drafts.length}>
        {saving ? 'Saving review…' : `Save source review (${confirmed}/${drafts.length})`}
      </Button></>}>
    {error && <p role="alert" className="form-error">{error}</p>}
    {!record ? <p>Loading extraction…</p> : page && draft ? <div className="extraction-review">
      <p><strong>Source unit {page.number} of {record.pages.length}</strong> · Revision {record.extraction_revision} · Accuracy: NOT_MEASURED</p>
      <p>Source page: {page.source_page_number ?? 'not paginated'} · Rendered page: {page.rendered_page_number ?? 'none'} · Printed label: {page.printed_page_label ?? 'not identified'} · PDF label: {page.pdf_page_label ?? 'none'}</p>
      <p>Primary reviewer: {page.primary_review?.reviewer ?? 'pending'} · Independent reviewer: {page.second_review?.reviewer ?? 'pending'}
        {page.requires_second_review && ' · This unit requires independent second review.'}</p>
      {technicalFailure && <p role="alert">A technical extraction failure blocks release and cannot be waived. The draft evidence is still available.</p>}
      <details><summary>Validation checks and release blockers</summary>
        {record.checks?.map((check) => <div key={check.name}><strong>{check.name}: {check.status}</strong>
          {check.details.map((detail, index) => <p key={index}>{detail}</p>)}</div>)}
      </details>
      {imageUrl && <><label>Source zoom <input type="range" min="1" max="3" step="0.25" value={zoom} onChange={(event) => setZoom(Number(event.target.value))} /></label>
        <div style={{ overflow: 'auto', maxHeight: 650 }}><img src={imageUrl} alt={`Preserved source unit ${page.number}`} style={{ display: 'block', width: `${zoom * 100}%`, maxWidth: 'none' }} /></div></>}
      {page.image && !imageUrl && <p>Loading original source image…</p>}
      {record.word && <details><summary>Word logical source mappings</summary><p>For ambiguous or continued Word paragraphs, add the listed logical IDs to the relevant region JSON field source_logical_ids. Map every visible fragment before resolving its mapping issue.</p>
        {record.word.blocks.filter((item) => item.part === 'word/document.xml' && item.text).map((item) => <p key={item.id}><code>{item.id}</code> — {item.mapping_status} — Pages {item.rendered_pages.join(', ') || 'unmapped'} — {item.text}</p>)}
      </details>}
      <details><summary>Independent native and visual candidates</summary>
        <label>Native extraction<textarea readOnly rows={6} value={page.native_text} style={{ width: '100%' }} /></label>
        <label>Independent visual extraction<textarea readOnly rows={6} value={page.visual_text ?? 'NOT_APPLICABLE / NOT_COMPLETED'} style={{ width: '100%' }} /></label>
      </details>
      {draft.blocks.map((block, index) => {
        const evidence = page.blocks.find((item) => item.id === block.id);
        return <fieldset key={block.id} style={{ marginTop: 16 }}><legend>{index + 1}. {block.id} — {evidence?.type}</legend>
          <p>Source crop: {evidence?.crop} · Coordinates: {evidence?.bbox_px.join(', ')}</p>
          <div><Button variant="secondary" disabled={index === 0} onClick={() => moveBlock(index, -1)}>Move earlier</Button>
            <Button variant="secondary" disabled={index === draft.blocks.length - 1} onClick={() => moveBlock(index, 1)}>Move later</Button></div>
          {evidence?.review_candidate && <label>Source-based model review proposal (not approved)<textarea readOnly rows={3} value={evidence.review_candidate.text} style={{ width: '100%' }} /></label>}
          <label>Source-verified region text<textarea rows={5} value={block.text} onChange={(event) => updateText(block, event.target.value)} style={{ width: '100%' }} /></label>
          <label>Related source block IDs (comma separated)<input value={block.relatedIds} onChange={(event) => updateBlock(block.id, { relatedIds: event.target.value })} style={{ width: '100%' }} /></label>
          <details open={['table', 'equation', 'question', 'answer_key', 'caption'].includes(evidence?.type ?? '')}>
            <summary>Structured source fields: cells, headers, spans, equations, options and captions</summary>
            <p>Review cells by their zero-based row and column. Header references use R0C1. Preserve printed answers only; never solve a question here. Continued fragments need reciprocal related IDs.</p>
            <textarea aria-label={`Structured source for ${block.id}`} rows={14} spellCheck={false} value={block.structureJson}
              onChange={(event) => updateStructure(block, event.target.value)} style={{ width: '100%', fontFamily: 'monospace' }} />
          </details>
        </fieldset>;
      })}
      <label>Deterministic page projection<textarea readOnly rows={8} value={projectedText} style={{ width: '100%' }} /></label>
      {issues.map((issue) => {
        const decision = decisions.find((value) => value.id === issue.id)!;
        return <fieldset key={issue.id}><legend>{issue.id}: {issue.code}</legend><p>{issue.message}</p>
          <p>Current status: {issue.status ?? 'open'}{issue.technical ? ' — reprocessing required' : ''}</p>
          {!issue.technical && <><label>Source decision<select value={decision.action} onChange={(event) => {
            const action = event.target.value as IssueDraft['action'];
            setDecisions((values) => values.map((value) => value.id === issue.id ? { ...value, action } : value));
            updatePage({});
          }}><option value="unresolved">Keep unresolved</option><option value="source_verified">Verified against source evidence</option><option value="source_anomaly">Source itself contains this anomaly; preserve it</option></select></label>
            <label>Evidence-based reason<input value={decision.reason} onChange={(event) => {
              setDecisions((values) => values.map((value) => value.id === issue.id ? { ...value, reason: event.target.value } : value));
              updatePage({});
            }} style={{ width: '100%' }} /></label></>}
        </fieldset>;
      })}
      <label>Reason for this source-unit review<textarea rows={2} value={draft.reason} onChange={(event) => updatePage({ reason: event.target.value })} style={{ width: '100%' }} /></label>
      {!projectedText && <label><input type="checkbox" checked={draft.blankConfirmed} onChange={(event) => updatePage({ blankConfirmed: event.target.checked })} />The actual source unit is blank, not unreadable.</label>}
      <label><input type="checkbox" checked={draft.confirmed} disabled={Boolean(page.requires_image && !imageUrl) || !draft.reason.trim()}
        onChange={(event) => setDrafts((values) => values.map((value, i) => i === current ? { ...value, confirmed: event.target.checked } : value))} />
        I compared this entire source unit, including region order, table relationships, equations, questions and omitted-content risks.</label>
      <div style={{ display: 'flex', gap: 12, marginTop: 16 }}><Button variant="secondary" disabled={current === 0} onClick={() => setCurrent(current - 1)}>Previous unit</Button>
        <Button variant="secondary" disabled={current === record.pages.length - 1} onClick={() => setCurrent(current + 1)}>Next unit</Button></div>
    </div> : <p>No source units could be extracted. Download the blocked draft to inspect the failure.</p>}
  </Modal>;
}
