import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { EducationOverview } from './EducationOverview';

const mock = vi.hoisted(() => ({
  workspace: { id: 'workspace-a', name: 'Review Academy', permissions: ['education.view', 'education.manage', 'agents.view', 'knowledge.view'] as string[] },
  courses: vi.fn(), batches: vi.fn(), students: vi.fn(), enrollments: vi.fn(), requests: vi.fn(), agents: vi.fn(),
}));
vi.mock('@/components/providers', () => ({ useWorkspace: () => ({ activeWorkspace: mock.workspace }), useAuth: () => ({ session: { user: { role: 'owner' } } }) }));
vi.mock('@/lib/education-api', () => ({ educationApi: { courses: { list: mock.courses }, batches: { list: mock.batches } } }));
vi.mock('@/lib/education-student-api', () => ({ educationStudentApi: { list: mock.students } }));
vi.mock('@/lib/education-enrollment-api', () => ({ educationEnrollmentApi: { list: mock.enrollments } }));
vi.mock('@/lib/education-access-request-api', () => ({ educationAccessRequestApi: { list: mock.requests } }));
vi.mock('@/lib/api', () => ({ api: { agents: { list: mock.agents } } }));
beforeEach(() => {
  vi.clearAllMocks();
  mock.workspace = { id: 'workspace-a', name: 'Review Academy', permissions: ['education.view', 'education.manage', 'agents.view', 'knowledge.view'] };
  mock.courses.mockResolvedValue([{ id: 'course-a', name: 'CMA Part One', code: 'CMA-P1', status: 'active', description: 'Accounting', createdAt: new Date().toISOString() }]);
  mock.batches.mockResolvedValue([]); mock.students.mockResolvedValue([{ id: 'student-a' }, { id: 'student-b' }]);
  mock.enrollments.mockResolvedValue([
    { id: 'enrollment-a', studentId: 'student-a', courseId: 'course-a', status: 'active', startsOn: null, endsOn: null, createdAt: new Date().toISOString() },
    { id: 'enrollment-b', studentId: 'student-a', courseId: 'course-a', status: 'active', startsOn: '2099-01-01', endsOn: null, createdAt: new Date().toISOString() },
  ]);
  mock.requests.mockResolvedValue([]); mock.agents.mockResolvedValue([]);
});
afterEach(cleanup);
const view = () => <MemoryRouter><EducationOverview /></MemoryRouter>;

it('renders export actions as real create/import deep links and counts current valid enrollments', async () => {
  render(view());
  await screen.findByRole('link', { name: 'View course CMA Part One' });
  for (const [name, href] of [
    ['Add Student', '/education/students?create=1'], ['Create Course', '/education/courses?create=1'],
    ['Create Batch', '/education/batches?create=1'], ['Create Enrollment', '/education/enrollments?create=1'],
  ]) expect(screen.getByRole('link', { name })).toHaveAttribute('href', href);
  const metrics = screen.getByRole('region', { name: 'Education summary' });
  expect([...metrics.querySelectorAll('article > strong')].map((e) => e.textContent)).toEqual(['2', '1', '1', '1']);
  expect(screen.getByText('Other / scheduled')).toBeInTheDocument();
  expect(screen.getByText('Import history is not supplied by the current API.')).toBeInTheDocument();
});

it('uses workspace permissions even for an organization owner, without fetching forbidden agent data', async () => {
  mock.workspace.permissions = ['education.view'];
  render(view());
  await screen.findByRole('link', { name: 'View course CMA Part One' });
  expect(screen.queryByRole('link', { name: 'Create Course' })).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'AI Agent Status' })).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Upload Resources' })).not.toBeInTheDocument();
  expect(mock.agents).not.toHaveBeenCalled();
});

it('makes no education requests when education access is denied', async () => {
  mock.workspace.permissions = [];
  render(view());
  expect(screen.getByRole('heading', { name: 'Education access unavailable' })).toBeInTheDocument();
  await act(async () => {});
  for (const endpoint of [mock.courses, mock.batches, mock.students, mock.enrollments, mock.requests, mock.agents]) expect(endpoint).not.toHaveBeenCalled();
});

it('clears the previous workspace before new requests settle', async () => {
  const { rerender } = render(view());
  await screen.findByRole('link', { name: 'View course CMA Part One' });
  mock.workspace = { ...mock.workspace, id: 'workspace-b' };
  let finish!: (courses: unknown[]) => void;
  mock.courses.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
  mock.students.mockResolvedValue([]); mock.enrollments.mockResolvedValue([]);
  rerender(view());
  expect(screen.queryByRole('link', { name: 'View course CMA Part One' })).not.toBeInTheDocument();
  await act(async () => finish([]));
  await screen.findByRole('heading', { name: 'Create your first course' });
  await waitFor(() => expect(mock.courses).toHaveBeenCalledTimes(2));
});

it('does not show zero enrollment totals or a success chart while the API has failed', async () => {
  mock.enrollments.mockRejectedValueOnce(new Error('Enrollment API offline'));
  render(view());
  await screen.findAllByText('Enrollment API offline');
  expect(screen.getByText('Statistics unavailable')).toBeInTheDocument();
  expect(screen.queryByRole('img', { name: 'Enrollments created in the last 7 days' })).not.toBeInTheDocument();
  const alerts = screen.getAllByRole('alert');
  await userEvent.click(within(alerts[0]!).getByRole('button', { name: 'Try again' }));
  expect(await screen.findByRole('img', { name: 'Enrollments created in the last 7 days' })).toBeInTheDocument();
});
