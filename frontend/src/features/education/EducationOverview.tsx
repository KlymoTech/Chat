import { ArrowLeft, ArrowRight, BookOpen, Bot, CalendarDays, Check, ClipboardCheck, FileUp, GraduationCap, Upload, UserPlus, Users } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useAuth, useWorkspace } from '@/components/providers';
import { Button, EmptyState } from '@/components/ui';
import { DashboardTrend } from '@/components/academy-dashboard';
import { api } from '@/lib/api';
import { educationApi } from '@/lib/education-api';
import { educationStudentApi } from '@/lib/education-student-api';
import { educationEnrollmentApi } from '@/lib/education-enrollment-api';
import { educationAccessRequestApi } from '@/lib/education-access-request-api';
import { useApi, type AsyncState } from '@/lib/use-api';
import { relativeTime } from '@/lib/format';
import { canUseDashboardCapability } from '@/features/dashboard/dashboardPermissions';
import { enrollmentHasAccess, uniqueStudents } from './educationPresentation';
import './education-design.css';

function current<T>(state: AsyncState<T>): T | null { return !state.loading && !state.error ? state.data : null; }
function State({ state, title, children }: { state: Pick<AsyncState<unknown>, 'loading' | 'error' | 'reload'>; title: string; children: ReactNode }) {
  return state.loading ? <p className="ed-state" role="status">Loading {title.toLowerCase()}…</p>
    : state.error ? <div className="ed-state" role="alert"><strong>{title} are unavailable</strong><p>{state.error}</p><Button size="sm" variant="secondary" onClick={state.reload}>Try again</Button></div> : <>{children}</>;
}
export function EducationMetric({ icon, value, label, note, tone = 'green' }: { icon: ReactNode; value: number | null; label: string; note: string; tone?: string }) {
  return <article className="ed-metric"><div><span className="ed-icon">{icon}</span><small className={`ed-chip ed-chip--${tone}`}>{note}</small></div><strong>{value === null ? '—' : value.toLocaleString()}</strong><h3>{label}</h3></article>;
}

/** User export: Education/Education Overview.png. Every value is workspace API data. */
export function EducationOverview() {
  const { activeWorkspace } = useWorkspace();
  return <EducationOverviewContent key={activeWorkspace?.id ?? 'no-workspace'} />;
}
function EducationOverviewContent() {
  const { activeWorkspace } = useWorkspace();
  const { session } = useAuth();
  const scope = { role: session?.user.role, permissions: activeWorkspace?.permissions };
  const canView = canUseDashboardCapability(scope, 'education.view');
  const canManage = canUseDashboardCapability(scope, 'education.manage');
  const canAgents = canUseDashboardCapability(scope, 'agents.view');
  const canKnowledge = canUseDashboardCapability(scope, 'knowledge.view');
  const courses = useApi(() => canView ? educationApi.courses.list() : Promise.resolve([]), [canView]);
  const batches = useApi(() => canView ? educationApi.batches.list() : Promise.resolve([]), [canView]);
  const students = useApi(() => canView ? educationStudentApi.list() : Promise.resolve([]), [canView]);
  const enrollments = useApi(() => canView ? educationEnrollmentApi.list() : Promise.resolve([]), [canView]);
  const requests = useApi(() => canView ? educationAccessRequestApi.list() : Promise.resolve([]), [canView]);
  const agents = useApi(() => canView && canAgents ? api.agents.list() : Promise.resolve([]), [canView, canAgents]);
  const [filter, setFilter] = useState('all');
  const [selected, setSelected] = useState(0);
  const [period, setPeriod] = useState(7);
  const [metric, setMetric] = useState<'enrollments' | 'courses'>('enrollments');
  const [now] = useState(() => new Date());
  const records = current(courses) ?? [];
  const registrations = current(enrollments) ?? [];
  const cohorts = current(batches) ?? [];
  const pending = (current(requests) ?? []).filter((r) => r.status === 'pending');
  const educationAgents = (current(agents) ?? []).filter((a) => a.purpose === 'education');
  const featured = records[selected % Math.max(records.length, 1)];
  const featuredAgent = educationAgents.find((a) => a.id === featured?.assignedAgentId) ?? educationAgents.find((a) => registrations.some((e) => e.courseId === featured?.id && e.agentId === a.id));
  const activeRegistrations = registrations.filter((e) => enrollmentHasAccess(e, now));
  const shown = records.filter((course) => filter === 'all' || (filter === 'batches' ? cohorts.some((b) => b.courseId === course.id && b.status === 'active') : course.status === filter));
  const observations = metric === 'enrollments' ? registrations : records;
  const chart = Array.from({ length: period }, (_, index) => {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() - period + index + 1);
    const next = new Date(day); next.setDate(next.getDate() + 1);
    return { label: day.toLocaleDateString('en', { month: 'short', day: 'numeric' }), value: observations.filter((item) => new Date(item.createdAt) >= day && new Date(item.createdAt) < next).length };
  });
  const enrollmentSegments = [
    { label: 'Active access', count: activeRegistrations.length, tone: 'green' },
    { label: 'Pending', count: registrations.filter((e) => e.status === 'pending').length, tone: 'amber' },
    { label: 'Expired', count: registrations.filter((e) => e.status === 'expired' || (e.status === 'active' && e.endsOn && e.endsOn < now.toISOString().slice(0, 10))).length, tone: 'red' },
    { label: 'Other / scheduled', count: 0, tone: 'gray' },
  ];
  enrollmentSegments[3]!.count = registrations.length - enrollmentSegments.slice(0, 3).reduce((sum, s) => sum + s.count, 0);
  if (!canView) return <div className="ed-state"><h2>Education access unavailable</h2><p>Your workspace role does not include Education access.</p></div>;
  return <div className="ed-overview">
    <section className="ed-hero" aria-labelledby="ed-title"><div className="ed-eyebrow"><time dateTime={now.toISOString().slice(0, 10)}>{now.toLocaleDateString('en', { month: 'long', day: 'numeric', year: 'numeric' })}</time> · {activeWorkspace?.name ?? 'Education workspace'}</div><h2 id="ed-title">Education Hub</h2><p>Manage students, courses, batches, enrollments, access requests, and autonomous AI tutoring from a unified operational plane.</p>
      <div className="ed-hero__actions">{canManage ? <><Link className="button ed-button--light" to="/education/students?create=1"><UserPlus />Add Student</Link><Link className="button" to="/education/courses?create=1"><BookOpen />Create Course</Link><Link className="button" to="/education/batches?create=1"><Users />Create Batch</Link><Link className="button" to="/education/enrollments?create=1"><ClipboardCheck />Create Enrollment</Link><Link className="button" to="/education/students/import"><FileUp />Import Students</Link></> : <Link className="button ed-button--light" to="/education/courses"><BookOpen />Browse Courses</Link>}</div>
    </section>
    <section className="ed-metrics" aria-label="Education summary">
      <EducationMetric icon={<Users />} label="Total Registered Students" value={current(students)?.length ?? null} note="Workspace records" />
      <EducationMetric icon={<UserPlus />} label="Students with Active Access" value={current(enrollments) ? uniqueStudents(activeRegistrations) : null} note="Valid today" />
      <EducationMetric icon={<BookOpen />} label="Active Courses" value={current(courses) ? records.filter((c) => c.status === 'active').length : null} note="Course catalog" tone="blue" />
      <EducationMetric icon={<ClipboardCheck />} label="Valid Enrollments" value={current(enrollments) ? activeRegistrations.length : null} note="Date-checked access" tone="amber" />
    </section>
    {students.error ? <State state={students} title="Students">{null}</State> : null}
    <div className="ed-columns"><div className="ed-primary">
      {featured ? <div className="ed-featured"><span className="ed-icon"><GraduationCap /></span><div><strong>{featuredAgent?.name ?? featured.name}</strong><small>{featuredAgent ? 'Course assistant' : featured.code}</small></div><span className="ed-featured__count"><strong>{current(enrollments) ? uniqueStudents(registrations.filter((e) => e.courseId === featured.id)) : '—'}</strong><small>students</small></span><Link aria-label={`Continue with ${featured.name}`} className="button button--primary" to={featuredAgent ? `/agents/${featuredAgent.id}/instructions` : `/education/courses?selected=${featured.id}`}>{featuredAgent ? 'Open agent' : 'View Course'}</Link><div className="ed-carousel"><button aria-label="Previous course" disabled={records.length < 2} onClick={() => setSelected((v) => (v + records.length - 1) % records.length)}><ArrowLeft /></button><button aria-label="Next course" disabled={records.length < 2} onClick={() => setSelected((v) => v + 1)}><ArrowRight /></button></div></div> : null}
      <section><div className="ed-section-heading"><h3>Your Courses</h3><Link to="/education/courses">View all courses <ArrowRight /></Link></div><div className="ed-tabs" role="group" aria-label="Filter academy courses">{[['all', 'All Courses'], ['active', 'Active'], ['batches', 'Batches'], ['archived', 'Archived']].map(([id, label]) => <button key={id} aria-pressed={filter === id} onClick={() => setFilter(id!)}>{label}</button>)}</div>
        <State state={courses} title="Courses">{filter === 'batches' && batches.error ? <State state={batches} title="Batches">{null}</State> : null}{shown.length ? <div className="ed-course-list">{shown.slice(0, 6).map((course) => <article key={course.id} className="ed-course-row"><span className="ed-outline-icon"><BookOpen /></span><div className="ed-record-name"><h4>{course.name}</h4><p>{course.description || course.code}</p></div><span className="ed-inline-count"><Users />{current(enrollments) ? uniqueStudents(registrations.filter((e) => e.courseId === course.id)) : '—'} students</span><span className="ed-inline-count">{current(batches) ? cohorts.filter((b) => b.courseId === course.id && b.status === 'active').length : '—'} active batches</span><Link aria-label={`View course ${course.name}`} className="button button--primary" to={`/education/courses?selected=${course.id}`}>View Course</Link></article>)}</div> : <EmptyState icon={BookOpen} title={records.length ? 'No courses match this filter' : 'Create your first course'} description="Add a course to organize students, batches and trusted learning material." action={canManage ? <Link className="button button--primary" to="/education/courses?create=1">Create Course</Link> : undefined} />}</State>
      </section>
      <section className="ed-panel ed-activity"><div className="ed-section-heading"><div><h3>Student Learning Activity</h3><p>New records created in this workspace. Not a measure of attendance.</p></div><select aria-label="Academy chart period" value={period} onChange={(e) => setPeriod(Number(e.target.value))}><option value="7">Weekly</option><option value="30">Monthly</option></select></div><div className="ed-tabs" role="group" aria-label="Academy chart metric"><button aria-pressed={metric === 'enrollments'} onClick={() => setMetric('enrollments')}>Enrollments</button><button aria-pressed={metric === 'courses'} onClick={() => setMetric('courses')}>Courses</button></div><State state={metric === 'courses' ? courses : enrollments} title="Statistics"><DashboardTrend data={chart} label={`${metric === 'enrollments' ? 'Enrollments' : 'Courses'} created in the last ${period} days`} /></State><div className="ed-panel-foot"><span>{(metric === 'courses' ? current(courses) : current(enrollments)) ? `${chart.reduce((sum, point) => sum + point.value, 0)} new ${metric}` : 'Statistics unavailable'}</span><Link to="/education/activity">View conversation activity <ArrowRight /></Link></div></section>
      <section><div className="ed-section-heading"><div><h3>Access Requests</h3><p>{current(requests) ? `${pending.length} pending · ${requests.data?.filter((r) => r.status === 'approved').length ?? 0} approved` : 'Identity and enrollment access review'}</p></div><Link to="/education/access-requests">View <ArrowRight /></Link></div><State state={requests} title="Access requests">{pending.length ? <div className="ed-request-list">{pending.slice(0, 3).map((r) => <article className="ed-request" key={r.id}><span className="ed-icon">{r.studentNumber.slice(0, 1)}</span><div className="ed-record-name"><strong>{r.studentNumber}</strong><p>{r.message || r.email || r.identityType}</p></div><div><time dateTime={r.createdAt}>{relativeTime(r.createdAt)}</time><Link className="button button--primary" to="/education/access-requests">{canManage ? 'Review' : 'View'}</Link></div></article>)}</div> : <div className="ed-empty"><Check />No pending access requests.</div>}</State></section>
    </div><aside className="ed-secondary" aria-label="Education operations">
      <section className="ed-panel"><div className="ed-section-heading"><h3>Enrollments</h3><Link to="/education/enrollments">View All <ArrowRight /></Link></div><State state={enrollments} title="Enrollments"><div className="ed-segment-bar" aria-hidden="true">{enrollmentSegments.map((s) => <i key={s.label} className={`ed-segment--${s.tone}`} style={{ flex: s.count, display: s.count ? undefined : 'none' }} />)}</div><dl className="ed-enrollment-counts">{enrollmentSegments.map((s) => <div key={s.label}><dt><i className={`ed-segment--${s.tone}`} />{s.label}</dt><dd>{s.count.toLocaleString()}</dd></div>)}</dl><Link className="button button--primary ed-wide" to="/education/enrollments">Manage Enrollments</Link></State></section>
      {canAgents ? <section className="ed-panel"><div className="ed-section-heading"><h3><Bot /> AI Agent Status</h3><Link to="/agents">Open Agents <ArrowRight /></Link></div><State state={agents} title="Agents"><div className="ed-agent-summary"><div><small>ACTIVE AGENTS</small><strong>{educationAgents.filter((a) => a.status === 'active').length}</strong></div><div><small>ASSIGNED STUDENTS</small><strong>{current(enrollments) ? uniqueStudents(registrations.filter((e) => educationAgents.some((a) => a.id === e.agentId))) : '—'}</strong></div></div>{educationAgents.length ? educationAgents.slice(0, 3).map((a) => <Link className="ed-agent-row" key={a.id} to={`/agents/${a.id}/instructions`}><i className={a.status === 'active' ? 'ed-segment--green' : 'ed-segment--gray'} /><div><strong>{a.name}</strong><small>{a.appearance?.deploymentChannel ?? 'website'}</small></div><span>{a.status}</span></Link>) : <p className="ed-muted">No education agents in this workspace.</p>}</State></section> : null}
      <section className="ed-panel ed-import-panel"><div className="ed-section-heading"><h3>Student Imports</h3><FileUp /></div><p>Preview, validate, and import student records using the existing enrollment workflow.</p><p className="ed-muted">Import history is not supplied by the current API.</p>{canManage ? <Link className="button button--primary ed-wide" to="/education/students/import"><Upload />Import Students</Link> : <p>Education management access is required to import.</p>}</section>
      {canKnowledge ? <section className="ed-knowledge"><small className="ed-chip">Knowledge Base</small><h3>Manage Education Sources</h3><p>Upload syllabi, exam questions, and lecture notes. Review source extraction and course access before publication.</p><BookOpen className="ed-knowledge__icon" aria-hidden="true" /><Link className="button ed-button--light" to="/education/knowledge"><FileUp />Upload Resources</Link></section> : null}
      <Link className="ed-batch-link" to="/education/batches"><CalendarDays /> {current(batches) ? `${cohorts.filter((b) => b.status === 'active').length} active batches` : 'Manage batches'} <ArrowRight /></Link>
    </aside></div>
  </div>;
}
