import { ArrowRight, BookOpen, Check, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, Modal } from '@/components/ui';
import { educationApi } from '@/lib/education-api';
import { educationCatalogApi } from '@/lib/education-catalog-api';
import { educationKnowledgeApi, type EducationKnowledgeScope, type EducationKnowledgeScopeRef } from '@/lib/education-knowledge-api';
import { useApi } from '@/lib/use-api';
import type { KnowledgeSource } from '@/types';
import './education-knowledge-scope-manager.css';

interface Props { agentId: string; sources: KnowledgeSource[] }
interface ScopeDraft extends EducationKnowledgeScopeRef { key: string }

export function EducationKnowledgeScopeManager({ agentId, sources }: Props) {
  const { pushToast } = useToast();
  const sourceKey = sources.map((source) => source.id).sort().join(':');
  const courses = useApi(() => educationApi.courses.list({ status: 'active' }), [agentId]);
  const batches = useApi(() => educationApi.batches.list({ status: 'active' }), [agentId]);
  const papers = useApi(() => educationCatalogApi.papers(), [agentId]);
  const scopes = useApi(async () => Object.fromEntries(await Promise.all(
    sources.map(async (source) => [source.id, await educationKnowledgeApi.sourceScopes(source.id)] as const),
  )) as Record<string, EducationKnowledgeScope[]>, [agentId, sourceKey]);
  const [editingSource, setEditingSource] = useState<KnowledgeSource | null>(null);
  const [draft, setDraft] = useState<ScopeDraft[]>([]);
  const [courseId, setCourseId] = useState('');
  const [paperId, setPaperId] = useState('');
  const [batchId, setBatchId] = useState('');
  const [materialType, setMaterialType] = useState('notes');
  const [saving, setSaving] = useState(false);
  const [publishingId, setPublishingId] = useState('');
  const [error, setError] = useState('');
  const hasSimplifiedCourse = (courses.data ?? []).some((course) => course.simplifiedWorkflow && course.assignedAgentId === agentId);

  // Curriculum is not chosen here: the server takes it from the Paper, the Batch, or the Course.
  const availablePapers = useMemo(() => (papers.data ?? []).filter((item) => item.courseId === courseId && item.status === 'active'), [papers.data, courseId]);
  const paperCurriculum = availablePapers.find((item) => item.id === paperId)?.curriculumId;
  const availableBatches = useMemo(() => (batches.data ?? []).filter((batch) => batch.courseId === courseId && (!paperCurriculum || !batch.curriculumId || batch.curriculumId === paperCurriculum)), [batches.data, courseId, paperCurriculum]);
  const resetPicker = () => { setCourseId(''); setPaperId(''); setBatchId(''); setError(''); };
  const closeScope = () => { if (!saving) { setEditingSource(null); setDraft([]); resetPicker(); } };
  const openScope = (source: KnowledgeSource) => { setEditingSource(source); setDraft((scopes.data?.[source.id] ?? []).map((item) => ({ ...item, key: item.id }))); resetPicker(); };

  const addTuple = () => {
    if (!courseId) { setError('Choose a Course.'); return; }
    if (draft.some((item) => item.courseId === courseId && (item.paperId ?? '') === paperId && (item.batchId ?? '') === batchId)) { setError('This course audience is already selected.'); return; }
    setDraft((current) => [...current, { courseId, paperId: paperId || null, batchId: batchId || null, materialType, key: `${courseId}:${paperId}:${batchId}` }]);
    resetPicker();
  };
  const save = async () => {
    if (!editingSource) return;
    setSaving(true); setError('');
    try {
      await educationKnowledgeApi.setSourceScopes(editingSource.id, agentId, draft.map(({ key: _key, ...scope }) => scope));
      scopes.reload(); pushToast(draft.length ? 'Course document assignments saved' : 'Source is unavailable to Education students');
      setEditingSource(null); setDraft([]); resetPicker();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save Education knowledge scope.'); }
    finally { setSaving(false); }
  };
  const scopeLabel = (scope: EducationKnowledgeScope | ScopeDraft) => {
    const course = courses.data?.find((item) => item.id === scope.courseId);
    const paper = papers.data?.find((item) => item.id === scope.paperId);
    const batch = batches.data?.find((item) => item.id === scope.batchId);
    return [course?.code ?? 'Course', paper?.code ?? 'Overview', batch?.code ?? 'All batches'].join(' · ');
  };
  const publish = async (scope: EducationKnowledgeScope) => {
    if (!window.confirm(`Publish ${scopeLabel(scope)} for students? Only this verified course audience will be able to use the source.`)) return;
    setPublishingId(scope.id);
    try {
      if (scope.approvalStatus === 'draft') await educationKnowledgeApi.approve(scope);
      await educationKnowledgeApi.publish(scope);
      await scopes.reload();
      pushToast('Course mapping approved and published for students.');
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Could not publish this course mapping.', 'error');
    } finally { setPublishingId(''); }
  };
  const scopeAction = (scope: EducationKnowledgeScope) => {
    if (!scope.requiresRelease && scope.approvalStatus === 'published') return <span className="education-knowledge-scope-row__ready"><Check /> Ready for this Course</span>;
    if (scope.approvalStatus === 'published') return <span className="education-knowledge-scope-row__ready"><Check /> Legacy mapping published · finish tutor release</span>;
    if (scope.approvalStatus === 'withdrawn') return <span className="education-knowledge-scope-row__pending">Withdrawn</span>;
    const label = scope.approvalStatus === 'approved' ? 'Publish to students' : 'Review & publish';
    return <Button size="sm" disabled={Boolean(publishingId)} onClick={() => void publish(scope)}>{publishingId === scope.id ? 'Publishing…' : label}</Button>;
  };

  return <>
    <Card className={`education-knowledge-scope-card${hasSimplifiedCourse ? ' is-simplified' : ''}`}>
      <div className="education-knowledge-scope-card__heading"><span><ShieldCheck /></span><div><h3>{hasSimplifiedCourse ? 'Course document assignments' : 'Existing source mappings'}</h3><p>{hasSimplifiedCourse ? 'Each document is assigned during upload and is retrieved only for its displayed Course.' : 'These mappings are not the WhatsApp tutor release. Complete course setup and publish the exact release in Course Knowledge.'}</p></div></div>
      <div className="education-knowledge-setup" aria-label="Education knowledge setup steps">
        <div><span><Check /></span><strong>1. Train</strong><small>Upload a source and wait for Training complete.</small></div>
        <div><span><ArrowRight /></span><strong>2. Map</strong><small>Choose its course, paper, and batch.</small></div>
        <div><span><ArrowRight /></span><strong>3. Publish</strong><small>Review and make the mapping live below.</small></div>
        <div><span><ArrowRight /></span><strong>4. Grant access</strong><small><a href={`/education/knowledge?agentId=${agentId}`}>Configure curriculum and student paper access</a>.</small></div>
      </div>
      <div className="education-knowledge-scope-card__notice"><strong>Student safety:</strong> unassigned, draft, or withdrawn material never reaches a student. Publishing only makes the selected course audience eligible.</div>
      {scopes.loading || courses.loading || batches.loading || papers.loading ? <div className="table-loading">Loading Education scopes…</div> : sources.length ? <div className="education-knowledge-scope-list">{sources.map((source) => {
        const bindings = scopes.data?.[source.id] ?? [];
        // Only trained material can be mapped to courses; mapping earlier would point students at nothing.
        const trained = source.status === 'ready';
        return <div className="education-knowledge-scope-row" key={source.id}><div className="education-knowledge-scope-row__source"><strong>{source.name}</strong><small>{source.kind} · {source.chunks} chunks{trained ? ' · training complete' : ''}</small></div><div className="education-knowledge-scope-row__bindings">{bindings.length ? bindings.map((scope) => <div className="education-knowledge-scope-row__binding" key={scope.id}><Badge tone={scope.approvalStatus === 'published' ? 'success' : scope.approvalStatus === 'withdrawn' ? 'danger' : 'purple'}>{scopeLabel(scope)} · {scope.approvalStatus ?? 'draft'}</Badge>{scopeAction(scope)}</div>) : <Badge tone="warning">Unassigned · blocked</Badge>}</div>{!hasSimplifiedCourse ? trained ? <Button variant="secondary" size="sm" onClick={() => openScope(source)}>Manage mappings</Button>
          : <span className="education-knowledge-scope-row__pending" title="Courses can only use material whose training is complete">{source.status === 'needs_review' ? 'Map after training: finish the extraction review' : source.status === 'failed' ? 'Training failed: retrain before mapping' : 'Map after training completes'}</span> : null}</div>;
      })}</div> : <EmptyState icon={BookOpen} title="No knowledge to map" description="Add a source with its intended Education destination before publishing." />}
    </Card>

    <Modal open={Boolean(editingSource)} onClose={closeScope} title={editingSource ? `Course mappings · ${editingSource.name}` : 'Course mappings'} description="Each row is a Course, an optional Paper, and an optional Batch. Course overview does not mean all papers." size="lg" footer={<><Button variant="secondary" disabled={saving} onClick={closeScope}>Cancel</Button><Button icon={ShieldCheck} disabled={saving} onClick={() => void save()}>{saving ? 'Saving…' : 'Save draft mappings'}</Button></>}>
      <div className="education-knowledge-scope-editor"><div className="education-knowledge-scope-editor__picker">
        <Field label="Course" htmlFor="education-knowledge-course"><select id="education-knowledge-course" value={courseId} onChange={(event) => { setCourseId(event.target.value); setPaperId(''); setBatchId(''); setError(''); }}><option value="">Choose Course</option>{(courses.data ?? []).map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}</select></Field>
        <Field label="Paper" htmlFor="education-knowledge-paper"><select id="education-knowledge-paper" value={paperId} disabled={!courseId} onChange={(event) => { setPaperId(event.target.value); setBatchId(''); }}><option value="">Course overview</option>{availablePapers.map((item) => <option value={item.id} key={item.id}>{item.code} · {item.name}</option>)}</select></Field>
        <Field label="Audience" htmlFor="education-knowledge-batch"><select id="education-knowledge-batch" value={batchId} disabled={!courseId} onChange={(event) => setBatchId(event.target.value)}><option value="">All matching batches</option>{availableBatches.map((batch) => <option value={batch.id} key={batch.id}>{batch.code} · {batch.name}</option>)}</select></Field>
        <Field label="Material type" htmlFor="education-knowledge-material-type"><select id="education-knowledge-material-type" value={materialType} onChange={(event) => setMaterialType(event.target.value)}><option value="notes">Notes</option><option value="textbook">Textbook</option><option value="practice">Practice</option><option value="worked_examples">Worked examples</option></select></Field>
        <Button variant="secondary" icon={Plus} onClick={addTuple}>Add assignment</Button>
      </div>{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="education-knowledge-scope-editor__selected">{draft.length ? draft.map((scope) => <div key={scope.key}><span>{scopeLabel(scope)}</span><button type="button" aria-label={`Remove ${scopeLabel(scope)}`} onClick={() => setDraft((current) => current.filter((item) => item.key !== scope.key))}><Trash2 /></button></div>) : <p>No assignment selected. This source will remain blocked from Education retrieval.</p>}</div></div>
    </Modal>
  </>;
}
