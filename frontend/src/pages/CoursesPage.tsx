import { Archive, BookOpen, Pencil, Plus, RotateCcw, Search, Trash2 } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useOptionalWorkspace, useToast } from '@/components/providers';
import { canUseDashboardCapability } from '@/features/dashboard/dashboardPermissions';
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader } from '@/components/ui';
import {
  educationApi,
  type CourseStatus,
  type EducationCourse,
} from '@/lib/education-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import { api } from '@/lib/api';
import { leadCrmApi, type ChannelConnectionView } from '@/lib/lead-crm-api';
import './CoursesPage.css';
import { educationEnrollmentApi } from '@/lib/education-enrollment-api';
import { EducationRecordDetail } from '@/features/education/EducationRecordDetail';
import { uniqueStudents } from '@/features/education/educationPresentation';
import '@/features/education/education-design.css';

type CourseFilter = 'all' | CourseStatus;

interface CourseFormState {
  code: string;
  name: string;
  description: string;
  simplifiedWorkflow: boolean;
  assignedAgentId: string;
  allowedChannelConnectionIds: string[];
}

const emptyForm: CourseFormState = { code: '', name: '', description: '', simplifiedWorkflow: false, assignedAgentId: '', allowedChannelConnectionIds: [] };

export function CoursesPage() {
  const courses = useApi(() => educationApi.courses.list());
  const agents = useApi(() => api.agents.list());
  const connections = useApi(() => leadCrmApi.channelConnections());
  const { pushToast } = useToast();
  const canManage = canUseDashboardCapability({ permissions: useOptionalWorkspace()?.activeWorkspace?.permissions }, 'education.manage');
  const [params, setParams] = useSearchParams();
  const batches = useApi(() => educationApi.batches.list());
  const enrollments = useApi(() => educationEnrollmentApi.list());
  const [search, setSearch] = useState(() => params.get('search') ?? '');
  const [status, setStatus] = useState<CourseFilter>('all');
  const [manualEditorOpen, setEditorOpen] = useState(false);
  const editorOpen = canManage && (manualEditorOpen || params.get('create') === '1');
  const [editing, setEditing] = useState<EducationCourse | null>(null);
  const [form, setForm] = useState<CourseFormState>(emptyForm);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<EducationCourse | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<EducationCourse | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [reactivating, setReactivating] = useState<string>();

  const records = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (courses.data ?? []).filter((course) => {
      const matchesStatus = status === 'all' || course.status === status;
      const matchesSearch = !query || `${course.code} ${course.name} ${course.description}`.toLowerCase().includes(query);
      return matchesStatus && matchesSearch;
    });
  }, [courses.data, search, status]);

  const activeCount = (courses.data ?? []).filter((course) => course.status === 'active').length;
  const archivedCount = (courses.data ?? []).filter((course) => course.status === 'archived').length;

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setFormError('');
    setEditorOpen(true);
  };

  const openEdit = (course: EducationCourse) => {
    setEditing(course);
    setForm({ code: course.code, name: course.name, description: course.description, simplifiedWorkflow: course.simplifiedWorkflow ?? false, assignedAgentId: course.assignedAgentId ?? '', allowedChannelConnectionIds: course.allowedChannelConnectionIds ?? [] });
    setFormError('');
    setEditorOpen(true);
  };

  const clearCreate = () => { if (params.has('create')) { const next = new URLSearchParams(params); next.delete('create'); setParams(next, { replace: true }); } };
  const closeEditor = () => {
    if (saving) return;
    clearCreate();
    setEditorOpen(false);
    setEditing(null);
    setForm(emptyForm);
    setFormError('');
  };

  const submitCourse = async (event: FormEvent) => {
    event.preventDefault();
    const code = form.code.trim();
    const name = form.name.trim();
    if (!code) {
      setFormError('Course code is required.');
      return;
    }
    if (name.length < 2) {
      setFormError('Course name must contain at least 2 characters.');
      return;
    }
    if (form.simplifiedWorkflow && !form.assignedAgentId) {
      setFormError('Choose the active Education Agent that this simplified Course will use.');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      if (editing) {
        await educationApi.courses.update(editing.id, {
          code,
          name,
          description: form.description,
          simplifiedWorkflow: form.simplifiedWorkflow,
          assignedAgentId: form.assignedAgentId || null,
          allowedChannelConnectionIds: form.allowedChannelConnectionIds,
          confirmAgentReassignment: editing.assignedAgentId !== (form.assignedAgentId || null) ? window.confirm("Replace this Course's Education Agent? Future student questions will use the replacement after its knowledge is ready.") : undefined,
        });
        pushToast(`${name} updated`);
      } else {
        await educationApi.courses.create({ code, name, description: form.description, simplifiedWorkflow: form.simplifiedWorkflow, assignedAgentId: form.assignedAgentId || undefined, allowedChannelConnectionIds: form.allowedChannelConnectionIds });
        pushToast(`${name} created`);
      }
      closeEditor();
      courses.reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Course could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const archiveCourse = async () => {
    if (!archiveTarget) return;
    setArchiving(true);
    try {
      await educationApi.courses.archive(archiveTarget.id);
      pushToast(`${archiveTarget.name} archived`);
      setArchiveTarget(null);
      courses.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Course could not be archived', 'error');
    } finally {
      setArchiving(false);
    }
  };

  const reactivateCourse = async (course: EducationCourse) => {
    setReactivating(course.id);
    try {
      await educationApi.courses.update(course.id, { status: 'active' });
      pushToast(`${course.name} reactivated`);
      courses.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Course could not be reactivated', 'error');
    } finally {
      setReactivating(undefined);
    }
  };

  const permanentlyDeleteCourse = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await educationApi.courses.permanentlyDelete(deleteTarget.id);
      pushToast(`${deleteTarget.name} deleted permanently`);
      setDeleteTarget(null);
      if (editing?.id === deleteTarget.id) closeEditor();
      courses.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Course could not be deleted', 'error');
    } finally {
      setDeleting(false);
    }
  };

  const selectedCourse = courses.data?.find((c) => c.id === params.get('selected'));
  const selectedMode = params.has('selected');
  const backToList = () => { const next = new URLSearchParams(params); next.delete('selected'); setParams(next); };

  if (courses.loading && !courses.data) return <PageLoader />;
  if (courses.error) {
    return <div className="page courses-page"><Card><EmptyState
      icon={BookOpen}
      title="Courses are unavailable"
      description={courses.error}
      action={<Button onClick={courses.reload}>Try again</Button>}
    /></Card></div>;
  }

  return <div className="page courses-page ed-catalog-page">
    {selectedMode ? selectedCourse ? <EducationRecordDetail key={selectedCourse.id} course={selectedCourse} batches={batches.data ?? []} enrollments={enrollments.data ?? []} associationsReady={!batches.loading && !enrollments.loading && !batches.error && !enrollments.error} associationsError={batches.error || enrollments.error} retryAssociations={() => { batches.reload(); enrollments.reload(); }} onBack={backToList} onEdit={() => openEdit(selectedCourse)} /> : <EmptyState icon={BookOpen} title="Course not found" description="This course is unavailable in the current workspace." action={<Button onClick={backToList}>Back to Courses</Button>} /> : <>
    <div className="page-heading page-heading--split">
      <div>
        <h2>Courses</h2>
        <p>Manage academic courses, cohort batches, enrollments, and connected knowledge.</p>
      </div>
      <Button icon={Plus} onClick={openCreate} disabled={!canManage}>Create course</Button>
    </div>

    <div className="course-stats" aria-label="Course summary">
      <Card><span className="course-stat-icon"><BookOpen /></span><div><strong>{courses.data?.length ?? 0}</strong><small>Total courses</small></div></Card>
      <Card><span className="course-stat-icon course-stat-icon--active"><BookOpen /></span><div><strong>{activeCount}</strong><small>Active</small></div></Card>
      <Card><span className="course-stat-icon course-stat-icon--archived"><Archive /></span><div><strong>{archivedCount}</strong><small>Archived</small></div></Card>
    </div>

    <Card className="course-catalog-card">
      <div className="course-toolbar">
        <div>
          <h3>Course catalog</h3>
          <p>{records.length} shown · {courses.data?.length ?? 0} total</p>
        </div>
        <div className="course-toolbar__filters">
          <label className="course-search">
            <span className="sr-only">Search courses</span>
            <Search />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search code, name, or description"
              aria-label="Search courses"
            />
          </label>
          <label className="course-status-filter">
            <span className="sr-only">Filter courses by status</span>
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value as CourseFilter)}
              aria-label="Filter courses by status"
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </select>
          </label>
        </div>
      </div>

      {records.length ? <div className="course-table-wrap"><table className="course-table">
        <thead><tr><th>Course</th><th>Course code</th><th>Batches</th><th>Students</th><th>Status</th><th>Updated</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{records.map((course) => <tr key={course.id}>
          <td><div className="ed-table-record"><span className="ed-icon"><BookOpen /></span><div><Link to={`?selected=${course.id}`}><strong>{course.name}</strong></Link><small>{course.description || 'No description'}</small></div></div></td>
          <td><code>{course.code}</code></td>
          <td>{batches.data && !batches.error ? <Link to={`/education/batches?courseId=${course.id}`}>{batches.data.filter((b) => b.courseId === course.id).length} batches</Link> : '—'}</td>
          <td>{enrollments.data && !enrollments.error ? uniqueStudents(enrollments.data.filter((e) => e.courseId === course.id)) : '—'}</td>
          <td><Badge tone={course.status === 'active' ? 'success' : 'neutral'}>{course.status}</Badge></td>
          <td><time dateTime={course.updatedAt}>{relativeTime(course.updatedAt)}</time></td>
          <td><div className="course-actions">
            <Button variant="secondary" size="sm" icon={Pencil} disabled={!canManage} onClick={() => openEdit(course)}>Edit</Button>
            <Button variant="danger" size="sm" icon={Trash2} disabled={!canManage} onClick={() => setDeleteTarget(course)}>Delete</Button>
            {course.status === 'active'
              ? <Button variant="ghost" size="sm" icon={Archive} disabled={!canManage} onClick={() => setArchiveTarget(course)}>Archive</Button>
              : <Button
                  variant="secondary"
                  size="sm"
                  icon={RotateCcw}
                  disabled={!canManage || reactivating === course.id}
                  onClick={() => void reactivateCourse(course)}
                >Reactivate</Button>}
          </div></td>
        </tr>)}</tbody>
      </table></div> : <EmptyState
        icon={BookOpen}
        title={courses.data?.length ? 'No matching courses' : 'Create your first course'}
        description={courses.data?.length
          ? 'Try another search or status filter.'
          : 'Create a course, organize its batches and connect students to trusted learning material.'}
        action={!courses.data?.length ? <Button icon={Plus} onClick={openCreate} disabled={!canManage}>Create course</Button> : undefined}
      />}
    </Card>

    </>}
    <Modal
      open={editorOpen}
      onClose={closeEditor}
      title={editing ? 'Edit course' : 'Create course'}
      description="Course codes are normalized and unique inside the active workspace."
      closeDisabled={saving}
      footer={<>
        <Button variant="secondary" onClick={closeEditor} disabled={saving}>Cancel</Button>
        <Button type="submit" form="course-editor-form" disabled={saving}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Create course'}</Button>
      </>}
    >
      <form id="course-editor-form" className="course-editor" onSubmit={(event) => void submitCourse(event)}>
        <div className="two-fields">
          <Field label="Course code" htmlFor="course-code" hint="Example: CMA-P1">
            <input
              id="course-code"
              value={form.code}
              maxLength={40}
              onChange={(event) => setForm((current) => ({ ...current, code: event.target.value.toUpperCase() }))}
              placeholder="CMA-P1"
              autoComplete="off"
            />
          </Field>
          <Field label="Course name" htmlFor="course-name">
            <input
              id="course-name"
              value={form.name}
              maxLength={160}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="CMA Part 1"
              autoComplete="off"
            />
          </Field>
        </div>
        <Field label="Description" htmlFor="course-description" hint="Optional. Describe what this course represents in your academy.">
          <textarea
            id="course-description"
            rows={5}
            maxLength={2000}
            value={form.description}
            onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
            placeholder="Course catalog description"
          />
        </Field>
        <label className="course-simplified-toggle"><input type="checkbox" checked={form.simplifiedWorkflow} onChange={(event) => setForm((current) => ({ ...current, simplifiedWorkflow: event.target.checked, assignedAgentId: event.target.checked ? current.assignedAgentId : '' }))} /> Choose your Agent and bot</label>
        {form.simplifiedWorkflow ? <>
          <Field label="Assigned Education Agent" htmlFor="course-assigned-agent" hint="Students inherit this Agent through the Course.">
            <select className="education-picker-select" id="course-assigned-agent" value={form.assignedAgentId} onChange={(event) => setForm((current) => ({ ...current, assignedAgentId: event.target.value }))} disabled={agents.loading}>
              <option value="">Select an Education Agent</option>
              {(agents.data ?? []).filter((agent) => agent.purpose === 'education' && ['active', 'draft'].includes(agent.status)).map((agent) => <option key={agent.id} value={agent.id}>{agent.name}{agent.status === 'draft' ? ' (draft — activate after enrollment)' : ''}</option>)}
            </select>
          </Field>
          <Field label="Allowed shared bot connections" htmlFor="course-channel-connections" hint="Select every connection that enrolled students may use for this Course.">
            <div id="course-channel-connections" className="course-channel-options" role="group" aria-label="Allowed shared bot connections">
              {(connections.data ?? []).filter((connection: ChannelConnectionView) => ['telegram', 'whatsapp'].includes(connection.provider) && connection.status !== 'disabled').map((connection: ChannelConnectionView) => {
                const selected = form.allowedChannelConnectionIds.includes(connection.id);
                return <label key={connection.id} className="course-channel-option"><input type="checkbox" checked={selected} onChange={() => setForm((current) => ({ ...current, allowedChannelConnectionIds: selected ? current.allowedChannelConnectionIds.filter((id) => id !== connection.id) : [...current.allowedChannelConnectionIds, connection.id] }))} /> {connection.name} ({connection.provider})</label>;
              })}
              {!connections.loading && !(connections.data ?? []).some((connection: ChannelConnectionView) => ['telegram', 'whatsapp'].includes(connection.provider) && connection.status !== 'disabled') ? <p className="course-channel-options__empty">No active bot connections are available.</p> : null}
            </div>
          </Field>
        </> : null}
        {formError ? <p className="course-form-error" role="alert">{formError}</p> : null}
      </form>
    </Modal>

    <Modal
      open={Boolean(archiveTarget)}
      onClose={() => { if (!archiving) setArchiveTarget(null); }}
      title="Archive course?"
      description="Archiving removes the course from active selection without deleting its durable record."
      size="sm"
      closeDisabled={archiving}
      footer={<>
        <Button variant="secondary" disabled={archiving} onClick={() => setArchiveTarget(null)}>Cancel</Button>
        <Button variant="danger" disabled={archiving} onClick={() => void archiveCourse()}>{archiving ? 'Archiving…' : 'Archive course'}</Button>
      </>}
    >
      <p className="course-archive-copy">{archiveTarget ? <><strong>{archiveTarget.code}</strong> · {archiveTarget.name}</> : null}</p>
    </Modal>

    <Modal
      open={Boolean(deleteTarget)}
      onClose={() => { if (!deleting) setDeleteTarget(null); }}
      title="Delete course permanently?"
      description="This cannot be undone. The course, its batches, student enrollments, and course-specific access records will be removed."
      size="sm"
      closeDisabled={deleting}
      footer={<>
        <Button variant="secondary" disabled={deleting} onClick={() => setDeleteTarget(null)}>Cancel</Button>
        <Button variant="danger" disabled={deleting} onClick={() => void permanentlyDeleteCourse()}>{deleting ? 'Deleting…' : 'Delete permanently'}</Button>
      </>}
    >
      <p className="course-archive-copy">{deleteTarget ? <><strong>{deleteTarget.code}</strong> · {deleteTarget.name}</> : null}</p>
      <p className="course-archive-copy">Students, Agents, shared training documents, and other courses will not be deleted.</p>
    </Modal>
  </div>;
}
