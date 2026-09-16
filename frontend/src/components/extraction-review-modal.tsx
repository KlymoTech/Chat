import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { apiErrorMessage } from '@/lib/api-error-message';
import { extractionApi, type ReviewInput, type SourceRecord } from '@/lib/extraction-api';
import { buildPageReview, newPageDraft, type PageDraft } from '@/lib/extraction-review-state';
import { Button, Modal } from '@/components/ui';
import type { KnowledgeSource } from '@/types';

type Decision = ReviewInput['issueResolutions'][number];

export function ExtractionReviewModal({ source, onClose, onApproved }: {
  source: KnowledgeSource; onClose: () => void; onApproved: (message?: string) => void;
}) {
  const [record, setRecord] = useState<SourceRecord | null>(null);
  const [current, setCurrent] = useState(0);
  const [loadedImage, setLoadedImage] = useState<{ identity: string; url: string } | null>(null);
  const [drafts, setDrafts] = useState<Record<number, PageDraft>>({});
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const install = useCallback((value: SourceRecord) => {
    setRecord(value);
    setDrafts(Object.fromEntries(value.pages.map((page) => [page.number, newPageDraft(page)])));
    setDecisions({});
    setCurrent((index) => Math.min(index, Math.max(0, value.pages.length - 1)));
  }, []);

  useEffect(() => {
    let active = true;
    setRecord(null); setError(''); setMessage('');
    void extractionApi.load(source.id).then((value) => { if (active) install(value); })
      .catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load extraction evidence.')); });
    return () => { active = false; };
  }, [source.id, install]);

  const page = record?.pages[current];
  const draft = page ? drafts[page.number] : undefined;
  const imageIdentity = `${source.id}:${record?.extraction_revision}:${page?.number}`;
  const imageUrl = loadedImage?.identity === imageIdentity ? loadedImage.url : null;
  useEffect(() => {
    if (!page?.image) return;
    let active = true;
    let url: string | null = null;
    void api.knowledge.extractionPage(source.id, page.number).then((blob) => {
      url = URL.createObjectURL(blob);
      if (active) setLoadedImage({ identity: imageIdentity, url });
      else URL.revokeObjectURL(url);
    }).catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load source image.')); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [source.id, page?.number, page?.image, imageIdentity]);

  const editDraft = (patch: Partial<PageDraft>) => {
    if (!page || !draft) return;
    setDrafts((values) => ({ ...values, [page.number]: { ...draft, ...patch, confirmed: false } }));
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
  const save = async () => {
    if (!record || !record.extraction_revision) return;
    setSaving(true); setError(''); setMessage('');
    try {
      const pages = record.pages.filter((item) => drafts[item.number]?.confirmed)
        .map((item) => buildPageReview(item, drafts[item.number]!));
      if (!pages.length) throw new Error('Confirm at least one source unit.');
      const issueResolutions = Object.values(decisions);
      if (issueResolutions.some((decision) => !decision.reason.trim())) throw new Error('Every issue decision needs a source-based reason.');
      const updated = await extractionApi.approve(source.id, { extractionRevision: record.extraction_revision, pages, issueResolutions });
      if (updated.status === 'processing' || updated.status === 'ready') { onApproved('Verified extraction released to knowledge ingestion.'); return; }
      if (updated.status !== 'needs_review') throw new Error(`Unexpected review state: ${updated.status}. Reload the source status.`);
      install(await extractionApi.load(source.id));
      setMessage('Review saved. Release remains blocked until all checks, source decisions, and required independent second reviews pass.');
    } catch (cause) { setError(apiErrorMessage(cause, 'Unable to save source review. Refresh evidence after a revision conflict.')); }
    finally { setSaving(false); }
  };
  const retry = async () => {
    setSaving(true); setError('');
    try { await api.knowledge.retryExtraction(source.id); onApproved('Extraction retry started; existing source evidence is retained.'); }
    catch (cause) { setError(apiErrorMessage(cause, 'Unable to retry extraction.')); }
    finally { setSaving(false); }
  };
  const refresh = async () => {
    if (Object.values(drafts).some((value) => value.confirmed || value.reason) && !window.confirm('Discard unsaved review edits and reload evidence?')) return;
    try { install(await extractionApi.load(source.id)); setError(''); }
    catch (cause) { setError(apiErrorMessage(cause, 'Unable to refresh evidence.')); }
  };

  const confirmed = Object.values(drafts).filter((value) => value.confirmed).length;
  const issues = record?.issues.filter((issue) => issue.page === 0 || issue.page === page?.number) ?? [];
  const blockingTechnical = record?.issues.some((issue) => issue.technical && issue.status !== 'resolved');
  const ambiguousWord = record?.word?.blocks.filter((block) => block.part === 'word/document.xml' && block.mapping_status === 'ambiguous') ?? [];
  return <Modal open onClose={onClose} size="lg" title={`Review extraction: ${source.name}`}
    description="Review source evidence, structures and relationships. Saving a review is not automatic release."
    footer={<><Button variant="secondary" onClick={() => void download()} disabled={!record || saving}>Download evidence</Button>
      <Button variant="secondary" onClick={() => void refresh()} disabled={saving}>Reload evidence</Button>
      <Button variant="secondary" onClick={() => void retry()} disabled={saving}>Retry extraction</Button>
      <Button variant="secondary" onClick={onClose} disabled={saving}>Close</Button>
      <Button onClick={() => void save()} disabled={saving || !record?.extraction_revision || !confirmed || Boolean(blockingTechnical)}>
        {saving ? 'Saving review…' : `Save ${confirmed} reviewed units`}
      </Button></>}>
    {error && <p role="alert" className="form-error">{error}</p>}
    {message && <p role="status">{message}</p>}
    {record && <p>Revision {record.extraction_revision} · {record.review_status} · Accuracy: {record.metrics?.measured_transcription_accuracy ?? 'NOT_MEASURED'}</p>}
    {blockingTechnical && <p role="alert">A required extraction stage failed. Download the draft, fix the reported cause, and retry. Technical failures cannot be waived.</p>}
    {record?.checks && <details><summary>Validation checks and release blockers</summary>
      {record.checks.map((check) => <p key={check.name}><strong>{check.name}: {check.status}</strong> {check.details?.join('; ')}</p>)}
    </details>}
    {!record ? <p>Loading extraction…</p> : page && draft ? <div className="extraction-review">
      <p><strong>Source unit {page.number} of {record.pages.length}</strong> · {page.source_unit} · source page {page.source_page_number ?? 'not paginated'} · rendered page {page.rendered_page_number ?? 'none'}</p>
      <p>Primary review: {page.primary_review?.reviewer ?? 'pending'}. {page.requires_second_review && `Independent second review: ${page.second_review?.reviewer ?? 'pending'}.`}</p>
      {imageUrl && page.image && <a href={imageUrl} target="_blank" rel="noreferrer"><img src={imageUrl} alt={`Source evidence for unit ${page.number}`} style={{ display: 'block', width: '100%', maxHeight: 500, objectFit: 'contain' }} /></a>}
      {page.image && !imageUrl && <p>Loading source image…</p>}
      <label>Native candidate<textarea readOnly rows={5} value={page.native_text} style={{ width: '100%' }} /></label>
      {page.visual_text !== null && <label>Independent visual candidate<textarea readOnly rows={5} value={page.visual_text} style={{ width: '100%' }} /></label>}
      {page.blocks.filter((block) => block.status !== 'split').map((block) => <fieldset key={block.id} disabled={saving}>
        <legend>{block.id} · {block.type} · bounds {block.bbox_px?.join(', ')}</legend>
        <p>Compare every paragraph, cell, sign and relationship with the source image. Keep source errors; do not solve questions.</p>
        <label>Reviewed structure JSON<textarea rows={12} spellCheck={false} style={{ width: '100%', fontFamily: 'monospace' }}
          value={draft.structures[block.id] ?? 'null'} onChange={(event) => editDraft({ structures: { ...draft.structures, [block.id]: event.target.value } })} /></label>
        <label>Related source block IDs (comma separated; visual IDs or native Word W… IDs)<input style={{ width: '100%' }}
          value={draft.relationships[block.id] ?? ''} onChange={(event) => editDraft({ relationships: { ...draft.relationships, [block.id]: event.target.value } })} /></label>
      </fieldset>)}
      {!page.blocks.length && <label>Exact source text<textarea rows={6} style={{ width: '100%' }} readOnly={page.source_unit === 'bytes'}
        value={draft.text} onChange={(event) => editDraft({ text: event.target.value })} /></label>}
      {ambiguousWord.length > 0 && <details><summary>{ambiguousWord.length} native Word blocks need rendered-source links</summary>
        {ambiguousWord.slice(0, 50).map((block) => <p key={block.id}><strong>{block.id} ({block.type})</strong>: {block.text.slice(0, 250)}</p>)}
        {ambiguousWord.length > 50 && <p>Download the evidence archive for the full native Word inventory.</p>}
      </details>}
      {issues.map((issue) => <fieldset key={issue.id} disabled={saving || Boolean(issue.technical)}>
        <legend>{issue.code} · {issue.status ?? 'open'}</legend><p>{issue.message}</p>
        {issue.technical ? <p>Reprocessing required; no reviewer override.</p> : <>
          <label>Source decision<select value={decisions[issue.id]?.action ?? issue.disposition ?? 'unresolved'} onChange={(event) => {
            setDecisions((values) => ({ ...values, [issue.id]: { id: issue.id, action: event.target.value as Decision['action'], reason: values[issue.id]?.reason ?? issue.resolution_reason ?? '' } }));
            editDraft({});
          }}><option value="unresolved">Unresolved</option><option value="source_verified">Verified against source</option><option value="source_anomaly">Source itself contains this anomaly</option></select></label>
          <label>Decision reason<input style={{ width: '100%' }} value={decisions[issue.id]?.reason ?? issue.resolution_reason ?? ''} onChange={(event) => {
            setDecisions((values) => ({ ...values, [issue.id]: { id: issue.id, action: values[issue.id]?.action ?? issue.disposition ?? 'unresolved', reason: event.target.value } }));
            editDraft({});
          }} /></label>
        </>}
      </fieldset>)}
      <label>Review reason<input style={{ width: '100%' }} value={draft.reason} disabled={saving} onChange={(event) => editDraft({ reason: event.target.value })} /></label>
      <label><input type="checkbox" checked={draft.blankConfirmed} disabled={saving} onChange={(event) => editDraft({ blankConfirmed: event.target.checked })} />This source is genuinely blank, not unreadable.</label>
      <label><input type="checkbox" checked={draft.confirmed} disabled={saving || !draft.reason.trim() || Boolean(page.requires_image && !imageUrl) || Boolean(blockingTechnical)}
        onChange={(event) => setDrafts((values) => ({ ...values, [page.number]: { ...draft, confirmed: event.target.checked } }))} />
        I checked this source unit, all regions, table cells, equations, numbering, and relationships against the retained evidence.</label>
      <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
        <Button variant="secondary" disabled={saving || current === 0} onClick={() => setCurrent(current - 1)}>Previous</Button>
        <Button variant="secondary" disabled={saving || current === record.pages.length - 1} onClick={() => setCurrent(current + 1)}>Next</Button>
      </div>
    </div> : <p>No source units could be extracted. Download the blocked draft and retry after fixing the source problem.</p>}
  </Modal>;
}
