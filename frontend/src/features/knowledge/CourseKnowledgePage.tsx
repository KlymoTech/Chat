import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth, useWorkspace } from '@/components/providers';
import { api } from '@/lib/api';
import { botWorkflowApi, type BotWorkflow } from '@/lib/bot-workflow-api';
import { knowledgeBlob, knowledgePath, knowledgeRequest, saveKnowledgeBlob, stageCourseFile, type AcademicReview, type EnrollmentAccessSyncApplyResult, type EnrollmentAccessSyncPreview, type KnowledgeCatalog, type KnowledgeRecord, type KnowledgeStatus, type StudentPreview, type TutorContext, type TutorProgress, type VersionDetail, type WhatsappTurn } from './api';
import './CourseKnowledgePage.css';

const emptyCatalog: KnowledgeCatalog = { courses: [], batches: [], curricula: [], papers: [], batchCurricula: [] };
const emptyStatus: KnowledgeStatus = { sources: [], versions: [], assignments: [], releases: [], heads: [], artifacts: [], faqs: [], access: [], enrollments: [], academicReviews: [], jobs: [], legacyScopes: [], notice: '' };
function name(row?: KnowledgeRecord) { return row?.name || row?.title || row?.code || row?.id || ''; }
function toggle(values: string[], value: string) { return values.includes(value) ? values.filter(v => v !== value) : [...values, value]; }

export function CourseKnowledgePage() {
  const { activeWorkspace } = useWorkspace();
  return <KnowledgeWorkspace key={activeWorkspace?.id ?? 'none'} />;
}

function KnowledgeWorkspace() {
  const { activeWorkspace } = useWorkspace();
  const { session } = useAuth();
  const [params] = useSearchParams();
  const [catalog, setCatalog] = useState(emptyCatalog);
  const [status, setStatus] = useState(emptyStatus);
  const [progress, setProgress] = useState<TutorProgress[]>([]);
  const [contexts, setContexts] = useState<TutorContext[]>([]);
  const [reviews, setReviews] = useState<AcademicReview[]>([]);
  const [workflow, setWorkflow] = useState<BotWorkflow | null>(null);
  const [turns, setTurns] = useState<WhatsappTurn[]>([]);
  const [auditPath, setAuditPath] = useState('');
  const [auditDelivery, setAuditDelivery] = useState('');
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [agents, setAgents] = useState<KnowledgeRecord[]>([]);
  const [agent, setAgent] = useState(params.get('agentId') ?? '');
  const [course, setCourse] = useState(params.get('courseId') ?? '');
  const [paper, setPaper] = useState('');
  const [batch, setBatch] = useState('');
  const [materialType, setMaterialType] = useState('notes');
  const [language, setLanguage] = useState('English');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const staged = useRef<{ file: File; key: string } | null>(null);
  const uploadRequest = useRef({ key: crypto.randomUUID(), fingerprint: '' });
  const mappingRequest = useRef({ key: crypto.randomUUID(), fingerprint: '' });
  const [detail, setDetail] = useState<VersionDetail | null>(null);
  const [blocks, setBlocks] = useState<string[]>([]);
  const [editing, setEditing] = useState<KnowledgeRecord | null>(null);
  const [selectedAssignments, setSelectedAssignments] = useState<string[]>([]);
  const [selectedArtifacts, setSelectedArtifacts] = useState<string[]>([]);
  const [selectedFaqs, setSelectedFaqs] = useState<string[]>([]);
  const [faqQuestion, setFaqQuestion] = useState('');
  const [faqAnswer, setFaqAnswer] = useState('');
  const [faqVariants, setFaqVariants] = useState('');
  const [faqReference, setFaqReference] = useState('');
  const [faqReviewId, setFaqReviewId] = useState('');
  const [editingFaq, setEditingFaq] = useState<KnowledgeRecord | null>(null);
  const [testConversation, setTestConversation] = useState('');
  const [testQuestion, setTestQuestion] = useState('');
  const [testAnswer, setTestAnswer] = useState('');
  const [reason, setReason] = useState('');
  const [mismatch, setMismatch] = useState(false);
  const [enrollment, setEnrollment] = useState('');
  const [syncPreview, setSyncPreview] = useState<EnrollmentAccessSyncPreview | null>(null);
  const [syncSelected, setSyncSelected] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [preview, setPreview] = useState<StudentPreview | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [originalImage, setOriginalImage] = useState('');
  const [paperCode, setPaperCode] = useState('');
  const [paperName, setPaperName] = useState('');
  const [artifactType, setArtifactType] = useState('summary');
  const [artifactReview, setArtifactReview] = useState<KnowledgeRecord | null>(null);
  const [answerKeyVerified, setAnswerKeyVerified] = useState(false);
  const permissions = activeWorkspace?.permissions ?? [];
  const owner = session?.user.role === 'owner' || session?.user.role === 'admin';
  // Course Knowledge endpoints are governed by knowledge.manage. Requiring a
  // second, unrelated Education permission disabled valid workspace admins in
  // the UI even though the API allowed the same action.
  const canManage = owner || permissions.includes('*') || permissions.includes('knowledge.manage');
  // Curriculum is not chosen on this page: each course has one syllabus, created on first use.
  const curriculum = catalog.curricula.find(c => c.courseId === course && c.active !== false)?.id ?? '';
  const papers = catalog.papers.filter(p => p.curriculumId === curriculum);
  const batches = catalog.batches.filter(b => b.courseId === course);
  const scopeAssignments = status.assignments.filter(a => a.courseId === course && a.curriculumId === curriculum);
  const source = status.versions.find(v => v.id === detail?.id);
  const courseName = name(catalog.courses.find(c => c.id === course));
  const audience = `${courseName || 'Selected course'} / ${paper === 'overview' ? 'course overview only' : name(papers.find(p => p.id === paper)) || 'select paper'} / ${batch ? name(batches.find(b => b.id === batch)) : 'all matching batches'}`;

  async function load() {
    const next = await knowledgeRequest<KnowledgeCatalog>('/education/knowledge/catalog');
    setCatalog(next);
    if (agent) {
      const [nextStatus, nextProgress, nextContexts, nextReviews] = await Promise.all([
        knowledgeRequest<KnowledgeStatus>(knowledgePath(agent, '/status')),
        knowledgeRequest<TutorProgress[]>(`/education/progress?agent_id=${encodeURIComponent(agent)}`),
        knowledgeRequest<TutorContext[]>(`/education/tutor-contexts?agent_id=${encodeURIComponent(agent)}`),
        knowledgeRequest<AcademicReview[]>(`/education/academic-reviews?agent_id=${encodeURIComponent(agent)}`),
      ]);
      setStatus(nextStatus); setProgress(nextProgress); setContexts(nextContexts); setReviews(nextReviews);
    }
  }
  async function action<T>(work: () => Promise<T>, message: string): Promise<T | undefined> {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { const result = await work(); await load(); setNotice(message); return result; }
    catch (e) { setError(e instanceof Error ? e.message : 'The request failed'); }
    finally {
      setBusy(false);
      // The result banner sits at the top of a long page: bring it into view so the outcome is seen.
      window.requestAnimationFrame(() => feedback.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' }));
    }
  }
  useEffect(() => {
    let live = true;
    void Promise.all([knowledgeRequest<KnowledgeCatalog>('/education/knowledge/catalog'), api.agents.list()]).then(([next, list]) => {
      if (live) { setCatalog(next); setAgents(list.filter(a => a.purpose === 'education').map(a => ({ id: a.id, name: a.name }))); }
    }).catch(e => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (!agent) return;
    let live = true;
    const reload = () => void Promise.all([
      knowledgeRequest<KnowledgeStatus>(knowledgePath(agent, '/status')),
      knowledgeRequest<TutorProgress[]>(`/education/progress?agent_id=${encodeURIComponent(agent)}`),
      knowledgeRequest<TutorContext[]>(`/education/tutor-contexts?agent_id=${encodeURIComponent(agent)}`),
      knowledgeRequest<AcademicReview[]>(`/education/academic-reviews?agent_id=${encodeURIComponent(agent)}`),
    ]).then(([nextStatus, nextProgress, nextContexts, nextReviews]) => { if (live) { setStatus(nextStatus); setProgress(nextProgress); setContexts(nextContexts); setReviews(nextReviews); } }).catch(e => { if (live) setError(String(e)); });
    reload(); const timer = setInterval(reload, 10000);
    return () => { live = false; clearInterval(timer); };
  }, [agent]);
  useEffect(() => {
    if (!agent) { setTurns([]); setWorkflow(null); return; }
    let live = true;
    const query = auditQuery();
    const refresh = () => void Promise.all([
      knowledgeRequest<WhatsappTurn[]>(knowledgePath(agent, `/whatsapp-turns?limit=25${query ? `&${query}` : ''}`)),
      botWorkflowApi.list().catch(() => [] as BotWorkflow[]),
    ]).then(([nextTurns, workflows]) => {
      if (live) { setTurns(nextTurns); setWorkflow(workflows.find(item => item.agentId === agent) ?? null); }
    }).catch(e => { if (live) setError(String(e)); });
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => { live = false; clearInterval(timer); };
  }, [agent, course, auditPath, auditDelivery]);
  useEffect(() => () => { if (originalImage) URL.revokeObjectURL(originalImage); }, [originalImage]);
  const preparingCourse = useRef('');
  const feedback = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!course || curriculum || !canManage || preparingCourse.current === course) return;
    preparingCourse.current = course;
    knowledgeRequest<KnowledgeRecord>(`/education/knowledge/courses/${course}/curriculum`, 'POST')
      .then(row => setCatalog(prev => ({ ...prev, curricula: [...prev.curricula.filter(c => c.id !== row.id), row] })))
      .catch(e => setError(String(e)))
      .finally(() => { preparingCourse.current = ''; });
  }, [course, curriculum, canManage]);

  function destination() { return { courseId: course, curriculumId: curriculum, paperId: !['overview', 'mixed', ''].includes(paper) ? paper : null, overview: paper === 'overview', mixedPapers: paper === 'mixed', batchId: batch || null, materialType, language }; }
  async function openVersion(id: string) {
    const value = await knowledgeRequest<VersionDetail>(knowledgePath(agent, `/versions/${id}`));
    setDetail(value); setBlocks([]); setEditing(null); setOriginalImage('');
  }
  async function reviewExistingMapping(scope: KnowledgeRecord) {
    const version = status.versions.find(v => v.sourceId === scope.sourceId && !v.withdrawn);
    if (!version) throw new Error('Prepare an immutable snapshot of this trained source first.');
    const loaded = await knowledgeRequest<VersionDetail>(knowledgePath(agent, `/versions/${version.id}`));
    setDetail(loaded); setEditing(null); setOriginalImage('');
    const ids = new Set(loaded.blocks.map(block => block.id));
    setBlocks((scope.selectedBlockIds ?? []).filter(id => ids.has(id)));
    setCourse(scope.courseId ?? ''); setPaper(scope.paperId ?? 'overview'); setBatch(scope.batchId ?? '');
    setMaterialType(scope.materialType ?? 'notes');
    document.getElementById('course-block-review')?.scrollIntoView({ behavior: 'smooth' });
  }
  function selectCourse(value: string) { setCourse(value); setPaper(''); setBatch(''); setSyncPreview(null); setSyncSelected([]); setSelectedAssignments([]); setSelectedArtifacts([]); setSelectedFaqs([]); setPreview(null); setArtifactReview(null); setTestConversation(''); }
  function selectAgent(value: string) {
    setAgent(value); setStatus(emptyStatus); setProgress([]); setContexts([]); setReviews([]); setReviewNotes({});
    setDetail(null); setBlocks([]); setEditing(null); setPreview(null); setEnrollment(''); setSyncPreview(null); setSyncSelected([]); setSelectedAssignments([]); setSelectedArtifacts([]); setSelectedFaqs([]); setTestConversation('');
  }
  async function upload(event: FormEvent) {
    event.preventDefault();
    await action(async () => {
      if (!agent || !course || !curriculum || !paper) throw new Error(!curriculum && course ? 'This course is still being set up for knowledge; try again in a moment.' : 'Choose an Education Agent, course, and paper mode before uploading.');
      let objectKey: string | undefined;
      if (file) {
        if (staged.current?.file !== file) staged.current = { file, key: await stageCourseFile(file) };
        objectKey = staged.current.key;
      }
      const body = { title: title || file?.name, destination: destination(), kind: file ? 'file' : 'text', ...(file ? { objectKey } : { content: text }) };
      const identity = JSON.stringify(body);
      if (uploadRequest.current.fingerprint !== identity) uploadRequest.current = { fingerprint: identity, key: crypto.randomUUID() };
      await knowledgeRequest(knowledgePath(agent, '/uploads'), 'POST', { ...body, idempotencyKey: uploadRequest.current.key });
      setFile(null); setText(''); staged.current = null;
    }, 'Upload recorded with its intended course. Processing does not publish it.');
  }
  async function saveMapping() {
    if (!detail) return;
    await action(async () => {
      const body = { ...destination(), mixedPapers: false, sourceVersionId: detail.id, blockIds: blocks, ...(editing ? { expectedRevision: editing.revision } : {}) };
      const identity = JSON.stringify({ agent, body });
      if (mappingRequest.current.fingerprint !== identity) mappingRequest.current = { fingerprint: identity, key: crypto.randomUUID() };
      await knowledgeRequest(knowledgePath(agent, editing ? `/assignments/${editing.id}` : '/assignments'), editing ? 'PUT' : 'POST', { ...body, idempotencyKey: editing?.idempotencyKey || mappingRequest.current.key });
      setEditing(null);
    }, 'Mapping saved for review. Previous approval cannot authorize an edited mapping.');
  }
  async function download(path: string, filename: string) { saveKnowledgeBlob(await knowledgeBlob(path), filename); }
  function auditQuery() {
    const query = new URLSearchParams();
    if (course) query.set('course_id', course);
    if (auditPath) query.set('answer_path', auditPath);
    if (auditDelivery) query.set('delivery_status', auditDelivery);
    return query.toString();
  }
  async function publish(release: KnowledgeRecord) {
    const head = status.heads.find(h => h.courseId === release.courseId && h.curriculumId === release.curriculumId);
    if (!window.confirm(`Publish this exact release for ${courseName}? Each included assignment retains its own paper and batch restrictions.`)) return;
    await action(() => knowledgeRequest(knowledgePath(agent, `/releases/${release.id}/publish`), 'POST', { expectedEpoch: head?.epoch ?? 0 }), 'Knowledge release activated.');
  }
  function selectEnrollment(id: string) { setEnrollment(id); setPreview(null); }
  async function previewEnrollmentAccessSync() {
    await action(async () => {
      if (!agent || !course) throw new Error('Choose an Education Agent and Course first.');
      const value = await knowledgeRequest<EnrollmentAccessSyncPreview>(knowledgePath(agent, '/enrollment-access/sync-preview'), 'POST', { courseId: course, batchId: batch || null });
      setSyncPreview(value);
      setSyncSelected(value.items.filter(item => item.disposition === 'will_create' || item.disposition === 'will_repair').map(item => item.enrollmentId));
    }, 'Review the proposed paper snapshots, then apply the selected enrollment grants.');
  }
  async function applyEnrollmentAccessSync() {
    if (!agent || !course || !syncSelected.length) return;
    const result = await action(async () => {
      const value = await knowledgeRequest<EnrollmentAccessSyncApplyResult>(knowledgePath(agent, '/enrollment-access/sync-apply'), 'POST', { courseId: course, batchId: batch || null, enrollmentIds: syncSelected });
      setSyncPreview(null); setSyncSelected([]);
      return value;
    }, 'Enrollment access sync completed without document reprocessing.');
    if (result) setNotice(`Enrollment access synced: ${result.created} created, ${result.repaired} repaired, ${result.skipped} skipped. Future papers require another preview and apply.`);
  }
  async function revokeEnrollmentAccessSync() {
    if (!agent || !course || !syncSelected.length) return;
    if (!window.confirm(`Revoke Course Knowledge access for ${syncSelected.length} selected enrollment${syncSelected.length === 1 ? '' : 's'}? This is an explicit revoke.`)) return;
    const result = await action(() => knowledgeRequest<{ revoked: number; skipped: number }>(knowledgePath(agent, '/enrollment-access/sync-revoke'), 'POST', { courseId: course, batchId: batch || null, enrollmentIds: syncSelected }), 'Selected Course Knowledge access was revoked.');
    if (result) { setSyncPreview(null); setSyncSelected([]); setNotice(`Course Knowledge access revoked for ${result.revoked}; ${result.skipped} skipped.`); }
  }
  function enrollmentLabel(id: string | null) {
    if (!id) return 'No course selected';
    const row = status.enrollments.find(item => item.id === id);
    const courseLabel = name(catalog.courses.find(item => item.id === row?.courseId));
    const batchLabel = name(catalog.batches.find(item => item.id === row?.batchId));
    return row ? `${courseLabel || 'Course'}${batchLabel ? ` · ${batchLabel}` : ''}` : `Enrollment ${id.slice(0, 8)}`;
  }
  function paperLabel(id: string | null) { return id ? name(catalog.papers.find(item => item.id === id)) || `Paper ${id.slice(0, 8)}` : 'Course overview'; }
  function reviewNote(id: string) { return reviewNotes[id]?.trim() ?? ''; }
  async function resolveAcademicReview(review: AcademicReview, outcome: 'confirmed' | 'corrected') {
    const resolution = reviewNote(review.id);
    if (!resolution) return;
    await action(() => knowledgeRequest(`/education/academic-reviews/${review.id}/resolve`, 'POST', {
      outcome, resolution, requestCorrectionDelivery: outcome === 'corrected',
    }), outcome === 'corrected' ? 'Correction recorded for policy-checked delivery.' : 'Reviewed answer confirmed.');
    setReviewNotes(current => { const next = { ...current }; delete next[review.id]; return next; });
  }
  function draftFromReview(review: AcademicReview) {
    setCourse(review.courseId ?? ''); setPaper(review.paperId ?? 'overview'); setBatch(review.batchId ?? '');
    setFaqQuestion(review.question); setFaqAnswer(review.resolution || review.answer);
    setFaqReviewId(review.id); setFaqReference(''); setFaqVariants(''); setEditingFaq(null);
    document.getElementById('course-faq-library')?.scrollIntoView({ behavior: 'smooth' });
  }
  async function saveFaq() {
    await action(async () => {
      if (!agent || !course || !curriculum || !paper || paper === 'mixed') throw new Error('Choose an agent, course, and paper or overview.');
      const references = faqReviewId ? [{ kind: 'teacher_review', review_id: faqReviewId }]
        : faqReference.trim() ? [{ kind: 'external', url: faqReference.trim() }]
        : selectedAssignments[0] ? [{ kind: 'course_assignment', assignment_id: selectedAssignments[0] }]
        : editingFaq?.references ?? [];
      if (!references.length) throw new Error('Select a source assignment, use a resolved teacher review, or enter a checked external source URL.');
      const body = { courseId: course, curriculumId: curriculum, paperId: paper === 'overview' ? null : paper,
        batchId: batch || null, question: faqQuestion.trim(), answer: faqAnswer.trim(),
        variants: faqVariants.split('\n').map(value => value.trim()).filter(Boolean), language,
        references, reviewId: faqReviewId || null, ...(editingFaq ? { expectedRevision: editingFaq.revision } : {}) };
      await knowledgeRequest(knowledgePath(agent, editingFaq ? `/faqs/${editingFaq.id}` : '/faqs'), editingFaq ? 'PUT' : 'POST', body);
      setEditingFaq(null); setFaqQuestion(''); setFaqAnswer(''); setFaqVariants(''); setFaqReference(''); setFaqReviewId('');
    }, 'Draft Q&A saved. A teacher must approve it and include it in a published release.');
  }
  async function startTestChat() {
    await action(async () => {
      const result = await knowledgeRequest<{ conversationId: string }>(knowledgePath(agent, '/test-conversations'), 'POST', { enrollmentId: enrollment, includeUnpublished: false });
      setTestConversation(result.conversationId); setTestAnswer('');
    }, 'Published student test started. Ask a question below.');
  }
  async function askTestChat() {
    if (!testConversation || !testQuestion.trim()) return;
    setBusy(true); setError(''); setTestAnswer('');
    try {
      let result = '';
      for await (const event of api.streamChat({ agentId: agent, conversationId: testConversation, message: testQuestion.trim() })) {
        if (event.type === 'token') { result += event.content ?? ''; setTestAnswer(result); }
        if (event.type === 'error') throw new Error(event.message ?? 'Tutor test failed');
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Tutor test failed'); }
    finally { setBusy(false); }
  }
  const activeRelease = status.heads.find(h => h.courseId === course && h.curriculumId === curriculum && h.releaseId);
  const currentManifest = status.releases.find(r => r.id === activeRelease?.releaseId)?.manifest;
  const publishedAssignments = (currentManifest?.assignments ?? []).map(item => scopeAssignments.find(a => a.id === item.assignment_id)).filter((item): item is KnowledgeRecord => Boolean(item));
  const coveredPaper = !paper || paper === 'mixed' ? Boolean(activeRelease) : publishedAssignments.some(a =>
    (a.overview || a.paperId === paper) && (!a.batchId || !batch || a.batchId === batch));
  const activeAccess = status.access.filter(a => status.enrollments.some(e => e.id === a.enrollmentId && e.courseId === course && e.status === 'active') && a.active
    && (!paper || paper === 'overview' || paper === 'mixed' || (a.paperIds ?? []).includes(paper)));
  const readyAssignments = scopeAssignments.filter(a => a.status === 'approved' && a.indexStatus === 'ready');
  const setupSteps = [
    { label: 'Course and syllabus', done: Boolean(course && curriculum), detail: curriculum ? 'Ready' : 'Select a course; its syllabus is prepared here.' },
    { label: 'Papers and batch', done: papers.length > 0 && batches.length > 0, detail: papers.length && batches.length ? 'Ready' : 'Create a paper and active batch for this course.' },
    { label: 'Lexical course index', done: readyAssignments.length > 0, detail: readyAssignments.length ? `${readyAssignments.length} approved lexical assignment(s)` : 'Reuse a trained source snapshot, review blocks, approve and prepare the lexical index.' },
    { label: 'Published course release', done: coveredPaper, detail: coveredPaper ? 'Active release covers the selected paper and batch' : activeRelease ? 'The active release does not cover this paper or batch.' : 'Build and publish an exact release.' },
    { label: 'Student paper access', done: activeAccess.length > 0, detail: activeAccess.length ? `${activeAccess.length} active enrollment grant(s)` : 'Grant curriculum and paper access to an active enrollment.' },
  ];
  const previewBody = { enrollmentId: enrollment, query, selectedPaperId: ['overview', 'mixed', ''].includes(paper) ? null : paper };

  return <div className="ck-page">
    <header><h2>Course knowledge</h2><p>Vectorless lexical retrieval: every uploaded source is explicitly bound to one course before publication, and student answers search only the active authorized course.</p></header>
    <div ref={feedback}>{error && <p role="alert" className="ck-error">{error}</p>}{notice && <p role="status" className="ck-notice">{notice}</p>}</div>
    <nav className="ck-section-nav" aria-label="Course setup sections"><a href="#course-setup">Readiness</a><a href="#course-faq-library">Approved Q&A</a><a href="#course-release">Publish</a><a href="#course-test">Student test</a><a href="#course-workflow">WhatsApp messages</a><a href="#course-review">Review gaps</a><a href="#course-audit">Q&A export</a></nav>
    <section className="ck-panel ck-grid" aria-label="Knowledge destination">
      <label>Education Agent<select value={agent} onChange={e => selectAgent(e.target.value)}><option value="">Select agent</option>{agents.map(a => <option key={a.id} value={a.id}>{name(a)}</option>)}</select></label>
      <label>Course<select value={course} onChange={e => selectCourse(e.target.value)}><option value="">Select course</option>{catalog.courses.map(c => <option key={c.id} value={c.id}>{name(c)}</option>)}</select></label>
      <label>Paper<select value={paper} onChange={e => { setPaper(e.target.value); setPreview(null); }}><option value="">Select paper mode</option><option value="overview">Course overview only</option><option value="mixed">Mixed papers (upload only)</option>{papers.map(p => <option key={p.id} value={p.id}>{name(p)}</option>)}</select></label>
      <label>Audience<select value={batch} onChange={e => { setBatch(e.target.value); setSyncPreview(null); setSyncSelected([]); }}><option value="">All matching batches</option>{batches.map(b => <option key={b.id} value={b.id}>{name(b)}</option>)}</select></label>
      <label>Material type<select value={materialType} onChange={e => setMaterialType(e.target.value)}>{['notes', 'textbook', 'practice', 'worked_examples'].map(v => <option key={v}>{v}</option>)}</select></label>
      <label>Language<input value={language} onChange={e => setLanguage(e.target.value)} maxLength={80} /></label>
      <p className="ck-wide">Audience: <strong>{audience}</strong>. Only students with a valid matching enrollment can receive it.</p>
    </section>
    <section className="ck-panel" id="course-setup"><h3>Student readiness for {courseName || 'the selected course'}</h3><p>Training complete is only the first step. WhatsApp uses the active Course Knowledge release, not the older source-mapping badge.</p><div className="ck-setup-list">{setupSteps.map(step => <div key={step.label} className="ck-setup-step"><span aria-hidden="true">{step.done ? '✓' : '○'}</span><div><strong>{step.label}</strong><small>{step.detail}</small></div></div>)}</div><p>Already-trained sources can be prepared as immutable snapshots below. Extraction does not run again.</p></section>
    <details className="ck-panel"><summary>Configure papers, batches, and enrollment access</summary><fieldset disabled={!canManage || busy}>
      <div className="ck-grid"><label>Paper code<input value={paperCode} onChange={e => setPaperCode(e.target.value)} /></label><label>Paper name<input value={paperName} onChange={e => setPaperName(e.target.value)} /></label><button onClick={() => void action(() => knowledgeRequest('/education/knowledge/papers', 'POST', { curriculumId: curriculum, code: paperCode, name: paperName }), 'Paper created.')}>Create paper</button><button disabled={!batch || !curriculum} onClick={() => void action(() => knowledgeRequest('/education/knowledge/batch-curriculum', 'PUT', { batchId: batch, curriculumId: curriculum }), 'Batch curriculum bound.')}>Bind selected batch to curriculum</button></div>
      <div className="ck-sync-access"><div><strong>Enrollment access</strong><p>Preview active enrollments and snapshot the papers available today. This never removes access; papers created later require another sync.</p></div><button type="button" disabled={!agent || !course} onClick={() => void previewEnrollmentAccessSync()}>Preview eligible enrollments</button></div>
      {syncPreview ? <div className="ck-sync-preview"><p><strong>Preview:</strong> {syncPreview.counts.will_create ?? 0} to create, {syncPreview.counts.will_repair ?? 0} to repair, {syncPreview.counts.manual_preserved ?? 0} manual records preserved, {syncPreview.counts.ineligible ?? 0} ineligible.</p><div className="ck-sync-preview__rows">{syncPreview.items.map(item => { const selectable = item.disposition !== 'ineligible'; return <label key={item.enrollmentId} className={`ck-sync-preview__row ck-sync-preview__row--${item.disposition}`}><input type="checkbox" disabled={!selectable} checked={syncSelected.includes(item.enrollmentId)} onChange={() => setSyncSelected(current => toggle(current, item.enrollmentId))} /><span><strong>{item.studentId?.slice(0, 8) ?? 'Student'} · {name(batches.find(value => value.id === item.batchId)) || 'Batch'}</strong><small>{item.disposition.replaceAll('_', ' ')} — {item.reason}</small><small>Snapshot papers: {(item.proposedPaperIds ?? []).map(id => name(papers.find(value => value.id === id)) || id.slice(0, 8)).join(', ') || 'None'}</small></span></label>; })}</div><div className="ck-actions"><button type="button" disabled={!syncSelected.length} onClick={() => void applyEnrollmentAccessSync()}>Apply access to {syncSelected.length} enrollment{syncSelected.length === 1 ? '' : 's'}</button><button type="button" disabled={!syncSelected.length} onClick={() => void revokeEnrollmentAccessSync()}>Revoke knowledge access</button></div></div> : null}
    </fieldset></details>
    <section className="ck-panel"><h3>1. Upload into this course</h3><p><strong>Course mapping is required.</strong> The selected Course becomes the document&apos;s retrieval scope. No embedding is created; published text is searched lexically only inside that Course.</p><form onSubmit={event => void upload(event)}><fieldset disabled={!canManage || busy || !agent}>
      <label>Source title<input required value={title} onChange={e => setTitle(e.target.value)} maxLength={180} /></label>
      <label>File<input type="file" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.tif,.tiff" onChange={e => { setFile(e.target.files?.[0] ?? null); staged.current = null; }} /></label>
      <label>Or native text<textarea value={text} onChange={e => setText(e.target.value)} disabled={!!file} rows={5} /></label>
      <button type="submit" disabled={!course || !curriculum || !paper || (!file && !text.trim())}>{busy ? 'Working…' : 'Upload and prepare'}</button>
    </fieldset></form><p>Legacy or bulk uploads without an assignment remain an administrative inbox, never shared student knowledge.</p>
    {status.sources.map(s => <div className="ck-row" key={s.id}><span>{name(s)} — {s.status}{status.jobs.find(j => j.sourceId === s.id)?.step ? ` / ${status.jobs.find(j => j.sourceId === s.id)?.step}` : ''}</span><Link to={`/agents/${agent}/knowledge`}>Extraction review</Link><button disabled={!canManage || busy || s.status !== 'ready'} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/sources/${s.id}/snapshot`), 'POST'), 'Reviewed source snapshot prepared.')}>Prepare immutable snapshot</button></div>)}</section>
    <section className="ck-panel"><h3>Existing trained mappings</h3><p>These older Draft or Published badges do not by themselves create a Course Knowledge release for the WhatsApp tutor. Reuse the extraction, review its blocks here, then approve, index and publish through the steps below.</p>{status.legacyScopes.filter(s => !course || s.courseId === course).map(s => <div className="ck-row" key={s.id}><span><strong>{name(status.sources.find(source => source.id === s.sourceId))}</strong><small>{name(catalog.courses.find(c => c.id === s.courseId))} · {s.paperId ? paperLabel(s.paperId) : 'Overview'} · {s.approvalStatus ?? 'draft'}</small></span><button disabled={!canManage || busy || !status.versions.some(v => v.sourceId === s.sourceId && !v.withdrawn)} onClick={() => void action(() => reviewExistingMapping(s), 'Existing mapping loaded for block review; save and approve an explicit Course Knowledge assignment.')}>Review in course setup</button></div>)}</section>
    <section className="ck-panel" id="course-block-review"><h3>2. Review and map source blocks</h3><label>Source version<select value={detail?.id ?? ''} onChange={e => { if (e.target.value) void action(() => openVersion(e.target.value), 'Source blocks loaded.'); }}><option value="">Choose version</option>{status.versions.map(v => <option key={v.id} value={v.id}>{name(v)} / v{v.sourceRevision}{v.withdrawn ? ' (withdrawn)' : ''}</option>)}</select></label>
      {detail && <><p>{detail.sourceUnitNotice}</p><div className="ck-actions"><button onClick={() => void action(() => download(knowledgePath(agent, `/versions/${detail.id}/report`), 'course-knowledge-review.zip'), 'Extraction report downloaded.')}>Download text, structure, mapping, and validation</button><button disabled={!canManage || busy || !reason.trim()} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/versions/${detail.id}/withdraw`), 'POST', { reason }), 'Source and dependent material withdrawn.')}>Withdraw this source version</button></div>
      <div className="ck-review"><div>{detail.blocks.map(b => <article className="ck-block" key={b.id}><label><input type="checkbox" checked={blocks.includes(b.id)} onChange={() => setBlocks(toggle(blocks, b.id))} />{b.id} / {b.type} / {b.page_number ? `page ${b.page_number}` : `source unit ${b.unit}`}</label><pre>{b.text}</pre>{b.structure ? <details><summary>Source structure</summary><pre>{JSON.stringify(b.structure, null, 2)}</pre></details> : null}{b.related_block_ids.length > 0 && <small>Include linked blocks: {b.related_block_ids.join(', ')}</small>}<button onClick={() => void action(async () => { const image = await knowledgeBlob(`/knowledge/${detail.sourceId}/extraction/pages/${b.unit}`); setOriginalImage(URL.createObjectURL(image)); }, 'Original source unit loaded for staff review.')}>View original source unit</button></article>)}</div><div>{originalImage ? <img src={originalImage} alt="Original source unit for comparison with extracted blocks" /> : <p>Select an original source unit to compare it beside the extraction. Text-only sources have no page image.</p>}</div></div>
      <div className="ck-actions"><button type="button" disabled={!canManage || busy || detail.blocks.length === 0 || blocks.length === detail.blocks.length} onClick={() => setBlocks(detail.blocks.map(block => block.id))}>Select all</button><button disabled={!canManage || busy || !blocks.length || paper === 'mixed' || !paper || source?.withdrawn} onClick={() => void saveMapping()}>{editing ? 'Save new mapping revision' : 'Save selected blocks as assignment'}</button></div></>}
      <label>Review / withdrawal reason<textarea value={reason} onChange={e => setReason(e.target.value)} rows={2} /></label><label><input type="checkbox" checked={mismatch} onChange={e => setMismatch(e.target.checked)} />I reviewed any possible course mismatch and confirm the explicit destination.</label>
      {scopeAssignments.map(a => <article className="ck-block" key={a.id}><label><input type="checkbox" checked={selectedAssignments.includes(a.id)} onChange={() => setSelectedAssignments(toggle(selectedAssignments, a.id))} />{a.id.slice(0, 8)} / revision {a.revision} / {a.status} / index {a.indexStatus}</label><p>{a.overview ? 'Course overview' : name(papers.find(p => p.id === a.paperId))} / {a.batchId ? name(batches.find(b => b.id === a.batchId)) : 'All matching batches'} / {a.blockIds?.length} blocks</p>{a.indexError && <p role="alert">{a.indexError}</p>}{a.validation?.warnings?.map((w, i) => <p key={i} className="ck-error">{w.code}: {w.evidence}</p>)}<div className="ck-actions">
        <button disabled={!canManage || busy || a.status === 'withdrawn'} onClick={() => void action(async () => { const v = await knowledgeRequest<VersionDetail>(knowledgePath(agent, `/versions/${a.sourceVersionId}`)); setDetail(v); setBlocks(a.blockIds ?? []); setEditing(a); setPaper(a.overview ? 'overview' : a.paperId ?? ''); setBatch(a.batchId ?? ''); }, 'Mapping loaded for editing.')}>Edit mapping</button>
        <button disabled={!canManage || busy || a.status !== 'review' || !reason.trim()} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/assignments/${a.id}/approve`), 'POST', { expectedRevision: a.revision, expectedSourceHash: status.versions.find(v => v.id === a.sourceVersionId)?.recordHash, reason, mismatchConfirmed: mismatch }), 'Exact mapping revision approved.')}>Approve exact revision</button>
        <button disabled={!canManage || busy || a.status !== 'approved'} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/assignments/${a.id}/prepare`), 'POST', { expectedRevision: a.revision }), 'Durable index preparation requested.')}>Prepare / retry index</button>
        <button disabled={!canManage || busy || !reason.trim()} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/assignments/${a.id}/withdraw`), 'POST', { reason }), 'Assignment withdrawn immediately.')}>Withdraw assignment</button></div></article>)}
    </section>
    <section className="ck-panel"><h3>3. Derived learning material</h3><p>Generated material stays in review and inherits the intersection of all selected source audiences.</p><select aria-label="Artifact type" value={artifactType} onChange={e => setArtifactType(e.target.value)}>{['summary', 'flashcards', 'practice_questions', 'translation', 'worked_example'].map(t => <option key={t}>{t}</option>)}</select><button disabled={!canManage || busy || !selectedAssignments.length} onClick={() => void action(async () => { const a = await knowledgeRequest<KnowledgeRecord>(knowledgePath(agent, '/artifacts'), 'POST', { assignmentIds: selectedAssignments, artifactType }); setArtifactReview(a); setAnswerKeyVerified(false); }, 'Draft artifact generated; it is not student evidence yet.')}>Generate draft from selected assignments</button>
      {status.artifacts.map(a => <div className="ck-row" key={a.id}><label><input type="checkbox" checked={selectedArtifacts.includes(a.id)} onChange={() => setSelectedArtifacts(toggle(selectedArtifacts, a.id))} />{a.artifactType} / {a.reviewStatus}{a.withdrawn ? ' / withdrawn' : ''}</label><button onClick={() => void action(async () => { setArtifactReview(await knowledgeRequest<KnowledgeRecord>(knowledgePath(agent, `/artifacts/${a.id}`))); setAnswerKeyVerified(false); }, 'Artifact loaded for review.')}>Review content</button></div>)}
      {artifactReview && <><pre>{artifactReview.content}</pre><label><input type="checkbox" checked={answerKeyVerified} onChange={e => setAnswerKeyVerified(e.target.checked)} />A teacher has separately validated this practice answer key.</label><button disabled={!canManage || busy || !reason.trim() || !artifactReview.fingerprint} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/artifacts/${artifactReview.id}/approve`), 'POST', { expectedFingerprint: artifactReview.fingerprint, reason, answerKeyValidated: answerKeyVerified }), 'Derived material reviewed; include it in a later release.')}>Approve artifact</button></>}
    </section>
    <section className="ck-panel" id="course-faq-library"><h3>4. Teacher-approved Q&A library</h3><p>Repeated questions are answered immediately only after a teacher approves this Q&A and publishes a release containing it. Drafts and web answers are never self-published.</p><fieldset disabled={!canManage || busy || !agent}>
      <label>Question<input value={faqQuestion} onChange={e => setFaqQuestion(e.target.value)} maxLength={4000} /></label>
      <label>Accepted question variants (one per line)<textarea value={faqVariants} onChange={e => setFaqVariants(e.target.value)} rows={3} /></label>
      <label>Teacher-approved answer<textarea value={faqAnswer} onChange={e => setFaqAnswer(e.target.value)} rows={5} /></label>
      <label>Verified external source URL (optional if a source assignment is selected or this came from a teacher review)<input type="url" value={faqReference} onChange={e => setFaqReference(e.target.value)} /></label>
      {faqReviewId && <p>Based on resolved teacher review {faqReviewId.slice(0, 8)}.</p>}
      <button disabled={!faqQuestion.trim() || !faqAnswer.trim() || !course || !curriculum || !paper || paper === 'mixed'} onClick={() => void saveFaq()}>{editingFaq ? 'Save new draft revision' : 'Save draft Q&A'}</button>
    </fieldset>
      {status.faqs.filter(f => f.courseId === course && f.curriculumId === curriculum).map(f => <article key={f.id} className="ck-block"><label><input type="checkbox" checked={selectedFaqs.includes(f.id)} disabled={f.status !== 'approved'} onChange={() => setSelectedFaqs(toggle(selectedFaqs, f.id))} /><strong>{f.question}</strong> · {f.status} · revision {f.revision}</label><p>{f.answer}</p><small>{f.paperId ? paperLabel(f.paperId) : 'Course overview'} · {f.batchId ? name(batches.find(b => b.id === f.batchId)) : 'All batches'} · {f.references?.length ?? 0} source(s)</small><div className="ck-actions"><button disabled={!canManage || busy || f.status === 'withdrawn'} onClick={() => { setEditingFaq(f); setFaqQuestion(f.question ?? ''); setFaqAnswer(f.answer ?? ''); setFaqVariants((f.variants ?? []).join('\n')); setFaqReference(f.references?.find(r => r.kind === 'external')?.url ?? ''); setFaqReviewId(f.reviewId ?? ''); setPaper(f.paperId ?? 'overview'); setBatch(f.batchId ?? ''); }}>Edit</button><button disabled={!canManage || busy || f.status !== 'draft' || !reason.trim()} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/faqs/${f.id}/approve`), 'POST', { expectedRevision: f.revision, reason }), 'Q&A approved. Include it in a new release before students can use it.')}>Approve reviewed answer</button><button disabled={!canManage || busy || !reason.trim() || f.status === 'withdrawn'} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/faqs/${f.id}/withdraw`), 'POST', { reason }), 'Q&A withdrawn immediately from future matches.')}>Withdraw</button></div></article>)}
    </section>
    <section className="ck-panel" id="course-release"><h3>5. Publish an exact release</h3><p>A candidate replaces the complete manifest. Select every approved assignment, artifact and Q&A that must remain available. An approved Q&A is not live until this release is published.</p>{currentManifest && <button disabled={busy} onClick={() => { setSelectedAssignments(currentManifest.assignments.map(a => a.assignment_id)); setSelectedArtifacts(currentManifest.artifacts.map(a => a.id)); setSelectedFaqs((currentManifest.faqs ?? []).map(a => a.id)); }}>Start from active release</button>}<button disabled={!canManage || busy || !selectedAssignments.length} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, '/releases'), 'POST', { courseId: course, curriculumId: curriculum, assignmentIds: selectedAssignments, artifactIds: selectedArtifacts, faqIds: selectedFaqs }), 'Candidate verified. Review its contents before publication.')}>Build candidate release</button>
      {status.releases.filter(r => r.courseId === course && r.curriculumId === curriculum).map(r => <article key={r.id} className="ck-block"><strong>{r.id.slice(0, 8)} / {r.status}{status.heads.some(h => h.releaseId === r.id) ? ' / ACTIVE' : ''}</strong><pre>{JSON.stringify(r.manifest, null, 2)}</pre><button disabled={!canManage || busy || status.heads.some(h => h.releaseId === r.id)} onClick={() => void publish(r)}>Publish this exact release</button></article>)}
      <p>Published coverage is separate from processing: papers absent from the active manifest have no published paper material.</p>
    </section>
    <section className="ck-panel" id="course-workflow"><h3>WhatsApp workflow messages</h3><p>Preview the active workflow here. Verified enrollments and access decisions are supplied by the backend, not editable text.</p><div className="ck-actions"><Link to={`/workflows?agentId=${encodeURIComponent(agent)}`}>Edit messages and triggers</Link></div>{!workflow || workflow.status !== 'active' ? <p className="ck-empty">No active workflow; the tutor uses safe built-in messages.</p> : workflow.steps.filter(step => step.enabled && Boolean(step.config?.systemAction)).map(step => <article className="ck-block" key={step.id}><strong>{step.name}</strong><small> · {String(step.config.systemAction)}</small><pre>{step.message.replaceAll('{{course}}', courseName || 'Selected course').replaceAll('{{paper}}', paperLabel(paper === 'overview' ? null : paper)).replaceAll('{{course_count}}', '[verified course count]').replaceAll('{{courses}}', '[Only this student’s verified enrollments]').replaceAll('{{papers}}', '[Only this student’s permitted papers]')}</pre></article>)}</section>
    <section className="ck-panel" id="course-test"><h3>6. Test as an enrolled student</h3><label>Enrollment<select value={enrollment} onChange={e => selectEnrollment(e.target.value)}><option value="">Select enrollment</option>{status.enrollments.filter(e => e.courseId === course).map(e => <option key={e.id} value={e.id}>{e.studentId} / {e.status}</option>)}</select></label><label>Question<input value={query} onChange={e => setQuery(e.target.value)} /></label><button disabled={busy || !enrollment || !query} onClick={() => void action(async () => setPreview(await knowledgeRequest<StudentPreview>(knowledgePath(agent, '/preview'), 'POST', previewBody)), 'Student authorization preview completed.')}>Preview authorized sources</button><button disabled={busy || !canManage || !enrollment} onClick={() => void startTestChat()}>Start published student chat</button>{testConversation && <div className="ck-test-chat"><label>Ask the real tutor<input value={testQuestion} onChange={e => setTestQuestion(e.target.value)} /></label><button disabled={busy || !testQuestion.trim()} onClick={() => void askTestChat()}>Send test question</button>{testAnswer && <pre role="status">{testAnswer}</pre>}</div>}
      {preview && <><p>{preview.notice}</p>{preview.evidence.map(e => <article key={e.entity_id} className="ck-block"><h4>{e.title}</h4><pre>{e.text}</pre><small>{JSON.stringify(e.metadata)}</small>{e.kind === 'course_chunk' && <button onClick={() => void action(async () => saveKnowledgeBlob(await knowledgeBlob(knowledgePath(agent, `/preview/excerpts/${e.entity_id}`), 'POST', previewBody), 'authorized-excerpt.txt'), 'Scoped excerpt downloaded.')}>Download only this authorized excerpt</button>}</article>)}</>}
    </section>
    <section className="ck-panel" id="course-audit-filters"><h3>Recent WhatsApp turns</h3><p>Filter the last 25 records or export the matching audit history. Phone numbers are omitted from downloads.</p><div className="ck-grid"><label>Answer path<select value={auditPath} onChange={e => setAuditPath(e.target.value)}><option value="">All paths</option>{['workflow', 'faq', 'document', 'web', 'unavailable', 'refusal', 'access_denied', 'retry'].map(value => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></label><label>Delivery<select value={auditDelivery} onChange={e => setAuditDelivery(e.target.value)}><option value="">All statuses</option>{['submitted', 'sent', 'delivered', 'read', 'failed', 'rejected'].map(value => <option key={value}>{value}</option>)}</select></label></div><div className="ck-actions"><button disabled={!agent} onClick={() => void action(() => download(knowledgePath(agent, `/whatsapp-turns/export?format=csv&${auditQuery()}`), 'course-whatsapp-qa-filtered.csv'), 'Filtered CSV downloaded.')}>Export filtered CSV</button><button disabled={!agent} onClick={() => void action(() => download(knowledgePath(agent, `/whatsapp-turns/export?format=json&${auditQuery()}`), 'course-whatsapp-qa-filtered.json'), 'Filtered JSON downloaded.')}>Export filtered JSON</button></div>{turns.length === 0 ? <p className="ck-empty">No recorded turns match these filters.</p> : turns.map(turn => <article className="ck-block" key={turn.id}><div className="ck-record-heading"><strong>{new Date(turn.createdAt).toLocaleString()} · {turn.answerPath}</strong><span>{turn.deliveryStatus}{turn.reviewStatus ? ` · review ${turn.reviewStatus}` : ''}</span></div><p><strong>Question:</strong> {turn.question}</p><p><strong>Answer:</strong> {turn.answer || 'No answer delivered.'}</p><small>{turn.citations.length} source reference(s) · {turn.paperId ? paperLabel(turn.paperId) : 'Course overview or not selected'}</small></article>)}</section>
    <section className="ck-panel" id="course-review"><h3>Teacher review queue</h3><p>Low-confidence and ungrounded answers appear here. Resolving a review alone does not publish course material; create and release a reviewed Q&A.</p>{reviews.length === 0 && <p className="ck-empty">No academic reviews for this agent.</p>}{reviews.map(r => { const open = ['pending', 'open', 'assigned'].includes(r.status); return <article className="ck-block" key={r.id}><div className="ck-record-heading"><strong>{enrollmentLabel(r.enrollmentId)} · {paperLabel(r.paperId)}</strong><span className={`ck-state ck-state--${open ? 'attention' : 'complete'}`}>{r.status}</span></div><p><strong>Student question:</strong> {r.question}</p><details><summary>Answer and retrieval diagnostics</summary><p>{r.answer || 'No answer was delivered.'}</p><small>Reason: {r.reason} · Internal candidates: {r.internalEvidence.length} · External sources: {r.externalEvidence.length}</small>{r.internalEvidence.length > 0 && <pre>{JSON.stringify(r.internalEvidence, null, 2)}</pre>}</details>{r.resolution && <p><strong>Resolution:</strong> {r.resolution}</p>}{open ? <><label>Teacher resolution<textarea rows={3} value={reviewNotes[r.id] ?? ''} onChange={e => setReviewNotes(current => ({ ...current, [r.id]: e.target.value }))} placeholder="Record what was checked and the approved conclusion." /></label><div className="ck-actions"><button disabled={!canManage || busy || !reviewNote(r.id)} onClick={() => void resolveAcademicReview(r, 'confirmed')}>Confirm answer</button><button disabled={!canManage || busy || !reviewNote(r.id)} onClick={() => void resolveAcademicReview(r, 'corrected')}>Record correction</button></div></> : <button disabled={!canManage || busy || !r.courseId} onClick={() => draftFromReview(r)}>Create draft Q&A from review</button>}</article>; })}</section>
    <section className="ck-panel" id="course-audit"><h3>WhatsApp Q&A history</h3><p>Processed Education WhatsApp turns are auditable. Downloads omit phone identifiers and mask sensitive text; they are not automatic training data.</p>{status.metrics && <div className="ck-metric-grid"><div><strong>{status.metrics.sampledTurns7d}</strong><small>Recent turns</small></div><div><strong>{status.metrics.p50Ms == null ? '—' : `${status.metrics.p50Ms} ms`}</strong><small>Median answer time</small></div><div><strong>{status.metrics.p95Ms == null ? '—' : `${status.metrics.p95Ms} ms`}</strong><small>95th percentile</small></div><div><strong>{status.metrics.deliveryFailures}</strong><small>Delivery failures</small></div><div><strong>{status.metrics.openKnowledgeGaps}</strong><small>Open review gaps</small></div><div><strong>{status.metrics.answerPaths.faq ?? 0}</strong><small>Fast Q&A hits</small></div></div>}<div className="ck-actions"><button disabled={!agent} onClick={() => void action(() => download(knowledgePath(agent, `/whatsapp-turns/export?format=csv${course ? `&course_id=${encodeURIComponent(course)}` : ''}`), 'course-whatsapp-qa.csv'), 'CSV downloaded.')}>Download CSV</button><button disabled={!agent} onClick={() => void action(() => download(knowledgePath(agent, `/whatsapp-turns/export?format=json${course ? `&course_id=${encodeURIComponent(course)}` : ''}`), 'course-whatsapp-qa.json'), 'JSON downloaded.')}>Download JSON</button></div></section>
    <section className="ck-panel"><h3>Learning progress</h3><p>Activity indicators only; these values are not an exam-readiness score.</p>{progress.length === 0 && <p className="ck-empty">No paper practice has been recorded for this agent.</p>}{progress.map(item => { const percentage = item.objectiveAnswersGraded ? Math.round(item.objectiveAnswersCorrect / item.objectiveAnswersGraded * 100) : null; return <div className="ck-row ck-progress-row" key={item.id}><span><strong>{enrollmentLabel(item.enrollmentId)} · {paperLabel(item.paperId)}</strong><small>Student {item.studentId.slice(0, 8)} · {item.learningStatus.replaceAll('_', ' ')}</small></span><span className="ck-metrics"><strong>{percentage === null ? '—' : `${percentage}%`}</strong><small>{item.objectiveAnswersCorrect}/{item.objectiveAnswersGraded} graded correct · {item.practiceAttempts} attempts · {item.questionsAsked} questions</small></span></div>; })}</section>
    <section className="ck-panel"><h3>Tutor context diagnostics</h3><p>Resetting context clears remembered course and menu state; it does not change enrollment permission.</p>{contexts.length === 0 && <p className="ck-empty">No student has created tutor context for this agent.</p>}{contexts.map(item => <article className="ck-block" key={`${item.identityId}-${item.agentId}`}><div className="ck-record-heading"><strong>{enrollmentLabel(item.enrollmentId)}</strong><span className={`ck-state ck-state--${item.interactionState === 'ready_for_question' ? 'complete' : 'attention'}`}>{item.interactionState.replaceAll('_', ' ')}</span></div><small>Identity {item.identityId.slice(0, 8)} · revision {item.selectionRevision}{item.menuExpiresAt ? ` · menu expires ${new Date(item.menuExpiresAt).toLocaleString()}` : ''}</small>{item.pendingQuestion && <p><strong>Pending question:</strong> {item.pendingQuestion}</p>}<button disabled={!canManage || busy} onClick={() => { if (window.confirm('Reset this student’s remembered course and pending menu? Enrollment permissions will remain unchanged.')) void action(() => knowledgeRequest(`/education/tutor-contexts/${item.identityId}/${item.agentId}`, 'DELETE'), 'Tutor selection reset; authorization records were unchanged.'); }}>Reset remembered selection</button></article>)}</section>
  </div>;
}
