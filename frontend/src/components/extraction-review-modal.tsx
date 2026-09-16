import { useEffect, useState } from 'react';
import { api, type ExtractionRecord } from '@/lib/api';
import { apiErrorMessage } from '@/lib/api-error-message';
import { Button, Modal } from '@/components/ui';
import type { KnowledgeSource } from '@/types';

export function ExtractionReviewModal({ source, onClose, onApproved }: {
  source: KnowledgeSource; onClose: () => void; onApproved: (message?: string) => void;
}) {
  const [record, setRecord] = useState<ExtractionRecord | null>(null);
  const [current, setCurrent] = useState(0);
  const [loadedImage, setLoadedImage] = useState<{ page: number; url: string } | null>(null);
  const [selected, setSelected] = useState<Record<number, string>>({});
  const [confirmed, setConfirmed] = useState<number[]>([]);
  const [reason, setReason] = useState('Compared with the original source evidence');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    void api.knowledge.extraction(source.id).then((value) => {
      if (!active) return;
      setRecord(value);
      setSelected(Object.fromEntries(value.pages.map((page) => [page.number, page.selected_text || page.native_text || page.visual_text || ''])));
    }).catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load extraction evidence.')); });
    return () => { active = false; };
  }, [source.id]);

  const page = record?.pages[current];
  const imageUrl = loadedImage && page && loadedImage.page === page.number ? loadedImage.url : null;
  useEffect(() => {
    if (!page?.image) return;
    let active = true;
    let url: string | null = null;
    void api.knowledge.extractionPage(source.id, page.number).then((blob) => {
      url = URL.createObjectURL(blob);
      if (active) setLoadedImage({ page: page.number, url });
      else URL.revokeObjectURL(url);
    }).catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load page image.')); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [source.id, page?.number, page?.image]);

  const download = async () => {
    try {
      const blob = await api.knowledge.extractionArchive(source.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${source.name}-extraction-review.zip`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (cause) { setError(apiErrorMessage(cause, 'Unable to download evidence.')); }
  };

  const approve = async () => {
    if (!record || confirmed.length !== record.pages.length) return;
    setSaving(true); setError('');
    try {
      await api.knowledge.approveExtraction(source.id, record.pages.map((item) => ({
        number: item.number, selectedText: selected[item.number] ?? '', reason,
      })));
      onApproved();
    } catch (cause) { setError(apiErrorMessage(cause, 'Unable to approve extraction.')); }
    finally { setSaving(false); }
  };

  const retry = async () => {
    setSaving(true); setError('');
    try { await api.knowledge.retryExtraction(source.id); onApproved('Extraction retry started'); }
    catch (cause) { setError(apiErrorMessage(cause, 'Unable to retry extraction.')); }
    finally { setSaving(false); }
  };

  const issues = record?.issues.filter((issue) => issue.page === page?.number) ?? [];
  const cannotApprove = record?.pages.some((item) => item.source_unit === 'logical_document')
    || record?.issues.some((issue) => issue.code === 'VISION_UNAVAILABLE');
  return <Modal open onClose={onClose} size="lg" title={`Review extraction: ${source.name}`}
    description="Compare each page with its source image. Only reviewed text will become searchable knowledge."
    footer={<><Button variant="secondary" onClick={() => void download()} disabled={!record}>Download evidence</Button>
      {record?.issues.some((issue) => issue.code === 'VISION_UNAVAILABLE') && <Button variant="secondary" onClick={() => void retry()} disabled={saving}>Retry visual reading</Button>}
      <Button variant="secondary" onClick={onClose}>Close</Button>
      <Button onClick={() => void approve()} disabled={saving || !record || Boolean(cannotApprove) || confirmed.length !== record.pages.length}>
        {saving ? 'Approving…' : `Approve ${confirmed.length}/${record?.pages.length ?? 0} pages`}
      </Button></>}>
    {error && <p role="alert" className="form-error">{error}</p>}
    {!record ? <p>Loading extraction…</p> : page ? <div className="extraction-review">
      <p><strong>Page {current + 1} of {record.pages.length}</strong> · {record.issues.length} issues across the document</p>
      {cannotApprove && <p role="alert">Verified release is blocked until every required visual reading succeeds and Word has a rendered page derivative. Download the draft evidence for inspection.</p>}
      {issues.map((issue) => <p className="form-error" key={issue.id}>{issue.code}: {issue.message}</p>)}
      {imageUrl && <img src={imageUrl} alt={`Original source page ${page.number}`} style={{ display: 'block', width: '100%', maxHeight: 500, objectFit: 'contain', background: '#f7f7f7' }} />}
      {page.image && !imageUrl && <p>Loading original page…</p>}
      <label>Native extraction<textarea readOnly rows={6} value={page.native_text} style={{ width: '100%' }} /></label>
      {page.visual_text !== null && <label>Independent visual reading<textarea readOnly rows={6} value={page.visual_text} style={{ width: '100%' }} /></label>}
      <label>Text approved for this page<textarea rows={8} value={selected[page.number] ?? ''}
        onChange={(event) => { setSelected((value) => ({ ...value, [page.number]: event.target.value })); setConfirmed((value) => value.filter((number) => number !== page.number)); }}
        style={{ width: '100%' }} /></label>
      <label>Reason for review<input value={reason} onChange={(event) => setReason(event.target.value)} style={{ width: '100%' }} /></label>
      <label><input type="checkbox" checked={confirmed.includes(page.number)} disabled={!imageUrl && Boolean(page.image)}
        onChange={(event) => setConfirmed((value) => event.target.checked ? [...value, page.number] : value.filter((number) => number !== page.number))} />
        I compared this text with the source evidence and resolved this page.</label>
      <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
        <Button variant="secondary" disabled={current === 0} onClick={() => setCurrent(current - 1)}>Previous</Button>
        <Button variant="secondary" disabled={current === record.pages.length - 1} onClick={() => setCurrent(current + 1)}>Next</Button>
      </div>
    </div> : <p>No source units were extracted.</p>}
  </Modal>;
}
