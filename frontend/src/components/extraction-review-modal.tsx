import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  AlertTriangle, Check, ChevronLeft, ChevronRight, Circle, Crop, Download, ExternalLink, FileText, Maximize2, PanelRightClose,
  PanelRightOpen, RotateCcw, ZoomIn, ZoomOut,
} from 'lucide-react';
import { api, type ExtractionAreaResult, type ExtractionBlock, type ExtractionPage, type ExtractionReading, type ExtractionRecord, type ExtractionReviewSubmission } from '@/lib/api';
import { replaceWords, targetFor, type AreaTarget } from '@/components/extraction-area-placement';
import { apiErrorMessage } from '@/lib/api-error-message';
import { Badge, Button, Modal } from '@/components/ui';
import { ExtractedPageView, REGION_STATE_LABELS, SourceRegionOverlay, finalText, regionState, type RegionState } from '@/components/extraction-layout-view';
import { PageEditor, type PageEditorHandle, type RegionEdit } from '@/components/extraction-page-editor';
import type { KnowledgeSource } from '@/types';
import './extraction-review-modal.css';

type Decision = ExtractionReviewSubmission['issueResolutions'][number];
type Issue = ExtractionRecord['issues'][number];

const DEFAULT_BULK_REVIEW_REASON =
  'Reviewed the source evidence and approved all source-verifiable issues on this page.';
const EXTRACTION_POLL_INTERVAL_MS = 3_000;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;

const humanize = (value: string) => {
  const text = value.replaceAll('_', ' ').toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
};

const statusTone = (status: string): 'success' | 'warning' | 'danger' | 'neutral' => {
  if (status === 'verified_release' || status === 'pass' || status === 'passed') return 'success';
  if (status === 'failed' || status === 'fail' || status === 'needs_password') return 'danger';
  if (status === 'needs_review' || status === 'warning' || status === 'blocked') return 'warning';
  return 'neutral';
};

const qualityTone = (score: number) => (score >= 0.9 ? 'success' : score >= 0.7 ? 'warning' : 'danger');

/** What still stands between a saved review and completed training, in plain words. */
function pendingSummary(record: ExtractionRecord): string {
  const reasons = (record.checks ?? []).filter((c) => !['PASS', 'PASSED'].includes(c.status.toUpperCase()))
    .flatMap((c) => (c.name === 'human_acceptance' ? c.details : [`${humanize(c.name)} check has not passed`]))
    .map((detail) => detail
      .replace(/review missing or stale/, 'still needs to be reviewed and saved')
      .replace(/^(\S+): unresolved (\S+)$/, (_m, _id: string, code: string) => `an issue (${humanize(code)}) is still unresolved`));
  return reasons.length
    ? `Review saved. Training completes when: ${[...new Set(reasons)].join('; ')}.`
    : 'Review saved. Training will complete shortly.';
}

function pageReviewState(page: ExtractionPage): 'done' | 'todo' {
  if (!page.primary_review) return 'todo';
  return 'done';
}

function parseReading(value: string | undefined): { reading: ExtractionReading | null; invalid: boolean } {
  try { return { reading: JSON.parse(value ?? 'null') as ExtractionReading | null, invalid: false }; }
  catch { return { reading: null, invalid: true }; }
}

export function ExtractionReviewModal({ source, onClose, onApproved }: {
  source: KnowledgeSource; onClose: () => void; onApproved: (message?: string) => void;
}) {
  const [record, setRecord] = useState<ExtractionRecord | null>(null);
  const [current, setCurrent] = useState(0);
  const [loadedImage, setLoadedImage] = useState<{ sourceId: string; page: number; url: string } | null>(null);
  const [structures, setStructures] = useState<Record<string, string>>({});
  const [links, setLinks] = useState<Record<string, string>>({});
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [allPagesSelected, setAllPagesSelected] = useState(false);
  const [allPagesDialogOpen, setAllPagesDialogOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [blank, setBlank] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [hovered, setHovered] = useState<string | null>(null);
  const [showReview, setShowReview] = useState(true);
  const [showOutlines, setShowOutlines] = useState(true);
  const extractedPane = useRef<HTMLDivElement>(null);
  const sourcePane = useRef<HTMLDivElement>(null);
  const syncing = useRef(false);
  const editorRef = useRef<PageEditorHandle>(null);
  const [view, setView] = useState<'editor' | 'exact'>('editor');
  const [activeRegion, setActiveRegion] = useState<string | null>(null);
  const [loadCount, setLoadCount] = useState(0);
  // Area extraction: the reviewer drags a box on the original page and extracts only that part.
  const [selecting, setSelecting] = useState(false);
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [areaBox, setAreaBox] = useState<number[] | null>(null);
  const [areaResult, setAreaResult] = useState<ExtractionAreaResult | null>(null);
  const [areaLoading, setAreaLoading] = useState(false);
  const [areaError, setAreaError] = useState('');
  const [areaText, setAreaText] = useState('');
  const [cellTexts, setCellTexts] = useState<Record<string, string>>({});
  const sourceFrame = useRef<HTMLDivElement>(null);
  // The live drag lives in a ref too: pointer events can arrive faster than React re-renders.
  const dragRef = useRef<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const initialize = (value: ExtractionRecord) => {
    setRecord(value); setLoadCount((n) => n + 1); setActiveRegion(null);
    setProcessing(false); setError(''); setNotice('');
    setStructures(Object.fromEntries(value.pages.flatMap((p) => (p.blocks ?? []).map((b) =>
      [b.id, JSON.stringify(b.reviewed_structure ?? b.proposed_structure ?? b.visual, null, 2)]))));
    setLinks(Object.fromEntries(value.pages.flatMap((p) => (p.blocks ?? []).map((b) => [b.id, (b.related_block_ids ?? []).join(', ')]))));
    setDecisions({}); setAllPagesSelected(false); setAllPagesDialogOpen(false); setConfirmed(false); setBlank(false); setReason('');
  };

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const load = async () => {
      try {
        const value = await api.knowledge.extraction(source.id);
        if (active) initialize(value);
      } catch (cause) {
        if (!active) return;
        const message = apiErrorMessage(cause, 'Unable to load extraction evidence.');
        if (message.toLowerCase().includes('still processing')) {
          setProcessing(true); setError('');
          setNotice('Extraction is still processing. This review will load automatically when the new evidence is ready.');
          timer = window.setTimeout(() => { void load(); }, EXTRACTION_POLL_INTERVAL_MS);
        } else {
          setProcessing(false); setError(message);
        }
      }
    };
    void load();
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, [source.id]);

  const page = record?.pages[current];
  const imageUrl = loadedImage && page && loadedImage.sourceId === source.id && loadedImage.page === page.number ? loadedImage.url : null;
  useEffect(() => {
    if (!page?.image) return;
    let active = true;
    let url: string | null = null;
    void api.knowledge.extractionPage(source.id, page.number).then((blob) => {
      url = URL.createObjectURL(blob);
      if (active) setLoadedImage({ sourceId: source.id, page: page.number, url });
      else URL.revokeObjectURL(url);
    }).catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load page image.')); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [source.id, page?.number, page?.image]);

  const download = async () => {
    try {
      const blob = await api.knowledge.extractionArchive(source.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `${source.name}-extraction-review.zip`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (cause) { setError(apiErrorMessage(cause, 'Unable to download evidence.')); }
  };

  const openStoredPdf = async () => {
    try {
      const blob = await api.knowledge.extractionSourcePdf(source.id);
      window.open(URL.createObjectURL(blob), '_blank', 'noopener,noreferrer');
    } catch (cause) { setError(apiErrorMessage(cause, 'This source is not a stored PDF.')); }
  };

  const downloadText = async () => {
    try {
      const blob = await api.knowledge.extractionText(source.id);
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `${source.name}-extracted.txt`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (cause) { setError(apiErrorMessage(cause, 'Unable to download extracted text.')); }
  };

  const save = async () => {
    if (!record || !page || !confirmed) return;
    setSaving(true); setError(''); setNotice('');
    try {
      const pagesToSave = allPagesSelected ? record.pages : [page];
      const reviewedPages = pagesToSave.map((reviewPage) => {
        const blocks = (reviewPage.blocks ?? []).filter((b) => b.status !== 'split').map((b) => {
          const structure = JSON.parse(structures[b.id] ?? 'null') as ExtractionReading | null;
          if (!structure || typeof structure.text !== 'string') throw new Error(`Region ${b.id} needs a complete structured reading.`);
          return { id: b.id, selectedText: structure.text, structure,
            relatedBlockIds: (links[b.id] ?? '').split(',').map((v) => v.trim()).filter(Boolean) };
        });
        return { number: reviewPage.number, selectedText: blocks.length ? blocks.map((b) => b.selectedText).join('\n') : reviewPage.native_text,
          reason, structureConfirmed: true, blankConfirmed: reviewPage.number === page.number ? blank : false, blocks };
      });
      const selectedPageNumbers = new Set(pagesToSave.map((reviewPage) => reviewPage.number));
      const result = await api.knowledge.approveExtraction(source.id, {
        extractionRevision: record.extraction_revision,
        allPagesSelected,
        pages: reviewedPages,
        issueResolutions: Object.values(decisions).filter((d) => record.issues.some((i) => i.id === d.id && (selectedPageNumbers.has(i.page) || i.page === 0))),
      });
      if (result.status !== 'needs_review') { onApproved('Verified extraction released'); return; }
      const updated = await api.knowledge.extraction(source.id);
      initialize(updated);
      setNotice(pendingSummary(updated));
    } catch (cause) { setError(apiErrorMessage(cause, cause instanceof Error ? cause.message : 'Unable to save review.')); }
    finally { setSaving(false); }
  };

  const retry = async () => {
    if (saving || released || retrying) return;
    setSaving(true); setRetrying(true); setError(''); setNotice('');
    try { await api.knowledge.retryExtraction(source.id); onApproved('Extraction retry started; source is processing'); }
    catch (cause) {
      const message = apiErrorMessage(cause, 'Unable to retry extraction.');
      if (message.toLowerCase().includes('not awaiting extraction review')) {
        setNotice('Extraction is already queued or processing. Monitor the source status and reopen the review when it returns to needs review.');
      } else {
        setRetrying(false); setError(message);
      }
    }
    finally { setSaving(false); }
  };

  const issues = record?.issues.filter((issue) => issue.page === page?.number || issue.page === 0) ?? [];
  const reviewPages = allPagesSelected && record ? record.pages : page ? [page] : [];
  const reviewPageNumbers = new Set(reviewPages.map((reviewPage) => reviewPage.number));
  const allReviewIssues = record?.issues.filter((issue) => reviewPageNumbers.has(issue.page) || issue.page === 0) ?? [];
  const actionableIssues = allReviewIssues.filter((issue) => issue.status !== 'resolved' && !issue.technical);
  const leaves = (page?.blocks ?? []).filter((b) => b.status !== 'split');
  const reviewLeaves = reviewPages.flatMap((reviewPage) => (reviewPage.blocks ?? []).filter((b) => b.status !== 'split'));
  const released = record?.review_status === 'verified_release';
  const hasTechnicalBlocker = allReviewIssues.some((i) => i.technical && i.status !== 'resolved');
  // A region the text layer and OCR agree on (proposed_structure) does not need a vision reading.
  const hasMissingVisualEvidence = reviewLeaves.some((b) => !b.visual && !b.proposed_structure);
  const evidenceLoading = Boolean(page?.image) && !imageUrl;
  const blocked = record?.schema_version !== 2 || hasTechnicalBlocker
    || hasMissingVisualEvidence || evidenceLoading;
  const blockerMessage = hasTechnicalBlocker
    ? 'Technical extraction failures are present. Reprocess the source before confirming this page.'
    : hasMissingVisualEvidence
      ? 'One or more source regions has no successful visual evidence. Reprocess the source before confirming this page.'
      : evidenceLoading
        ? 'Source evidence is still loading. Wait for it to finish before confirming this page.'
        : record?.schema_version !== 2
          ? 'This extraction uses an outdated evidence schema. Reprocess the source before confirming this page.'
          : '';
  const updateStructure = (id: string, value: string) => { setStructures((s) => ({ ...s, [id]: value })); setConfirmed(false); };
  const clearArea = () => { setAreaBox(null); setAreaResult(null); setAreaError(''); setAreaText(''); setCellTexts({}); setDrag(null); };
  const changePage = (index: number) => { setCurrent(index); setConfirmed(false); setBlank(false); setReason(''); setZoom(1); clearArea(); setSelecting(false); };
  const selectSinglePage = (index: number) => { setAllPagesSelected(false); setAllPagesDialogOpen(false); changePage(index); };
  const selectAllPages = () => {
    if (!record) return;
    setAllPagesSelected(true); setConfirmed(false); setBlank(false);
    setAllPagesDialogOpen(true);
  };
  const setDecision = (issue: Issue, patch: Partial<Decision>) => {
    setConfirmed(false);
    setDecisions((s) => ({ ...s, [issue.id]: { id: issue.id, action: s[issue.id]?.action ?? 'unresolved', reason: s[issue.id]?.reason ?? '', ...patch } }));
  };
  const approveAllIssues = () => {
    if (!actionableIssues.length) return;
    const sharedReason = reason.trim() || DEFAULT_BULK_REVIEW_REASON;
    if (!reason.trim()) setReason(sharedReason);
    setDecisions((currentDecisions) => {
      const next = { ...currentDecisions };
      actionableIssues.forEach((issue) => {
        next[issue.id] = { id: issue.id, action: 'source_verified', reason: sharedReason };
      });
      return next;
    });
    setConfirmed(false);
    setNotice(`Approved ${actionableIssues.length} unresolved issue${actionableIssues.length === 1 ? '' : 's'} using the ${allPagesSelected ? 'all-pages' : 'page'} review reason. Confirm source coverage, then save.`);
  };

  const invalidStructures = reviewLeaves.filter((block) => parseReading(structures[block.id]).invalid);
  const undecidedIssues = actionableIssues.filter((issue) => (decisions[issue.id]?.action ?? 'unresolved') === 'unresolved');
  const readiness: Array<{ done: boolean; label: string }> = page ? [
    { done: !blocked, label: blocked ? 'Resolve the evidence problem shown above' : 'Source evidence is ready' },
    { done: !invalidStructures.length, label: invalidStructures.length ? `Fix invalid structured reading in ${invalidStructures.map((b) => b.id).join(', ')}` : 'Structured readings are valid' },
    { done: !undecidedIssues.length, label: undecidedIssues.length ? `${undecidedIssues.length} flagged issue${undecidedIssues.length === 1 ? '' : 's'} still unresolved (optional, but release stays blocked)` : 'Flagged issues have a decision' },
    { done: Boolean(reason.trim()), label: `Enter a reason for the ${allPagesSelected ? 'all-pages' : 'page'} review` },
    { done: confirmed, label: `Confirm you checked every region on ${allPagesSelected ? 'all selected pages' : 'this page'}` },
  ] : [];
  const zoomBy = (delta: number) => setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round((z + delta) * 100) / 100)));
  const pageCount = record?.pages.length ?? 0;
  const drafts: Record<string, ExtractionReading | null> = Object.fromEntries(leaves.map((b) => [b.id, parseReading(structures[b.id]).reading]));
  const stateCounts = leaves.reduce<Partial<Record<RegionState, number>>>((counts, b) => {
    const state = regionState(b, finalText(b, drafts[b.id] ?? null));
    return { ...counts, [state]: (counts[state] ?? 0) + 1 };
  }, {});
  const selectRegion = (id: string) => {
    setShowReview(true); setActiveRegion(id);
    if (view === 'editor') editorRef.current?.focusRegion(id);
  };
  // An edit in the page editor becomes that region's structured reading, as a card edit used to.
  const applyEdit = (id: string, edit: RegionEdit) => {
    const block = leaves.find((b) => b.id === id);
    const base = parseReading(structures[id]).reading ?? block?.proposed_structure ?? block?.visual
      ?? { kind: block?.type ?? 'paragraph', text: '', complete: true };
    updateStructure(id, JSON.stringify({
      ...base, text: edit.text,
      ...(edit.cells ? { cells: edit.cells } : {}),
      ...(edit.derived_description !== undefined ? { derived_description: edit.derived_description } : {}),
    }, null, 2));
  };
  const openRegions = leaves.filter((b) => ['conflict', 'single', 'failed'].includes(regionState(b, finalText(b, drafts[b.id] ?? null))));
  const active = leaves.find((b) => b.id === activeRegion) ?? null;

  const areaTarget: AreaTarget = page && areaBox ? targetFor(page, areaBox, drafts) : { mode: 'none' };
  const toImagePx = (clientX: number, clientY: number) => {
    const rect = sourceFrame.current?.getBoundingClientRect();
    if (!rect || !page?.width_px || !page.height_px || !rect.width || !rect.height) return null;
    const clamp = (v: number) => Math.min(1, Math.max(0, v));
    return { x: clamp((clientX - rect.left) / rect.width) * page.width_px, y: clamp((clientY - rect.top) / rect.height) * page.height_px };
  };
  const extractArea = async (box: number[], vision = false) => {
    if (!page) return;
    const target = targetFor(page, box, drafts);
    setAreaBox(box); setAreaLoading(true); setAreaError('');
    if (!vision) { setAreaResult(null); setCellTexts({}); }
    try {
      const result = await api.knowledge.extractArea(source.id, page.number, {
        bboxPx: box, vision,
        cells: target.mode === 'cells' ? target.cells.map((c) => ({ row: c.row, column: c.column, bboxPx: c.bbox_px })) : [],
      });
      setAreaResult(result);
      setAreaText(target.mode === 'part' || target.mode === 'whole' || target.mode === 'none' ? result.suggestion.text : '');
      setCellTexts(Object.fromEntries(result.cells.map((c) => [`${c.row},${c.column}`, c.suggestion.text])));
      if (target.mode !== 'none') setHovered(target.block.id);
    } catch (cause) { setAreaError(apiErrorMessage(cause, 'Unable to extract the selected area.')); }
    finally { setAreaLoading(false); }
  };
  const finishDrag = () => {
    const current = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (!current) return;
    const box = [Math.min(current.x0, current.x1), Math.min(current.y0, current.y1), Math.max(current.x0, current.x1), Math.max(current.y0, current.y1)].map(Math.round);
    if (box[2]! - box[0]! < 8 || box[3]! - box[1]! < 8) return;
    setSelecting(false);
    void extractArea(box);
  };
  /** Write the reviewed area text into its place: some words, a whole region, or table cells. */
  const placeArea = () => {
    if (areaTarget.mode === 'none') return;
    const { block } = areaTarget;
    const current = finalText(block, drafts[block.id] ?? null);
    if (areaTarget.mode === 'cells') {
      const draft = drafts[block.id] ?? null;
      const cells = (draft?.cells?.length ? draft.cells : block.proposed_structure?.cells ?? []).map((cell) => {
        const text = cellTexts[`${cell.row},${cell.column}`];
        return text === undefined ? cell : { ...cell, text, state: text ? 'VALUE' : 'BLANK' };
      });
      if (view === 'editor') areaTarget.cells.forEach((c) => editorRef.current?.replaceCell(block.id, c.row, c.column, cellTexts[`${c.row},${c.column}`] ?? c.text));
      else {
        const rows = [...new Set(cells.map((c) => c.row))].sort((a, b) => a - b);
        applyEdit(block.id, { text: rows.map((r) => cells.filter((c) => c.row === r).sort((a, b) => a.column - b.column).map((c) => c.text).join(' | ')).join('\n'), cells });
      }
    } else {
      const next = areaTarget.mode === 'part' ? replaceWords(current, areaTarget.start, areaTarget.end, areaText) : areaText;
      if (view === 'editor' && block.type !== 'figure' && !block.figure_description) {
        if (areaTarget.mode === 'part') editorRef.current?.replaceWords(block.id, areaTarget.start, areaTarget.end, areaText);
        else editorRef.current?.replaceRegionText(block.id, next);
      }
      else applyEdit(block.id, { text: next });
    }
    setNotice(`Placed the extracted area into ${humanize(block.type).toLowerCase()} ${block.id}. Review it, then save the page.`);
    setActiveRegion(block.id); clearArea();
  };
  useEffect(() => {
    if (!selecting && !areaBox) return;
    const cancel = (event: KeyboardEvent) => { if (event.key === 'Escape') { setSelecting(false); setDrag(null); } };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, [selecting, areaBox]);
  const boxStyle = (box: number[]) => page?.width_px && page.height_px ? {
    left: `${(box[0]! / page.width_px) * 100}%`, top: `${(box[1]! / page.height_px) * 100}%`,
    width: `${((box[2]! - box[0]!) / page.width_px) * 100}%`, height: `${((box[3]! - box[1]!) / page.height_px) * 100}%`,
  } : undefined;
  // Keep both page panes on the same spot, so each extracted line sits beside its source line.
  const syncScroll = (from: HTMLDivElement | null, to: HTMLDivElement | null) => {
    if (!from || !to || syncing.current) return;
    syncing.current = true;
    const ratio = (value: number, max: number) => (max > 0 ? value / max : 0);
    to.scrollTop = ratio(from.scrollTop, from.scrollHeight - from.clientHeight) * (to.scrollHeight - to.clientHeight);
    to.scrollLeft = ratio(from.scrollLeft, from.scrollWidth - from.clientWidth) * (to.scrollWidth - to.clientWidth);
    window.requestAnimationFrame(() => { syncing.current = false; });
  };
  const failedChecks = (record?.checks ?? []).filter((c) => statusTone(c.status) !== 'success').length;

  return <Modal open onClose={onClose} size="xl" bodyClassName="xr-modal-body" title={`Review extraction: ${source.name}`}
    description="Compare each page with the original, correct anything that was read wrong, then save. You can edit a trained file at any time; saving retrains it."
    footer={<div className="xr-footer">
      <div className="xr-footer__pager">
        <Button variant="secondary" size="sm" icon={ChevronLeft} disabled={saving || !record || current === 0} onClick={() => changePage(current - 1)}>Previous</Button>
        {pageCount > 0 && <span>{allPagesSelected ? `${pageCount} pages selected` : `Page ${current + 1} of ${pageCount}`}</span>}
        <Button variant="secondary" size="sm" disabled={saving || !record || current >= pageCount - 1} onClick={() => changePage(current + 1)}>Next<ChevronRight aria-hidden="true" /></Button>
      </div>
      <div className="xr-footer__actions">
        <Button variant="secondary" onClick={onClose} disabled={saving}>Close</Button>
        <Button onClick={() => void save()} disabled={saving || !page || blocked || !confirmed || !reason.trim()}>
          {saving ? 'Saving…' : released ? 'Save and retrain' : allPagesSelected ? 'Save all page reviews' : 'Save page review'}
        </Button>
      </div>
    </div>}>
    <div className="xr-top">
      <div className="xr-toolbar">
        <div className="xr-toolbar__meta">
          {record ? <>
            <Badge tone={statusTone(record.review_status)}>{humanize(record.review_status)}</Badge>
            <span>Revision {record.extraction_revision}</span>
            <span aria-hidden="true">·</span>
            <span>{pageCount} source unit{pageCount === 1 ? '' : 's'}</span>
          </> : <span>{processing ? 'Waiting for extraction to finish…' : 'Loading extraction…'}</span>}
        </div>
        <div className="xr-toolbar__tools" role="group" aria-label="Source files">
          <Button variant="ghost" size="sm" icon={ExternalLink} onClick={() => void openStoredPdf()} disabled={!record || saving}>Open PDF</Button>
          <Button variant="ghost" size="sm" icon={FileText} onClick={() => void downloadText()} disabled={!record || saving}>Download text</Button>
          <Button variant="ghost" size="sm" icon={Download} onClick={() => void download()} disabled={!record || saving}>Download evidence</Button>
          <Button variant="secondary" size="sm" icon={RotateCcw} onClick={() => void retry()} disabled={saving || released || retrying || processing}>{retrying || processing ? 'Reprocessing…' : 'Reprocess source'}</Button>
        </div>
      </div>
      {error && <p role="alert" className="xr-banner xr-banner--danger"><AlertTriangle aria-hidden="true" />{error}</p>}
      {notice && <p role="status" className="xr-banner xr-banner--info">{notice}</p>}
      {record && pageCount > 1 && <nav className="xr-pages" aria-label="Source pages">
        <button type="button" className={`xr-page-chip xr-page-chip--all${allPagesSelected ? ' is-selected' : ''}`}
          aria-pressed={allPagesSelected} disabled={saving} onClick={selectAllPages}><Check aria-hidden="true" />Select all pages</button>
        {record.pages.map((p, index) => {
          const state = pageReviewState(p);
          return <button key={p.number} type="button" className={`xr-page-chip xr-page-chip--${state}${allPagesSelected ? ' is-all-selected' : ''}${index === current ? ' is-active' : ''}`}
            aria-current={index === current ? 'page' : undefined} disabled={saving}
            title={state === 'done' ? 'Reviewed' : 'Not reviewed yet'}
            onClick={() => selectSinglePage(index)}>{state === 'done' ? <Check aria-hidden="true" /> : null}{p.number}</button>;
        })}
      </nav>}
    </div>

    {record && (page ? <div className={`xr-layout${showReview ? '' : ' is-compare-only'}`}>
      <section className="xr-source" aria-label="Extracted text beside the original">
        <div className="xr-source__bar">
          <div className="xr-legend" aria-label="Region colours">
            {(Object.keys(REGION_STATE_LABELS) as RegionState[]).filter((s) => stateCounts[s]).map((s) =>
              <span key={s} className={`xr-legend__item xl-swatch--${s}`}>{REGION_STATE_LABELS[s]} · {stateCounts[s]}</span>)}
          </div>
          <div className="xr-zoom">
            <label className="xr-toggle"><input type="checkbox" checked={showOutlines} onChange={(e) => setShowOutlines(e.target.checked)} />Outlines</label>
            <button type="button" className="icon-button" onClick={() => zoomBy(-ZOOM_STEP)} disabled={zoom <= MIN_ZOOM} aria-label="Zoom out"><ZoomOut /></button>
            <span aria-live="polite">{Math.round(zoom * 100)}%</span>
            <button type="button" className="icon-button" onClick={() => zoomBy(ZOOM_STEP)} disabled={zoom >= MAX_ZOOM} aria-label="Zoom in"><ZoomIn /></button>
            <Button variant="ghost" size="sm" onClick={() => setZoom(1)} disabled={zoom === 1}>Reset zoom</Button>
            {imageUrl && <a className="icon-button" href={imageUrl} target="_blank" rel="noreferrer" aria-label="Open full resolution source page"><Maximize2 /></a>}
            <button type="button" className="icon-button" onClick={() => setShowReview((v) => !v)} aria-label={showReview ? 'Hide review panel' : 'Show review panel'} title={showReview ? 'Hide review panel' : 'Show review panel'}>
              {showReview ? <PanelRightClose /> : <PanelRightOpen />}
            </button>
          </div>
        </div>
        <div className={`xr-panes${showOutlines ? '' : ' hide-outlines'}`}>
          <div className="xr-pane">
            <div className="xr-pane__label">
              <span>{view === 'editor' ? 'Extracted text · edit directly' : 'Extracted text · exact word positions'}</span>
              <span className="xr-view-toggle" role="group" aria-label="Extracted view">
                <button type="button" aria-pressed={view === 'editor'} onClick={() => setView('editor')}>Editor</button>
                <button type="button" aria-pressed={view === 'exact'} onClick={() => setView('exact')}>Exact layout</button>
              </span>
            </div>
            <div className="xr-source__viewport" ref={extractedPane} onScroll={() => syncScroll(extractedPane.current, sourcePane.current)}>
              {!page.width_px || !page.height_px
                ? <pre className="xl-plain xl-plain--standalone">{page.selected_text ?? page.native_text}</pre>
                : view === 'editor'
                  ? <PageEditor key={`${page.number}-${loadCount}-${imageUrl ? 1 : 0}`} ref={editorRef} page={page} drafts={drafts} imageUrl={imageUrl} zoom={zoom}
                    readOnly={saving} hovered={hovered} onHover={setHovered} onActiveRegion={setActiveRegion} onChange={applyEdit} />
                  : <ExtractedPageView page={page} drafts={drafts} zoom={zoom} hovered={hovered} onHover={setHovered} onSelect={selectRegion} />}
            </div>
          </div>
          <div className="xr-pane">
            <div className="xr-pane__label">
              <span>Original · page {page.number}</span>
              <button type="button" className={`xr-select-area${selecting ? ' is-active' : ''}`} aria-pressed={selecting}
                disabled={!imageUrl || !page.width_px || saving} onClick={() => { setSelecting((v) => !v); setDrag(null); }}
                title="Drag a box over any part of the original to extract only that part">
                <Crop aria-hidden="true" />{selecting ? 'Drag over the part to extract · Esc to cancel' : 'Select area to extract'}
              </button>
            </div>
            <div className="xr-source__viewport" ref={sourcePane} onScroll={() => syncScroll(sourcePane.current, extractedPane.current)}>
              {imageUrl
                ? <div className={`xl-source${selecting ? ' is-selecting' : ''}`} style={{ width: `${zoom * 100}%` }} ref={sourceFrame}>
                  <img src={imageUrl} alt={`Original source page ${page.number}`} />
                  {page.width_px && page.height_px ? <SourceRegionOverlay page={page} drafts={drafts} hovered={hovered} onHover={setHovered} onSelect={selectRegion} /> : null}
                  {selecting && <div className="xa-capture" aria-label="Drag to select an area of the page"
                    onPointerDown={(event) => {
                      const point = toImagePx(event.clientX, event.clientY);
                      if (!point) return;
                      event.currentTarget.setPointerCapture?.(event.pointerId);
                      dragRef.current = { x0: point.x, y0: point.y, x1: point.x, y1: point.y };
                      setDrag(dragRef.current);
                    }}
                    onPointerMove={(event) => {
                      const point = dragRef.current && toImagePx(event.clientX, event.clientY);
                      if (point && dragRef.current) { dragRef.current = { ...dragRef.current, x1: point.x, y1: point.y }; setDrag(dragRef.current); }
                    }}
                    onPointerUp={finishDrag} />}
                  {drag && <div className="xa-box is-drawing" style={boxStyle([Math.min(drag.x0, drag.x1), Math.min(drag.y0, drag.y1), Math.max(drag.x0, drag.x1), Math.max(drag.y0, drag.y1)])} />}
                  {areaBox && !drag && <div className="xa-box" style={boxStyle(areaBox)} aria-hidden="true" />}
                </div>
                : <div className="xr-source__empty">{evidenceLoading ? 'Loading source image…' : 'No source image for this unit. Compare against the native text instead.'}</div>}
            </div>
          </div>
        </div>
      </section>

      <section className="xr-review" aria-label="Review this page">
        <header className="xr-page-head">
          <div>
            <h3>Source unit {page.number} of {pageCount}</h3>
            <p>Printed label: {page.printed_page_label ?? 'not identified'}</p>
          </div>
          <div className="xr-chips">
            {page.quality && <Badge tone={qualityTone(page.quality.score)}>Quality {Math.round(page.quality.score * 100)}%</Badge>}
            <span className={`xr-chip${page.primary_review ? ' is-done' : ''}`}>Primary review: {page.primary_review ? 'recorded' : 'pending'}</span>
          </div>
        </header>
        {page.quality && <p className="xr-muted">
          Read with {page.quality.method.replaceAll('_', ' ')}{page.quality.reasons.length ? ` · Flagged for: ${page.quality.reasons.map(humanize).join(', ')}` : ' · Native text accepted'}
        </p>}
        {blocked && <p role="alert" className="xr-banner xr-banner--warning"><AlertTriangle aria-hidden="true" />{blockerMessage} The draft package remains available.</p>}
        {released && <p className="xr-banner xr-banner--success"><Check aria-hidden="true" />This file is trained. You can still edit any page; saving retrains it with your changes.</p>}

        <Step number={1} title="Check the page" hint="Edit directly in the extracted page on the left, like a document. Coloured regions show how each part was read; click one to inspect it here.">
          {(areaBox || areaLoading) && <section className="xa-card" aria-label="Selected area">
            <header className="xa-card__head">
              <strong>Selected area</strong>
              <span className="xr-muted">{areaTarget.mode === 'none' ? 'Not inside any region'
                : areaTarget.mode === 'cells' ? `Goes into ${areaTarget.cells.length} cell${areaTarget.cells.length === 1 ? '' : 's'} of table ${areaTarget.block.id}`
                  : areaTarget.mode === 'part' ? `Replaces “${areaTarget.selected.slice(0, 40)}${areaTarget.selected.length > 40 ? '…' : ''}” in ${areaTarget.block.id}`
                    : `Replaces all of ${humanize(areaTarget.block.type).toLowerCase()} ${areaTarget.block.id}`}
                {areaTarget.mode !== 'none' && areaTarget.others > 0 ? ` · also touches ${areaTarget.others} other region${areaTarget.others === 1 ? '' : 's'}, which stay unchanged` : ''}</span>
            </header>
            {areaLoading && <p className="xr-muted" role="status">Reading the selected area…</p>}
            {areaError && <p className="xr-field-error" role="alert">{areaError}</p>}
            {areaResult && <>
              <ul className="xa-readings">
                {([['PDF text layer', areaResult.readings.pdf_text], ['OCR', areaResult.readings.ocr],
                  [areaResult.readings.vision_status === 'complete_unstructured' ? 'Vision · plain text' : 'Vision model', areaResult.readings.vision ?? (areaResult.readings.vision_status === 'not_requested' ? null : 'No reading')]] as const)
                  .filter(([, text]) => text !== null).map(([name, text]) => <li key={name}>
                    <span className="xr-readers__name">{name}</span>
                    <span className="xr-readers__text">{text || 'Nothing read'}</span>
                    {areaTarget.mode !== 'cells' && text && <button type="button" className="xr-readers__use" onClick={() => setAreaText(text)} aria-label={`Use the ${name} reading for the area`}>Use this</button>}
                  </li>)}
              </ul>
              <p className={`xa-verdict${areaResult.suggestion.confirmed ? ' is-confirmed' : ''}`}>
                {areaResult.suggestion.confirmed ? <Check aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
                {areaResult.suggestion.confirmed ? 'Two independent readers agree on this text.' : 'Readers do not agree; check the text against the original before placing it.'}
              </p>
              {areaTarget.mode === 'cells'
                ? <div className="xa-cells">{areaResult.cells.map((cell) => {
                  const key = `${cell.row},${cell.column}`;
                  return <label key={key} className={`xr-field${cell.suggestion.confirmed ? '' : ' is-unconfirmed'}`}>
                    Row {cell.row + 1}, column {cell.column + 1}{cell.suggestion.confirmed ? '' : ` · PDF “${cell.pdf_text}”, OCR “${cell.ocr || 'nothing'}”`}
                    <input value={cellTexts[key] ?? ''} onChange={(e) => setCellTexts((s) => ({ ...s, [key]: e.target.value }))} />
                  </label>;
                })}</div>
                : <label className="xr-field">Extracted text (edit before placing)
                  <textarea rows={Math.min(8, Math.max(2, areaText.split('\n').length + 1))} value={areaText} onChange={(e) => setAreaText(e.target.value)} />
                </label>}
            </>}
            <div className="xa-actions">
              <Button size="sm" icon={Check} onClick={placeArea} disabled={!areaResult || areaLoading || areaTarget.mode === 'none'}>Put in place</Button>
              <Button variant="secondary" size="sm" onClick={() => areaBox && void extractArea(areaBox, true)}
                disabled={!areaBox || areaLoading || areaResult?.readings.vision_status === 'complete'}>Ask the vision model too</Button>
              <Button variant="ghost" size="sm" onClick={() => { clearArea(); setHovered(null); }}>Clear</Button>
            </div>
          </section>}
          {leaves.length === 0 && <p className="xr-muted">No separate regions were detected on this page. Review the native text below.</p>}
          {openRegions.length > 0 && <div className="xr-open">
            <strong>{openRegions.length} region{openRegions.length === 1 ? '' : 's'} need{openRegions.length === 1 ? 's' : ''} your decision</strong>
            <ul>{openRegions.map((block) => <li key={block.id}>
              <button type="button" className={`xr-open__item${activeRegion === block.id ? ' is-active' : ''}`} onClick={() => selectRegion(block.id)}
                onMouseEnter={() => setHovered(block.id)} onMouseLeave={() => setHovered(null)}>
                <span className={`xr-state xl-swatch--${regionState(block, finalText(block, drafts[block.id] ?? null))}`}>{humanize(block.type)}</span>
                <span className="xr-open__text">{(finalText(block, drafts[block.id] ?? null) || block.ocr_text || 'No text read').slice(0, 70)}</span>
              </button>
            </li>)}</ul>
          </div>}
          {openRegions.length === 0 && leaves.length > 0 && <p className="xr-empty"><Check aria-hidden="true" />Every region on this page was settled by agreeing readers. Check it against the original and confirm.</p>}
          {active ? (() => {
            const { reading, invalid } = parseReading(structures[active.id]);
            const state = regionState(active, finalText(active, reading));
            return <fieldset id={`xr-card-${active.id}`} className={`xr-card xr-card--${state}${invalid ? ' is-invalid' : ''}`}>
              <legend><Badge tone="brand">{humanize(active.type)}</Badge><code>{active.id}</code><span className={`xr-state xl-swatch--${state}`}>{REGION_STATE_LABELS[state]}</span></legend>
              <label className="xr-field">Selected region text<textarea rows={3} value={reading?.text ?? ''} disabled={!reading || view === 'editor'} readOnly={view === 'editor'}
                onChange={(e) => updateStructure(active.id, JSON.stringify({ ...reading, text: e.target.value }, null, 2))} /></label>
              {view === 'editor' && <p className="xr-muted">Edit this text in the page on the left; this box mirrors it.</p>}
              {invalid && <p className="xr-field-error">The structured reading below is not valid JSON. Fix it to edit this region.</p>}
              <ReaderComparison block={active} onUse={active.type !== 'table' && !active.figure_description && view === 'editor'
                ? (text) => editorRef.current?.replaceRegionText(active.id, text) : undefined} />
              {active.cell_checks?.some((c) => !c.confirmed) && <p className="xr-note xr-note--warn"><AlertTriangle aria-hidden="true" />
                Cells outlined in red differ between the PDF text and OCR: {active.cell_checks.filter((c) => !c.confirmed).map((c) => `row ${c.row + 1}, column ${c.column + 1} (PDF “${c.pdf}”, OCR “${c.ocr || 'nothing'}”)`).join('; ')}.</p>}
              {active.audit_notes?.map((note) => <p key={note} className="xr-note"><Check aria-hidden="true" />{note}</p>)}
              {active.crop && <RegionEvidence sourceId={source.id} blockId={active.id} />}
              <details className="xr-details"><summary>Advanced: structured evidence and links</summary>
                <p className="xr-muted">Preserve exact source values. Header references use zero-based R0C0 coordinates. Descriptions remain separate from visible text.{active.bbox_px?.length ? ` Source rectangle: ${active.bbox_px.join(', ')} px.` : ''}</p>
                <label className="xr-field">Structured reading for {active.id}<textarea className="xr-mono" rows={10} value={structures[active.id] ?? ''} onChange={(e) => updateStructure(active.id, e.target.value)} /></label>
                <label className="xr-field">Related source block IDs (comma separated)<input value={links[active.id] ?? ''} onChange={(e) => { setLinks((s) => ({ ...s, [active.id]: e.target.value })); setConfirmed(false); }} /></label>
              </details>
            </fieldset>;
          })() : leaves.length > 0 && <p className="xr-muted">Click into any region of the extracted page to see how each reader read it.</p>}
          <details className="xr-details" open={!leaves.length}>
            <summary>Compare raw readings</summary>
            <div className="xr-compare">
              <label className="xr-field">Native source text<textarea readOnly rows={6} value={page.native_text} /></label>
              {page.visual_text !== null && <label className="xr-field">Independent visual reading<textarea readOnly rows={6} value={page.visual_text} /></label>}
            </div>
          </details>
        </Step>

        <Step number={2} title={`Resolve flagged issues${allReviewIssues.length ? ` (${allReviewIssues.length})` : ''}`}
          hint="Decide whether each flag matches the original. Technical failures can only be fixed by reprocessing."
          action={<Button variant="secondary" size="sm" icon={Check} onClick={approveAllIssues} disabled={saving || !record || !page || !actionableIssues.length}>Approve all unresolved issues</Button>}>
          {issues.length === 0 && <p className="xr-empty"><Check aria-hidden="true" />No issues flagged on this page.</p>}
          {issues.map((issue) => {
            const resolved = issue.status === 'resolved';
            const tone = issue.technical && !resolved ? 'danger' : resolved ? 'success' : 'warning';
            return <fieldset key={issue.id} className={`xr-card xr-issue xr-issue--${tone}`}>
              <legend><Badge tone={tone}>{humanize(issue.code)}</Badge><span className="xr-muted">{issue.technical ? 'Technical' : humanize(issue.status ?? 'open')}</span></legend>
              <p>{issue.message}{issue.block_id ? <> · <code>{issue.block_id}</code></> : null}</p>
              {issue.technical && !resolved && <p className="xr-muted">Use <strong>Reprocess source</strong> above to fix this.</p>}
              {!resolved && !issue.technical && <div className="xr-issue__controls">
                <label className="xr-field">Decision for {issue.id}<select value={decisions[issue.id]?.action ?? 'unresolved'} onChange={(e) => setDecision(issue, { action: e.target.value as Decision['action'] })}>
                  <option value="unresolved">Unresolved — block release</option><option value="source_verified">Verified against source</option><option value="source_anomaly">Source mistake preserved</option>
                </select></label>
                <label className="xr-field">Source evidence and reason for {issue.id}<input value={decisions[issue.id]?.reason ?? ''} placeholder="What did you see in the original?" onChange={(e) => setDecision(issue, { reason: e.target.value })} /></label>
              </div>}
            </fieldset>;
          })}
        </Step>

        <Step number={3} title="Confirm and save" hint={allPagesSelected ? 'Record why you are approving all selected pages. The review is saved for every page.' : 'Record why you are approving this page. The review is saved per page.'}>
          <label className="xr-field">Reason for {allPagesSelected ? 'all-pages' : 'page'} review<input value={reason} placeholder="e.g. Compared every value with the original page" onChange={(e) => setReason(e.target.value)} /></label>
          {!leaves.length && !page.native_text && <label className="xr-check"><input type="checkbox" checked={blank} onChange={(e) => setBlank(e.target.checked)} />Source is blank</label>}
          <label className="xr-check" title={blocked ? blockerMessage : undefined}><input type="checkbox" checked={confirmed} disabled={blocked} onChange={(e) => setConfirmed(e.target.checked)} />
            I checked every source region, text, order, table cell, equation and relationship on {allPagesSelected ? 'all selected pages' : 'this page'}.</label>
          <ul className="xr-readiness" aria-label="Before you save">
            {readiness.map((item) => <li key={item.label} className={item.done ? 'is-done' : ''}>{item.done ? <Check aria-hidden="true" /> : <Circle aria-hidden="true" />}{item.label}</li>)}
          </ul>
        </Step>

        <details className="xr-details">
          <summary>Validation checks{record.checks?.length ? ` · ${failedChecks ? `${failedChecks} need attention` : 'all passed'}` : ''}</summary>
          {(record.checks ?? []).length ? <ul className="xr-checks">
            {(record.checks ?? []).map((c) => <li key={c.name}><Badge tone={statusTone(c.status)}>{humanize(c.status)}</Badge><span><strong>{humanize(c.name)}</strong>{c.details.length ? ` — ${c.details.join('; ')}` : ''}</span></li>)}
          </ul> : <p className="xr-muted">No validation checks were reported.</p>}
        </details>
        {record.word && <details className="xr-details"><summary>Word source parts and annotation channels</summary><pre className="xr-mono">{JSON.stringify(record.word, null, 2)}</pre></details>}
      </section>
    </div> : <p className="xr-banner xr-banner--warning">No source units were extracted. Check the validation checks and reprocess a readable source.</p>)}
    <Modal open={allPagesDialogOpen} onClose={() => setAllPagesDialogOpen(false)} size="sm" title="Approve all selected pages"
      description={`${pageCount} pages are selected. This keeps the current extraction review rules and saves all selected pages together.`}
      footer={<div className="xr-all-pages-dialog__actions">
        <Button variant="secondary" onClick={() => setAllPagesDialogOpen(false)} disabled={saving}>Continue reviewing</Button>
        <Button onClick={() => void save()} disabled={saving || !page || blocked || !confirmed || !reason.trim()}>{saving ? 'Saving…' : 'Save all page reviews'}</Button>
      </div>}>
      <div className="xr-all-pages-dialog">
        <Button variant="secondary" size="sm" icon={Check} onClick={approveAllIssues} disabled={saving || !actionableIssues.length}>Approve all unresolved issues</Button>
        <p className="xr-muted">{actionableIssues.length ? `${actionableIssues.length} unresolved non-technical issue${actionableIssues.length === 1 ? '' : 's'} will be approved using the review reason below.` : 'There are no unresolved non-technical issues to approve.'}</p>
        <label className="xr-field">Reason for all-pages review<input value={reason} placeholder="e.g. Compared every value with the original pages" onChange={(e) => { setReason(e.target.value); setConfirmed(false); }} /></label>
        <label className="xr-check" title={blocked ? blockerMessage : undefined}><input type="checkbox" checked={confirmed} disabled={blocked} onChange={(e) => setConfirmed(e.target.checked)} />
          I checked every source region, text, order, table cell, equation and relationship on all selected pages.</label>
        <ul className="xr-readiness" aria-label="Before you save all pages">
          {readiness.map((item) => <li key={item.label} className={item.done ? 'is-done' : ''}>{item.done ? <Check aria-hidden="true" /> : <Circle aria-hidden="true" />}{item.label}</li>)}
        </ul>
      </div>
    </Modal>
  </Modal>;
}

function Step({ number, title, hint, action, children }: { number: number; title: string; hint: string; action?: ReactNode; children: ReactNode }) {
  return <section className="xr-step">
    <header className="xr-step__head">
      <span className="xr-step__num" aria-hidden="true">{number}</span>
      <div><h4>{title}</h4><p>{hint}</p></div>
      {action}
    </header>
    <div className="xr-step__body">{children}</div>
  </section>;
}

const sameReading = (a: string, b: string) => {
  const norm = (v: string) => v.normalize('NFKC').replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
    .replace(/[–—−]/g, '-').replace(/\s+/g, ' ').trim();
  return norm(a) === norm(b);
};

/** Mirrors the backend's ocr_confirms: OCR look-alike glyphs and separator spacing only. */
const ocrLookalike = (a: string, b: string) => {
  const canon = (v: string) => v.normalize('NFKC').replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
    .replace(/[–—−]/g, '-').replace(/[lI|]/g, '1').replace(/[Oo]/g, '0').replace(/[×X]/g, 'x')
    .replace(/\s*([/:;,()])\s*/g, '$1').replace(/\s+/g, ' ').trim();
  return canon(a) === canon(b);
};

function ReaderComparison({ block, onUse }: { block: ExtractionBlock; onUse?: (text: string) => void }) {
  const final = block.selected_text ?? block.proposed_structure?.text ?? null;
  const lined = block.proposed_structure?.text && block.native_text && sameReading(block.proposed_structure.text, block.native_text)
    ? block.proposed_structure.text : block.native_text;
  const readers: Array<{ name: string; text: string | undefined | null; note?: string; use?: string }> = [
    { name: 'PDF text layer', text: block.native_text, use: lined },
    { name: 'OCR', text: block.ocr_text, note: block.ocr_min_confidence != null ? `lowest word confidence ${Math.round(block.ocr_min_confidence)}%` : undefined },
    ...(block.ocr_region_text ? [{ name: 'OCR, region pass', text: block.ocr_region_text, note: 'cropped, contrast-corrected, 2× upscaled' }] : []),
    { name: 'Vision model', text: block.visual?.text },
  ];
  if (!readers.some((r) => r.text)) return null;
  return <details className="xr-details xr-readers" open={final === null || Boolean(onUse)}>
    <summary>Independent readings{final === null ? ' · they disagree' : ''}</summary>
    <ul>
      {readers.map((r) => {
        const exact = Boolean(r.text && final !== null && sameReading(r.text, final));
        const lookalike = !exact && r.name.startsWith('OCR') && Boolean(r.text && final !== null && ocrLookalike(r.text, final));
        const agrees = exact || lookalike;
        return <li key={r.name} className={!r.text ? 'is-missing' : agrees ? 'is-agree' : 'is-differ'}>
          <span className="xr-readers__name">{agrees ? <Check aria-hidden="true" /> : <Circle aria-hidden="true" />}{r.name}
            {r.note ? <small> · {r.note}</small> : null}{lookalike ? <small> · matches except look-alike glyphs</small> : null}</span>
          <span className="xr-readers__text">{r.text || 'No reading'}</span>
          {onUse && r.text && <button type="button" className="xr-readers__use" onClick={() => onUse(r.use ?? r.text!)}
            aria-label={`Use the ${r.name} reading`}>Use this</button>}
        </li>;
      })}
    </ul>
  </details>;
}

function RegionEvidence({ sourceId, blockId }: { sourceId: string; blockId: string }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    let active = true;
    let objectUrl: string | null = null;
    void api.knowledge.extractionRegion(sourceId, blockId).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      if (active) setUrl(objectUrl); else URL.revokeObjectURL(objectUrl);
    }).catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load source crop.')); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [open, sourceId, blockId]);
  return <details className="xr-details" onToggle={(event) => setOpen(event.currentTarget.open)}><summary>Inspect original region crop</summary>
    {error && <p role="alert" className="xr-field-error">{error}</p>}
    {open && url && <a href={url} target="_blank" rel="noreferrer"><img className="xr-crop" src={url} alt={`Source crop ${blockId}`} /></a>}
  </details>;
}
