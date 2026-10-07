import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ExtractionReviewModal } from '@/components/extraction-review-modal';
import type { ExtractionRecord } from '@/lib/api';
import type { KnowledgeSource } from '@/types';

const mocks = vi.hoisted(() => ({ extraction: vi.fn(), extractionPage: vi.fn(), approveExtraction: vi.fn(), retryExtraction: vi.fn(), extractionArchive: vi.fn(), extractArea: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { knowledge: mocks } }));
// The real TipTap editor is covered by extraction-page-editor.test.tsx; here a stand-in reports
// region edits the same way, so these tests stay focused on the review workflow.
vi.mock('@/components/extraction-page-editor', async () => {
  const { forwardRef } = await import('react');
  return {
    PageEditor: forwardRef(function PageEditor({ page, onChange }: { page: ExtractionRecord['pages'][number]; onChange: (id: string, edit: { text: string }) => void }) {
      return <div>{page.blocks.map((b) => <label key={b.id}>Edit {b.id}<textarea onChange={(e) => onChange(b.id, { text: e.target.value })} /></label>)}</div>;
    }),
  };
});
const source: KnowledgeSource = { id: 'source', agentId: 'agent', name: 'lesson.pdf', kind: 'file', status: 'needs_review', sizeLabel: '', chunks: 0, updatedAt: '' };
const base: ExtractionRecord = {
  schema_version: 2, extraction_revision: 3, source_sha256: 'hash', review_status: 'needs_review', checks: [], release_blockers: [],
  pages: [{ number: 1, native_text: 'Value -12.50', visual_text: 'Value 12.50', selected_text: null, image: null, width_px: 1000, height_px: 1400,
    blocks: [{ id: 'P0001-R0001', type: 'paragraph', status: 'candidate', native_text: 'Value -12.50', selected_text: null,
      visual: { kind: 'paragraph', text: 'Value 12.50', complete: true } }] }],
  issues: [{ id: 'I000001', page: 1, code: 'NUMERIC_CONFLICT', message: 'Sign differs', status: 'open' }],
};

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  mocks.extraction.mockResolvedValue(structuredClone(base));
  mocks.approveExtraction.mockResolvedValue({ ...source });
});

describe('Extraction source review', () => {
  it('sends versioned structured decisions and keeps the review open until release', async () => {
    const user = userEvent.setup();
    const approved = vi.fn();
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={approved} />);
    await screen.findByText('Source unit 1 of 1');
    await user.type(screen.getByLabelText('Edit P0001-R0001'), 'Value -12.50');
    await user.selectOptions(screen.getByLabelText('Decision for I000001'), 'source_verified');
    await user.type(screen.getByLabelText('Source evidence and reason for I000001'), 'Visible minus sign in original');
    await user.type(screen.getByLabelText('Reason for page review'), 'Compared to the original');
    await user.click(screen.getByRole('checkbox', { name: /I checked every source/ }));
    await user.click(screen.getByRole('button', { name: 'Save page review' }));
    await screen.findByRole('status');
    expect(mocks.approveExtraction).toHaveBeenCalledWith('source', expect.objectContaining({
      extractionRevision: 3,
      pages: [expect.objectContaining({ selectedText: 'Value -12.50', structureConfirmed: true,
        blocks: [expect.objectContaining({ id: 'P0001-R0001', structure: expect.objectContaining({ text: 'Value -12.50' }) })] })],
      issueResolutions: [{ id: 'I000001', action: 'source_verified', reason: 'Visible minus sign in original' }],
    }));
    expect(approved).not.toHaveBeenCalled();
  }, 15_000);

  it('approves every unresolved source issue from one page reason', async () => {
    const user = userEvent.setup();
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await screen.findByText('Source unit 1 of 1');
    const approveAll = screen.getByRole('button', { name: 'Approve all unresolved issues' });
    expect(approveAll).toBeEnabled();
    const confirm = screen.getByRole('checkbox', { name: /I checked every source/ });
    expect(confirm).toBeEnabled();
    await user.click(approveAll);

    expect(screen.getByLabelText('Decision for I000001')).toHaveValue('source_verified');
    expect(screen.getByLabelText('Source evidence and reason for I000001')).toHaveValue(
      'Reviewed the source evidence and approved all source-verifiable issues on this page.',
    );
    expect(screen.getByLabelText('Reason for page review')).toHaveValue(
      'Reviewed the source evidence and approved all source-verifiable issues on this page.',
    );
    expect(screen.getByRole('checkbox', { name: /I checked every source/ })).not.toBeChecked();

    await user.click(screen.getByRole('checkbox', { name: /I checked every source/ }));
    await user.click(screen.getByRole('button', { name: 'Save page review' }));
    await waitFor(() => expect(mocks.approveExtraction).toHaveBeenCalledWith('source', expect.objectContaining({
      issueResolutions: [{ id: 'I000001', action: 'source_verified', reason: 'Reviewed the source evidence and approved all source-verifiable issues on this page.' }],
    })));
  });

  it('blocks technical failures without offering a source-verification override', async () => {
    mocks.extraction.mockResolvedValue({ ...base, issues: [{ id: 'T1', page: 1, code: 'VISION_UNAVAILABLE', message: 'Failed call', technical: true, status: 'open' }] });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await screen.findByText('Failed call');
    expect(screen.getByRole('button', { name: 'Save page review' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: /I checked every source/ })).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent(/Technical extraction failures are present/);
    expect(screen.queryByLabelText('Decision for T1')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download evidence' })).toBeEnabled();
  });

  it('treats an already-running extraction retry as an informational state', async () => {
    const user = userEvent.setup();
    mocks.retryExtraction.mockRejectedValue(new Error('Source is not awaiting extraction review'));
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await screen.findByText('Source unit 1 of 1');

    await user.click(screen.getByRole('button', { name: 'Reprocess source' }));

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/already queued or processing/));
    expect(screen.getByRole('button', { name: 'Reprocessing…' })).toBeDisabled();
  });

  it('shows a live processing state while replacement evidence is being generated', async () => {
    mocks.extraction.mockRejectedValue(new Error('Extraction is still processing; review evidence will be available when processing completes.'));
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);

    await screen.findByText(/Extraction is still processing/);
    expect(screen.getByRole('status')).toHaveTextContent(/Extraction is still processing/);
    expect(screen.getByText('Waiting for extraction to finish…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reprocessing…' })).toBeDisabled();
  });

  it('invalidates confirmation when structured content changes', async () => {
    const user = userEvent.setup();
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await screen.findByLabelText('Edit P0001-R0001');
    const confirm = screen.getByRole('checkbox', { name: /I checked every source/ });
    await user.click(confirm);
    expect(confirm).toBeChecked();
    await user.type(screen.getByLabelText('Edit P0001-R0001'), 'changed');
    expect(confirm).not.toBeChecked();
  });

  it('explains what is still needed before the page can be saved', async () => {
    const user = userEvent.setup();
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    const checklist = await screen.findByRole('list', { name: 'Before you save' });
    expect(checklist).toHaveTextContent('1 flagged issue still unresolved');
    expect(checklist).toHaveTextContent('Enter a reason for the page review');
    await user.selectOptions(screen.getByLabelText('Decision for I000001'), 'source_verified');
    expect(checklist).toHaveTextContent('Flagged issues have a decision');
  });

  it('navigates between source pages from the page strip', async () => {
    const user = userEvent.setup();
    const second = { ...base.pages[0]!, number: 2, native_text: 'Second page', blocks: [] };
    mocks.extraction.mockResolvedValue({ ...structuredClone(base), pages: [structuredClone(base.pages[0]!), second] });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await screen.findByText('Source unit 1 of 2');
    await user.click(screen.getByRole('button', { name: '2' }));
    expect(screen.getByText('Source unit 2 of 2')).toBeInTheDocument();
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('submits every page and all unresolved issues after selecting all pages', async () => {
    const user = userEvent.setup();
    const second = { ...structuredClone(base.pages[0]!), number: 2, native_text: 'Second page value', visual_text: 'Second page value',
      blocks: [{ ...structuredClone(base.pages[0]!.blocks[0]!), id: 'P0002-R0001', native_text: 'Second page value', visual: { kind: 'paragraph' as const, text: 'Second page value', complete: true } }] };
    mocks.extraction.mockResolvedValue({ ...structuredClone(base), pages: [structuredClone(base.pages[0]!), second],
      issues: [...structuredClone(base.issues), { id: 'I000002', page: 2, code: 'TEXT_CONFLICT', message: 'Second page differs', status: 'open' }] });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await screen.findByText('Source unit 1 of 2');

    await user.click(screen.getByRole('button', { name: 'Select all pages' }));
    const dialog = screen.getByRole('dialog', { name: 'Approve all selected pages' });
    expect(screen.getByText('2 pages selected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '1' })).toHaveClass('is-all-selected');
    expect(screen.getByRole('button', { name: '2' })).toHaveClass('is-all-selected');
    await user.click(within(dialog).getByRole('button', { name: 'Approve all unresolved issues' }));
    await user.click(within(dialog).getByRole('checkbox', { name: /all selected pages/ }));
    await user.click(within(dialog).getByRole('button', { name: 'Save all page reviews' }));

    await waitFor(() => expect(mocks.approveExtraction).toHaveBeenCalledWith('source', expect.objectContaining({
      allPagesSelected: true,
      pages: [expect.objectContaining({ number: 1 }), expect.objectContaining({ number: 2 })],
      issueResolutions: expect.arrayContaining([
        expect.objectContaining({ id: 'I000001', action: 'source_verified' }),
        expect.objectContaining({ id: 'I000002', action: 'source_verified' }),
      ]),
    })));
  });

  it('notifies the parent only after the server releases the extraction', async () => {
    const user = userEvent.setup();
    const approved = vi.fn();
    mocks.approveExtraction.mockResolvedValue({ ...source, status: 'processing' });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={approved} />);
    await screen.findByLabelText('Reason for page review');
    await user.type(screen.getByLabelText('Reason for page review'), 'Second source review');
    await user.click(screen.getByRole('checkbox', { name: /I checked every source/ }));
    await user.click(screen.getByRole('button', { name: 'Save page review' }));
    await waitFor(() => expect(approved).toHaveBeenCalledWith('Verified extraction released'));
  });
});

describe('Review panel with the page editor', () => {
  it('lists undecided regions and opens the inspector with every reading', async () => {
    const user = userEvent.setup();
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await screen.findByText('1 region needs your decision');
    expect(screen.getByText('Click into any region of the extracted page to see how each reader read it.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Value 12.50/ }));
    expect(screen.getByText('PDF text layer')).toBeInTheDocument();
    expect(screen.getByText('Vision model')).toBeInTheDocument();
    expect(screen.getByLabelText('Selected region text')).toHaveAttribute('readonly');
  });
});

describe('Extracting only a selected area', () => {
  it('reads the dragged box and puts the reviewed text in place', async () => {
    const user = userEvent.setup();
    if (!window.PointerEvent) Object.assign(window, { PointerEvent: MouseEvent });
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:page'), revokeObjectURL: vi.fn() });
    const record = structuredClone(base);
    record.pages[0]!.image = 'pages/page_0001.png';
    record.pages[0]!.blocks[0]!.bbox_px = [0, 0, 1000, 100];
    mocks.extraction.mockResolvedValue(record);
    mocks.extractionPage.mockResolvedValue(new Blob());
    mocks.extractArea.mockResolvedValue({
      page: 1, bbox_px: [10, 10, 900, 90], words: [], table: null, cells: [],
      readings: { pdf_text: 'Value -12.50', ocr: 'Value -12.50', ocr_min_confidence: 96, ocr_status: 'complete', vision: null, vision_status: 'not_requested' },
      suggestion: { text: 'Value -12.50', source: 'pdf_text_confirmed_by_ocr', confirmed: true },
    });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Exact layout' }));
    const select = screen.getByRole('button', { name: /Select area to extract/ });
    await waitFor(() => expect(select).toBeEnabled());
    await user.click(select);

    const capture = screen.getByLabelText('Drag to select an area of the page');
    capture.parentElement!.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 1400, right: 1000, bottom: 1400, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.pointerDown(capture, { clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerMove(capture, { clientX: 900, clientY: 90, pointerId: 1 });
    fireEvent.pointerUp(capture, { clientX: 900, clientY: 90, pointerId: 1 });

    await waitFor(() => expect(mocks.extractArea).toHaveBeenCalledWith('source', 1, { bboxPx: [10, 10, 900, 90], vision: false, cells: [] }));
    await screen.findByText('Two independent readers agree on this text.');
    expect(screen.getByText('Replaces all of paragraph P0001-R0001')).toBeInTheDocument();
    const text = screen.getByLabelText('Extracted text (edit before placing)');
    expect(text).toHaveValue('Value -12.50');
    await user.clear(text);
    await user.type(text, 'Value -12.50 kg');
    await user.click(screen.getByRole('button', { name: 'Put in place' }));
    expect(await screen.findByText(/Placed the extracted area into paragraph P0001-R0001/)).toBeInTheDocument();

    await user.type(screen.getByLabelText('Reason for page review'), 'Re-read the selected line');
    await user.click(screen.getByRole('checkbox', { name: /I checked every source/ }));
    await user.click(screen.getByRole('button', { name: 'Save page review' }));
    await waitFor(() => expect(mocks.approveExtraction).toHaveBeenCalledWith('source', expect.objectContaining({
      pages: [expect.objectContaining({ blocks: [expect.objectContaining({ selectedText: 'Value -12.50 kg' })] })],
    })));
  }, 15_000);

  it('asks the vision model only when the reviewer requests it', async () => {
    const user = userEvent.setup();
    if (!window.PointerEvent) Object.assign(window, { PointerEvent: MouseEvent });
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:page'), revokeObjectURL: vi.fn() });
    const record = structuredClone(base);
    record.pages[0]!.image = 'pages/page_0001.png';
    record.pages[0]!.blocks[0]!.bbox_px = [0, 0, 1000, 100];
    mocks.extraction.mockResolvedValue(record);
    mocks.extractionPage.mockResolvedValue(new Blob());
    const result = { page: 1, bbox_px: [10, 10, 900, 90], words: [], table: null, cells: [],
      readings: { pdf_text: 'Value -12.50', ocr: 'Value 12.50', ocr_min_confidence: 70, ocr_status: 'complete', vision: null, vision_status: 'not_requested' },
      suggestion: { text: 'Value -12.50', source: 'pdf_text_unconfirmed', confirmed: false } };
    mocks.extractArea.mockResolvedValueOnce(result).mockResolvedValueOnce({ ...result,
      readings: { ...result.readings, vision: 'Value -12.50', vision_status: 'complete' },
      suggestion: { text: 'Value -12.50', source: 'pdf_text_confirmed_by_vision', confirmed: true } });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    const select = await screen.findByRole('button', { name: /Select area to extract/ });
    await waitFor(() => expect(select).toBeEnabled());
    await user.click(select);
    const capture = screen.getByLabelText('Drag to select an area of the page');
    capture.parentElement!.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 1400, right: 1000, bottom: 1400, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.pointerDown(capture, { clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerMove(capture, { clientX: 900, clientY: 90, pointerId: 1 });
    fireEvent.pointerUp(capture, { clientX: 900, clientY: 90, pointerId: 1 });
    await screen.findByText(/Readers do not agree/);
    await user.click(screen.getByRole('button', { name: 'Ask the vision model too' }));
    await waitFor(() => expect(mocks.extractArea).toHaveBeenLastCalledWith('source', 1, expect.objectContaining({ vision: true })));
    expect(await screen.findByText('Two independent readers agree on this text.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ask the vision model too' })).toBeDisabled();
  }, 15_000);
});

describe('Knowing when training completes', () => {
  it('lets a trained file be edited and saved to retrain it', async () => {
    const user = userEvent.setup();
    const onApproved = vi.fn();
    mocks.extraction.mockResolvedValue({ ...structuredClone(base), review_status: 'verified_release', issues: [] });
    mocks.approveExtraction.mockResolvedValue({ ...source, status: 'processing' });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={onApproved} />);
    expect(await screen.findByText(/This file is trained. You can still edit any page/)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Edit P0001-R0001'), 'Value -12.50');
    await user.type(screen.getByLabelText('Reason for page review'), 'Corrected a value');
    await user.click(screen.getByRole('checkbox', { name: /I checked every source/ }));
    await user.click(screen.getByRole('button', { name: 'Save and retrain' }));
    await waitFor(() => expect(onApproved).toHaveBeenCalledWith('Verified extraction released'));
    expect(screen.queryByText(/second review/i)).not.toBeInTheDocument();
  });

  it('explains in plain words what is left after saving', async () => {
    const user = userEvent.setup();
    const saved = { ...structuredClone(base), checks: [{ name: 'human_acceptance', status: 'FAIL', details: ['Page 1: review missing or stale'] }] };
    mocks.extraction.mockResolvedValueOnce(structuredClone(base)).mockResolvedValueOnce(saved);
    mocks.approveExtraction.mockResolvedValue({ ...source, status: 'needs_review' });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await user.type(await screen.findByLabelText('Reason for page review'), 'Checked against the source');
    await user.click(screen.getByRole('checkbox', { name: /I checked every source/ }));
    await user.click(screen.getByRole('button', { name: 'Save page review' }));
    expect(await screen.findByText('Review saved. Training completes when: Page 1: still needs to be reviewed and saved.')).toBeInTheDocument();
  });
});
