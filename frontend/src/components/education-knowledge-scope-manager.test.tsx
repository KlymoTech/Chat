import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EducationKnowledgeScopeManager } from '@/components/education-knowledge-scope-manager';
import { ToastProvider } from '@/components/providers';
import type { EducationBatch, EducationCourse } from '@/lib/education-api';
import type { EducationKnowledgeScope } from '@/lib/education-knowledge-api';
import type { KnowledgeSource } from '@/types';

const mocks = vi.hoisted(() => ({
  courses: vi.fn<() => Promise<EducationCourse[]>>(),
  batches: vi.fn<() => Promise<EducationBatch[]>>(),
  sourceScopes: vi.fn<(sourceId: string) => Promise<EducationKnowledgeScope[]>>(),
  setSourceScopes: vi.fn(),
  approve: vi.fn(),
  publish: vi.fn(),
}));

vi.mock('@/lib/education-api', () => ({
  educationApi: {
    courses: { list: mocks.courses },
    batches: { list: mocks.batches },
  },
}));

vi.mock('@/lib/education-catalog-api', () => ({
  educationCatalogApi: {
    papers: () => Promise.resolve([
      { id: 'paper-cpa-1', courseId: 'course-cpa', curriculumId: 'curriculum-cpa', code: 'P1', name: 'Paper 1', status: 'active' },
    ]),
  },
}));

vi.mock('@/lib/education-knowledge-api', () => ({
  educationKnowledgeApi: {
    sourceScopes: mocks.sourceScopes,
    setSourceScopes: mocks.setSourceScopes,
    approve: mocks.approve,
    publish: mocks.publish,
  },
}));

const source: KnowledgeSource = {
  id: 'source-1',
  agentId: 'agent-education',
  name: 'CPA Handbook',
  kind: 'text',
  status: 'ready',
  sizeLabel: '20 words',
  chunks: 3,
  updatedAt: '2026-09-10T00:00:00.000Z',
  content: 'CPA private knowledge',
};

const courses: EducationCourse[] = [
  {
    id: 'course-cpa', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CPA',
    name: 'CPA', description: '', status: 'active', createdAt: '', updatedAt: '',
  },
  {
    id: 'course-cma', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CMA',
    name: 'CMA', description: '', status: 'active', createdAt: '', updatedAt: '',
  },
];

const batches: EducationBatch[] = [
  {
    id: 'batch-cpa-a', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-cpa',
    code: 'CPA-A', name: 'CPA Batch A', description: '', startsOn: null, endsOn: null,
    status: 'active', createdAt: '', updatedAt: '',
  },
  {
    id: 'batch-cma-a', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-cma',
    code: 'CMA-A', name: 'CMA Batch A', description: '', startsOn: null, endsOn: null,
    status: 'active', createdAt: '', updatedAt: '',
  },
];

describe('EducationKnowledgeScopeManager', () => {
  beforeEach(() => {
    mocks.courses.mockResolvedValue(courses);
    mocks.batches.mockResolvedValue(batches);
    mocks.sourceScopes.mockResolvedValue([]);
    mocks.setSourceScopes.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('offers a review-and-publish action for a trained draft mapping', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const draft = { id: 'scope-draft', sourceId: source.id, factId: null, agentId: source.agentId, workspaceId: 'workspace-1', courseId: 'course-cpa', paperId: null, batchId: 'batch-cpa-a', materialType: 'notes', extractionRevision: 1, mappingRevision: 1, approvalStatus: 'draft' as const, createdAt: '', updatedAt: '' };
    mocks.sourceScopes.mockResolvedValue([draft]);
    mocks.approve.mockResolvedValue({ ...draft, approvalStatus: 'approved' });
    mocks.publish.mockResolvedValue({ ...draft, approvalStatus: 'published' });
    render(<ToastProvider><EducationKnowledgeScopeManager agentId="agent-education" sources={[source]} /></ToastProvider>);
    await user.click(await screen.findByRole('button', { name: 'Review & publish' }));
    await waitFor(() => expect(mocks.approve).toHaveBeenCalledWith(draft));
    await waitFor(() => expect(mocks.publish).toHaveBeenCalledWith(draft));
  });

  it('marks unscoped Education knowledge as blocked and saves a Course/Batch pair', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <EducationKnowledgeScopeManager agentId="agent-education" sources={[source]} />
      </ToastProvider>,
    );

    expect(await screen.findByText('Unassigned · blocked')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Manage mappings' }));

    const courseSelect = screen.getByLabelText('Course');
    const batchSelect = screen.getByLabelText('Audience');
    await user.selectOptions(courseSelect, 'course-cpa');
    expect(screen.getByRole('option', { name: /CPA-A/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /CMA-A/ })).not.toBeInTheDocument();
    await user.selectOptions(batchSelect, 'batch-cpa-a');
    await user.click(screen.getByRole('button', { name: 'Add assignment' }));
    expect(screen.getByText('CPA · Overview · CPA-A')).toBeInTheDocument();
    expect(screen.queryByLabelText('Curriculum')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Save draft mappings' }));
    await waitFor(() => expect(mocks.setSourceScopes).toHaveBeenCalledWith(
      source.id,
      'agent-education',
      [{ courseId: 'course-cpa', paperId: null, batchId: 'batch-cpa-a', materialType: 'notes' }],  // no curriculum: the server resolves it
    ));
    await waitFor(() => expect(screen.queryByText(/Education scope · CPA Handbook/)).not.toBeInTheDocument());
  });

  it('prevents duplicate Course/Batch pairs before submitting', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <EducationKnowledgeScopeManager agentId="agent-education" sources={[source]} />
      </ToastProvider>,
    );
    await screen.findByText('Unassigned · blocked');
    await user.click(screen.getByRole('button', { name: 'Manage mappings' }));

    for (let index = 0; index < 2; index += 1) {
      await user.selectOptions(screen.getByLabelText('Course'), 'course-cpa');
      await user.selectOptions(screen.getByLabelText('Audience'), 'batch-cpa-a');
      await user.click(screen.getByRole('button', { name: 'Add assignment' }));
    }

    expect(screen.getByRole('alert')).toHaveTextContent('already selected');
    expect(mocks.setSourceScopes).not.toHaveBeenCalled();
  });
});

describe('Course mapping waits for completed training', () => {
  beforeEach(() => {
    mocks.courses.mockResolvedValue(courses);
    mocks.batches.mockResolvedValue(batches);
    mocks.sourceScopes.mockResolvedValue([]);
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('offers mapping only for trained material', async () => {
    render(
      <ToastProvider>
        <EducationKnowledgeScopeManager agentId="agent-education" sources={[
          source, { ...source, id: 'source-review', name: 'draft.pdf', status: 'needs_review' }]} />
      </ToastProvider>,
    );
    expect(await screen.findByText('Map after training: finish the extraction review')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Manage mappings' })).toHaveLength(1);
  });
});

describe('Automatic Course document assignments', () => {
  beforeEach(() => {
    mocks.courses.mockResolvedValue([{ ...courses[0]!, simplifiedWorkflow: true, assignedAgentId: 'agent-education' }]);
    mocks.batches.mockResolvedValue(batches);
    mocks.sourceScopes.mockResolvedValue([{
      id: 'automatic-scope', sourceId: source.id, factId: null, agentId: source.agentId,
      workspaceId: 'workspace-1', courseId: 'course-cpa', paperId: null, batchId: null,
      materialType: 'notes', requiresRelease: false, approvalStatus: 'published', createdAt: '', updatedAt: '',
    }]);
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('does not expose manual mapping controls and uses the Course-ready label', async () => {
    render(
      <ToastProvider>
        <EducationKnowledgeScopeManager
          agentId="agent-education"
          sources={[source, { ...source, id: 'source-review', name: 'draft.pdf', status: 'needs_review' }]}
        />
      </ToastProvider>,
    );

    expect((await screen.findAllByText('Ready for this Course')).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Map after training/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Manage mappings' })).not.toBeInTheDocument();
  });
});

describe('Course mappings without a curriculum step', () => {
  beforeEach(() => {
    mocks.courses.mockResolvedValue(courses);
    mocks.batches.mockResolvedValue(batches);
    mocks.sourceScopes.mockResolvedValue([]);
    mocks.setSourceScopes.mockResolvedValue([]);
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('lists the course’s papers directly and sends no curriculum', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><EducationKnowledgeScopeManager agentId="agent-education" sources={[source]} /></ToastProvider>);
    await user.click(await screen.findByRole('button', { name: 'Manage mappings' }));
    await user.selectOptions(screen.getByLabelText('Course'), 'course-cpa');
    await user.selectOptions(screen.getByLabelText('Paper'), 'paper-cpa-1');
    await user.click(screen.getByRole('button', { name: 'Add assignment' }));
    expect(screen.getByText('CPA · P1 · All batches')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save draft mappings' }));
    await waitFor(() => expect(mocks.setSourceScopes).toHaveBeenCalledWith(source.id, 'agent-education',
      [{ courseId: 'course-cpa', paperId: 'paper-cpa-1', batchId: null, materialType: 'notes' }]));
  });
});
