import {
  Ban,
  CheckCircle2,
  Clock3,
  GraduationCap,
  Layers3,
  PauseCircle,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Field, Modal } from '@/components/ui';
import { api } from '@/lib/api';
import { educationApi, type EducationBatch, type EducationCourse } from '@/lib/education-api';
import {
  educationEnrollmentApi,
  type EducationEnrollment,
  type BulkEnrollmentAssignmentInput,
  type EnrollmentCreateInput,
  type EnrollmentPatchInput,
  type EnrollmentStatus,
} from '@/lib/education-enrollment-api';
import type { EducationStudent } from '@/lib/education-student-api';
import type { Agent } from '@/types';
import './student-enrollments-modal.css';

interface StudentEnrollmentsModalProps {
  defaultAgentId?: string;
  student: EducationStudent | null;
  open: boolean;
  onClose: () => void;
}

interface EnrollmentFormState {
  courseId: string;
  batchId: string;
  agentId: string;
  startsOn: string;
  endsOn: string;
  status: 'pending' | 'active';
}

interface BulkAssignmentState {
  courseId: string;
  batchId: string;
  startsOn: string;
  endsOn: string;
}

const emptyForm: EnrollmentFormState = {
  courseId: '',
  batchId: '',
  agentId: '',
  startsOn: '',
  endsOn: '',
  status: 'pending',
};

const statusLabels: Record<EnrollmentStatus, string> = {
  pending: 'Pending',
  active: 'Active',
  suspended: 'Suspended',
  expired: 'Expired',
  revoked: 'Revoked',
  graduated: 'Graduated',
};

function statusTone(status: EnrollmentStatus): 'success' | 'warning' | 'danger' | 'neutral' | 'brand' {
  if (status === 'active') return 'success';
  if (status === 'pending' || status === 'suspended') return 'warning';
  if (status === 'revoked') return 'danger';
  if (status === 'graduated') return 'brand';
  return 'neutral';
}

function dateLabel(value: string | null): string {
  if (!value) return 'No limit';
  return new Date(`${value}T00:00:00`).toLocaleDateString();
}

export function StudentEnrollmentsModal({ student, open, onClose, defaultAgentId }: StudentEnrollmentsModalProps) {
  const { pushToast } = useToast();
  const [enrollments, setEnrollments] = useState<EducationEnrollment[]>([]);
  const [courses, setCourses] = useState<EducationCourse[]>([]);
  const [batches, setBatches] = useState<EducationBatch[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [filter, setFilter] = useState<'all' | EnrollmentStatus>('all');
  const [form, setForm] = useState<EnrollmentFormState>({ ...emptyForm, agentId: defaultAgentId ?? '' });
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [actingId, setActingId] = useState<string>();
  const [editing, setEditing] = useState<EducationEnrollment | null>(null);
  const [bulkMode, setBulkMode] = useState(false);
  const [bulkAgentId, setBulkAgentId] = useState(defaultAgentId ?? '');
  const [bulkStatus, setBulkStatus] = useState<'pending' | 'active'>('pending');
  const [bulkAssignments, setBulkAssignments] = useState<BulkAssignmentState[]>([]);
  useEffect(() => {
    if (open) {
      setForm({ ...emptyForm, agentId: defaultAgentId ?? '' });
      setEditing(null);
      setBulkMode(false);
      setBulkAgentId(defaultAgentId ?? '');
      setBulkAssignments([]);
    }
  }, [open, student?.id, defaultAgentId]);

  const educationAgents = useMemo(
    () => agents.filter((agent) => agent.purpose === 'education'),
    [agents],
  );
  const activeCourses = useMemo(
    () => courses.filter((course) => course.status === 'active'),
    [courses],
  );
  const selectableBatches = useMemo(
    () => batches.filter((batch) => batch.status === 'active' && batch.courseId === form.courseId),
    [batches, form.courseId],
  );
  const visibleEnrollments = useMemo(
    () => enrollments.filter((enrollment) => filter === 'all' || enrollment.status === filter),
    [enrollments, filter],
  );
  const courseById = useMemo(() => new Map(courses.map((course) => [course.id, course])), [courses]);
  const batchById = useMemo(() => new Map(batches.map((batch) => [batch.id, batch])), [batches]);
  const agentById = useMemo(() => new Map(agents.map((agent) => [agent.id, agent])), [agents]);
  const selectedCourse = courseById.get(form.courseId);
  const selectedCourseIsSimplified = Boolean(selectedCourse?.simplifiedWorkflow);

  const load = async () => {
    if (!student) return;
    setLoading(true);
    setLoadError('');
    try {
      const [nextEnrollments, nextCourses, nextBatches, nextAgents] = await Promise.all([
        educationEnrollmentApi.list({ studentId: student.id }),
        educationApi.courses.list(),
        educationApi.batches.list(),
        api.agents.list(),
      ]);
      setEnrollments(nextEnrollments);
      setCourses(nextCourses);
      setBatches(nextBatches);
      setAgents(nextAgents);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Student enrollments could not be loaded.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open || !student) return undefined;
    let cancelled = false;
    void Promise.all([
      educationEnrollmentApi.list({ studentId: student.id }),
      educationApi.courses.list(),
      educationApi.batches.list(),
      api.agents.list(),
    ])
      .then(([nextEnrollments, nextCourses, nextBatches, nextAgents]) => {
        if (cancelled) return;
        setEnrollments(nextEnrollments);
        setCourses(nextCourses);
        setBatches(nextBatches);
        setAgents(nextAgents);
        setLoadError('');
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(error instanceof Error ? error.message : 'Student enrollments could not be loaded.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [open, student]);

  const resetForm = () => {
    setEditing(null);
    setForm({ ...emptyForm, agentId: defaultAgentId ?? '' });
    setFormError('');
    setBulkMode(false);
    setBulkAgentId(defaultAgentId ?? '');
    setBulkAssignments([]);
  };

  const close = () => {
    if (saving || actingId) return;
    setFilter('all');
    resetForm();
    setLoadError('');
    setLoading(true);
    onClose();
  };

  const setCourse = (courseId: string) => {
    const course = courses.find((item) => item.id === courseId);
    setForm((current) => ({ ...current, courseId, batchId: '', startsOn: '', endsOn: '', agentId: course?.simplifiedWorkflow ? (course.assignedAgentId ?? '') : current.agentId }));
  };

  const setBatch = (batchId: string) => {
    const batch = batches.find((item) => item.id === batchId);
    setForm((current) => ({
      ...current,
      batchId,
      startsOn: batch?.startsOn ?? current.startsOn,
      endsOn: batch?.endsOn ?? current.endsOn,
    }));
  };

  const startEdit = (enrollment: EducationEnrollment) => {
    if (!['pending', 'suspended'].includes(enrollment.status)) return;
    setEditing(enrollment);
    setForm({
      courseId: enrollment.courseId,
      batchId: enrollment.batchId,
      agentId: enrollment.agentId,
      startsOn: enrollment.startsOn ?? '',
      endsOn: enrollment.endsOn ?? '',
      status: enrollment.status === 'pending' ? 'pending' : 'active',
    });
    setFormError('');
  };

  const submitEnrollment = async (event: FormEvent) => {
    event.preventDefault();
    if (!student || student.status !== 'active') return;
    if (!form.courseId || !form.batchId || (!selectedCourseIsSimplified && !form.agentId)) {
      setFormError(selectedCourseIsSimplified ? 'Select a Course and Batch.' : 'Select a Course, Batch, and Education Agent.');
      return;
    }
    if (form.startsOn && form.endsOn && form.endsOn < form.startsOn) {
      setFormError('Enrollment end date cannot be before start date.');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      if (editing) {
        const patch: EnrollmentPatchInput = {
          courseId: form.courseId,
          batchId: form.batchId,
          agentId: selectedCourseIsSimplified ? undefined : form.agentId,
          startsOn: form.startsOn || null,
          endsOn: form.endsOn || null,
        };
        await educationEnrollmentApi.update(editing.id, patch);
        pushToast('Enrollment updated');
      } else {
        const input: EnrollmentCreateInput = {
          studentId: student.id,
          courseId: form.courseId,
          batchId: form.batchId,
          agentId: selectedCourseIsSimplified ? undefined : form.agentId,
          startsOn: form.startsOn || null,
          endsOn: form.endsOn || null,
          status: form.status,
        };
        await educationEnrollmentApi.create(input);
        pushToast(form.status === 'active' ? 'Active enrollment created' : 'Pending enrollment created');
      }
      resetForm();
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Enrollment could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const toggleBulkCourse = (course: EducationCourse) => {
    setBulkAssignments((current) => current.some((assignment) => assignment.courseId === course.id)
      ? current.filter((assignment) => assignment.courseId !== course.id)
      : [...current, { courseId: course.id, batchId: '', startsOn: '', endsOn: '' }]);
  };

  const updateBulkAssignment = (courseId: string, patch: Partial<BulkAssignmentState>) => {
    setBulkAssignments((current) => current.map((assignment) => (
      assignment.courseId === courseId ? { ...assignment, ...patch } : assignment
    )));
  };

  const submitBulkEnrollments = async (event: FormEvent) => {
    event.preventDefault();
    if (!student || student.status !== 'active') return;
    if (!bulkAgentId || !bulkAssignments.length || bulkAssignments.some((assignment) => !assignment.batchId)) {
      setFormError('Select an Education Agent, at least one Course, and one Batch for every selected Course.');
      return;
    }
    if (bulkAssignments.some((assignment) => assignment.startsOn && assignment.endsOn && assignment.endsOn < assignment.startsOn)) {
      setFormError('Enrollment end date cannot be before start date.');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      const assignments: BulkEnrollmentAssignmentInput[] = bulkAssignments.map((assignment) => ({
        courseId: assignment.courseId,
        batchId: assignment.batchId,
        startsOn: assignment.startsOn || null,
        endsOn: assignment.endsOn || null,
      }));
      const created = await educationEnrollmentApi.bulkCreate({
        studentId: student.id, agentId: bulkAgentId, assignments, status: bulkStatus,
      });
      pushToast(`${created.length} enrollment${created.length === 1 ? '' : 's'} created`);
      resetForm();
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Enrollments could not be created.');
    } finally {
      setSaving(false);
    }
  };

  const updateStatus = async (enrollment: EducationEnrollment, status: EnrollmentStatus, message: string) => {
    if (!student || student.status !== 'active') {
      pushToast('Reactivate the Student before changing enrollment access.', 'error');
      return;
    }
    setActingId(enrollment.id);
    try {
      await educationEnrollmentApi.update(enrollment.id, { status });
      pushToast(message);
      await load();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Enrollment status could not be changed.', 'error');
    } finally {
      setActingId(undefined);
    }
  };

  const revoke = async (enrollment: EducationEnrollment) => {
    if (!student || student.status !== 'active') {
      pushToast('Reactivate the Student before changing enrollment access.', 'error');
      return;
    }
    setActingId(enrollment.id);
    try {
      await educationEnrollmentApi.revoke(enrollment.id);
      pushToast('Enrollment revoked');
      await load();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Enrollment could not be revoked.', 'error');
    } finally {
      setActingId(undefined);
    }
  };

  return <Modal
    open={open}
    onClose={close}
    title={student ? `${student.name} · Enrollments` : 'Student enrollments'}
    description={`Assign Course, Batch, validity, and access status. Simplified Courses inherit their Education Agent automatically. Student WhatsApp: ${student?.whatsappNumber || 'not added - edit the student profile'}${student?.whatsappNumber ? student.whatsappVerified ? ' (verified)' : ' (verification needed)' : ''}.`}
    size="lg"
    closeDisabled={saving || Boolean(actingId)}
    footer={<Button variant="secondary" onClick={close} disabled={saving || Boolean(actingId)}>Close</Button>}
  >
    {student ? <div className="enrollment-manager">
      <div className="enrollment-manager__student">
        <span><strong>{student.studentNumber}</strong><small>{student.email ?? 'No profile email'}</small></span>
        <Badge tone={student.status === 'active' ? 'success' : 'neutral'}>{student.status}</Badge>
      </div>

      {student.status === 'active' ? <form className="enrollment-editor" onSubmit={(event) => void (bulkMode ? submitBulkEnrollments(event) : submitEnrollment(event))} noValidate>
        <div className="enrollment-editor__heading">
          <div>
            <h3>{bulkMode ? 'Assign multiple courses' : editing ? 'Edit enrollment assignment' : 'Add enrollment'}</h3>
            <p>{bulkMode ? 'Create selected Course and Batch enrollments together. Simplified Courses must use their assigned Education Agent.' : editing ? 'Assignment changes are available while an Enrollment is pending or suspended.' : 'Create access as pending for review or active when already approved.'}</p>
          </div>
          <div className="enrollment-editor__heading-actions">
            {!editing ? <Button type="button" variant="secondary" size="sm" icon={Layers3} onClick={() => { setBulkMode((current) => !current); setFormError(''); }} disabled={saving}>{bulkMode ? 'Single enrollment' : 'Assign multiple courses'}</Button> : null}
            {editing ? <Button type="button" variant="ghost" size="sm" onClick={resetForm} disabled={saving}>Cancel edit</Button> : null}
            <Button type="submit" size="sm" icon={editing ? Pencil : Plus} disabled={saving}>
              {saving ? 'Saving…' : bulkMode ? 'Create enrollments' : editing ? 'Save enrollment' : 'Add enrollment'}
            </Button>
          </div>
        </div>
        {bulkMode ? <div className="enrollment-bulk">
          <Field label="Education Agent" htmlFor="bulk-enrollment-agent" hint="All selected simplified Courses must be assigned to this Agent.">
            <select className="enrollment-select" id="bulk-enrollment-agent" value={bulkAgentId} onChange={(event) => { setBulkAgentId(event.target.value); setBulkAssignments([]); }}>
              <option value="">Select Education Agent</option>
              {educationAgents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name}</option>)}
            </select>
          </Field>
          <Field label="Initial status" htmlFor="bulk-enrollment-status">
            <select className="enrollment-select" id="bulk-enrollment-status" value={bulkStatus} onChange={(event) => setBulkStatus(event.target.value as 'pending' | 'active')}><option value="pending">Pending</option><option value="active">Active</option></select>
          </Field>
          <div className="enrollment-bulk__courses">
            {activeCourses.map((course) => {
              const selected = bulkAssignments.find((assignment) => assignment.courseId === course.id);
              const incompatible = course.simplifiedWorkflow && Boolean(bulkAgentId) && course.assignedAgentId !== bulkAgentId;
              const courseBatches = batches.filter((batch) => batch.status === 'active' && batch.courseId === course.id);
              return <div className="enrollment-bulk__course" key={course.id}>
                <label><input type="checkbox" checked={Boolean(selected)} disabled={!bulkAgentId || incompatible} onChange={() => toggleBulkCourse(course)} /> <strong>{course.code} Â· {course.name}</strong>{course.simplifiedWorkflow ? ' (simplified)' : ''}</label>
                {incompatible ? <small>This Course is assigned to a different Education Agent.</small> : null}
                {selected ? <div className="enrollment-bulk__details">
                  <Field label="Batch" htmlFor={`bulk-batch-${course.id}`}><select id={`bulk-batch-${course.id}`} value={selected.batchId} onChange={(event) => { const batch = courseBatches.find((item) => item.id === event.target.value); updateBulkAssignment(course.id, { batchId: event.target.value, startsOn: batch?.startsOn ?? selected.startsOn, endsOn: batch?.endsOn ?? selected.endsOn }); }}><option value="">Select Batch</option>{courseBatches.map((batch) => <option key={batch.id} value={batch.id}>{batch.code} Â· {batch.name}</option>)}</select></Field>
                  <Field label="Access starts" htmlFor={`bulk-start-${course.id}`}><input id={`bulk-start-${course.id}`} type="date" value={selected.startsOn} onChange={(event) => updateBulkAssignment(course.id, { startsOn: event.target.value })} /></Field>
                  <Field label="Access ends" htmlFor={`bulk-end-${course.id}`}><input id={`bulk-end-${course.id}`} type="date" value={selected.endsOn} onChange={(event) => updateBulkAssignment(course.id, { endsOn: event.target.value })} /></Field>
                </div> : null}
              </div>;
            })}
          </div>
        </div> : <div className={`enrollment-editor__grid${selectedCourseIsSimplified ? ' enrollment-editor__grid--simplified' : ''}`}>
          <Field label="Course" htmlFor="enrollment-course">
            <select className="enrollment-select" id="enrollment-course" value={form.courseId} onChange={(event) => setCourse(event.target.value)}>
              <option value="">Select Course</option>
              {activeCourses.map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}
            </select>
          </Field>
          <Field label="Batch" htmlFor="enrollment-batch" hint={form.courseId ? 'Only active batches for the selected Course.' : 'Select a Course first.'}>
            <select className="enrollment-select" id="enrollment-batch" value={form.batchId} disabled={!form.courseId} onChange={(event) => setBatch(event.target.value)}>
              <option value="">Select Batch</option>
              {selectableBatches.map((batch) => <option value={batch.id} key={batch.id}>{batch.code} · {batch.name}</option>)}
            </select>
          </Field>
          {!selectedCourseIsSimplified ? <Field label="Education Agent" htmlFor="enrollment-agent" hint="Only Agents with Education purpose are eligible.">
            <select className="enrollment-select" id="enrollment-agent" value={form.agentId} onChange={(event) => setForm((current) => ({ ...current, agentId: event.target.value }))}>
              <option value="">Select Education Agent</option>
              {educationAgents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name} · {agent.status}{agent.whatsappNumber ? ` - WhatsApp ${agent.whatsappNumber}` : ''}</option>)}
            </select>
          </Field> : null}
          {!editing ? <Field label="Initial status" htmlFor="enrollment-status">
            <select className="enrollment-select" id="enrollment-status" value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value as 'pending' | 'active' }))}>
              <option value="pending">Pending</option>
              <option value="active">Active</option>
            </select>
          </Field> : null}
          <Field label="Access starts" htmlFor="enrollment-start" hint="Optional; Batch dates are suggested automatically.">
            <input id="enrollment-start" type="date" value={form.startsOn} onChange={(event) => setForm((current) => ({ ...current, startsOn: event.target.value }))} />
          </Field>
          <Field label="Access ends" htmlFor="enrollment-end" hint="Optional. Must be on/after the start date.">
            <input id="enrollment-end" type="date" value={form.endsOn} onChange={(event) => setForm((current) => ({ ...current, endsOn: event.target.value }))} />
          </Field>
        </div>}
        {!activeCourses.length || !educationAgents.length ? <div className="enrollment-prerequisite-note">
          <ShieldCheck />
          <p>{!activeCourses.length ? 'Create an active Course and Batch before enrolling Students. ' : ''}{!educationAgents.length ? 'Create an Agent with Education purpose before assigning enrollment access.' : ''}</p>
        </div> : null}
        {formError ? <p className="enrollment-error" role="alert">{formError}</p> : null}
      </form> : <div className="enrollment-readonly-note">
        <Ban /><div><strong>Student is archived</strong><p>Existing Enrollment history remains visible. Reactivate the Student before creating or changing access.</p></div>
      </div>}

      <section className="enrollment-list-section">
        <div className="enrollment-list-section__heading">
          <div><h3>Enrollment access</h3><p>{enrollments.length} total assignment{enrollments.length === 1 ? '' : 's'}</p></div>
          <label>
            <span className="sr-only">Filter enrollments by status</span>
            <select value={filter} onChange={(event) => setFilter(event.target.value as 'all' | EnrollmentStatus)} aria-label="Filter enrollments by status">
              <option value="all">All statuses</option>
              {Object.entries(statusLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select>
          </label>
        </div>

        {loading ? <div className="enrollment-loading">Loading enrollments…</div> : loadError ? <div className="enrollment-load-error" role="alert">
          <p>{loadError}</p><Button variant="secondary" size="sm" onClick={() => void load()}>Try again</Button>
        </div> : visibleEnrollments.length ? <div className="enrollment-list">
          {visibleEnrollments.map((enrollment) => {
            const course = courseById.get(enrollment.courseId);
            const batch = batchById.get(enrollment.batchId);
            const agent = agentById.get(enrollment.agentId);
            const busy = actingId === enrollment.id;
            return <article className={`enrollment-row is-${enrollment.status}`} key={enrollment.id}>
              <div className="enrollment-row__icon"><GraduationCap /></div>
              <div className="enrollment-row__main">
                <div className="enrollment-row__title">
                  <strong>{course?.name ?? 'Unknown Course'}</strong>
                  <Badge tone={statusTone(enrollment.status)}>{statusLabels[enrollment.status]}</Badge>
                </div>
                <div className="enrollment-row__meta">
                  <span><b>Course</b>{course ? `${course.code} · ${course.name}` : enrollment.courseId}</span>
                  <span><b>Batch</b>{batch ? `${batch.code} · ${batch.name}` : enrollment.batchId}</span>
                  <span><b>Agent</b>{agent?.name ?? enrollment.agentId}</span>
                  <span><b>Validity</b>{dateLabel(enrollment.startsOn)} → {dateLabel(enrollment.endsOn)}</span>
                </div>
              </div>
              <div className="enrollment-row__actions">
                {['pending', 'suspended'].includes(enrollment.status) && student.status === 'active' ? <Button variant="ghost" size="sm" icon={Pencil} disabled={busy} onClick={() => startEdit(enrollment)}>Edit</Button> : null}
                {student.status === 'active' && ['pending', 'suspended', 'expired'].includes(enrollment.status) ? <Button variant="secondary" size="sm" icon={CheckCircle2} disabled={busy} onClick={() => void updateStatus(enrollment, 'active', 'Enrollment activated')}>Activate</Button> : null}
                {student.status === 'active' && enrollment.status === 'active' ? <Button variant="secondary" size="sm" icon={PauseCircle} disabled={busy} onClick={() => void updateStatus(enrollment, 'suspended', 'Enrollment suspended')}>Suspend</Button> : null}
                {student.status === 'active' && ['pending', 'active', 'suspended'].includes(enrollment.status) ? <Button variant="ghost" size="sm" icon={Clock3} disabled={busy} onClick={() => void updateStatus(enrollment, 'expired', 'Enrollment expired')}>Expire</Button> : null}
                {student.status === 'active' && ['active', 'suspended', 'expired'].includes(enrollment.status) ? <Button variant="ghost" size="sm" icon={GraduationCap} disabled={busy} onClick={() => void updateStatus(enrollment, 'graduated', 'Student graduated from this enrollment')}>Graduate</Button> : null}
                {student.status === 'active' && enrollment.status === 'revoked' ? <Button variant="secondary" size="sm" icon={RefreshCw} disabled={busy} onClick={() => void updateStatus(enrollment, 'pending', 'Enrollment restored to pending')}>Restore</Button> : null}
                {student.status === 'active' && enrollment.status !== 'revoked' && enrollment.status !== 'graduated' ? <Button variant="danger" size="sm" icon={Ban} disabled={busy} onClick={() => void revoke(enrollment)}>Revoke</Button> : null}
              </div>
            </article>;
          })}
        </div> : <div className="enrollment-empty">
          <GraduationCap />
          <div><strong>{enrollments.length ? 'No enrollments match this filter' : 'No enrollment access yet'}</strong><p>{enrollments.length ? 'Choose another status filter.' : 'Assign an active Course, Batch, and Education Agent to this Student.'}</p></div>
        </div>}
      </section>
    </div> : null}
  </Modal>;
}
