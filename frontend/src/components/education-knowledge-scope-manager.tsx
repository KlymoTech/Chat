import { BookOpen, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, Modal } from '@/components/ui';
import { educationApi } from '@/lib/education-api';
import {
  educationKnowledgeApi,
  type EducationKnowledgeScope,
  type EducationKnowledgeScopeRef,
} from '@/lib/education-knowledge-api';
import { useApi } from '@/lib/use-api';
import type { KnowledgeSource } from '@/types';
import './education-knowledge-scope-manager.css';

interface EducationKnowledgeScopeManagerProps {
  agentId: string;
  sources: KnowledgeSource[];
}

interface ScopeDraft extends EducationKnowledgeScopeRef {
  key: string;
}

export function EducationKnowledgeScopeManager({
  agentId,
  sources,
}: EducationKnowledgeScopeManagerProps) {
  const { pushToast } = useToast();
  const sourceKey = sources.map((source) => source.id).sort().join(':');
  const courses = useApi(() => educationApi.courses.list({ status: 'active' }), [agentId]);
  const batches = useApi(() => educationApi.batches.list({ status: 'active' }), [agentId]);
  const scopes = useApi(async () => {
    const entries = await Promise.all(
      sources.map(async (source) => [source.id, await educationKnowledgeApi.sourceScopes(source.id)] as const),
    );
    return Object.fromEntries(entries) as Record<string, EducationKnowledgeScope[]>;
  }, [agentId, sourceKey]);
  const [editingSource, setEditingSource] = useState<KnowledgeSource | null>(null);
  const [draft, setDraft] = useState<ScopeDraft[]>([]);
  const [courseId, setCourseId] = useState('');
  const [batchId, setBatchId] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const availableBatches = useMemo(
    () => (batches.data ?? []).filter((batch) => batch.courseId === courseId),
    [batches.data, courseId],
  );

  const openScope = (source: KnowledgeSource) => {
    const existing = scopes.data?.[source.id] ?? [];
    setEditingSource(source);
    setDraft(existing.map((item) => ({ courseId: item.courseId, batchId: item.batchId, key: item.id })));
    setCourseId('');
    setBatchId('');
    setError('');
  };

  const closeScope = () => {
    if (saving) return;
    setEditingSource(null);
    setDraft([]);
    setCourseId('');
    setBatchId('');
    setError('');
  };

  const addPair = () => {
    if (!courseId || !batchId) {
      setError('Choose both a Course and Batch.');
      return;
    }
    if (draft.some((item) => item.courseId === courseId && item.batchId === batchId)) {
      setError('This Course and Batch pair is already selected.');
      return;
    }
    setDraft((current) => [
      ...current,
      { courseId, batchId, key: `${courseId}:${batchId}` },
    ]);
    setCourseId('');
    setBatchId('');
    setError('');
  };

  const save = async () => {
    if (!editingSource) return;
    setSaving(true);
    setError('');
    try {
      await educationKnowledgeApi.setSourceScopes(
        editingSource.id,
        agentId,
        draft.map(({ courseId: selectedCourseId, batchId: selectedBatchId }) => ({
          courseId: selectedCourseId,
          batchId: selectedBatchId,
        })),
      );
      scopes.reload();
      pushToast(
        draft.length
          ? 'Education knowledge access scope saved'
          : 'Source is now unavailable to Education students',
      );
      setEditingSource(null);
      setDraft([]);
      setCourseId('');
      setBatchId('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save Education knowledge scope.');
    } finally {
      setSaving(false);
    }
  };

  const scopeLabel = (scope: EducationKnowledgeScope | ScopeDraft) => {
    const course = courses.data?.find((item) => item.id === scope.courseId);
    const batch = batches.data?.find((item) => item.id === scope.batchId);
    return `${course?.code ?? 'Course'} · ${batch?.code ?? 'Batch'}`;
  };

  return <>
    <Card className="education-knowledge-scope-card">
      <div className="education-knowledge-scope-card__heading">
        <span><ShieldCheck /></span>
        <div>
          <h3>Education access scope</h3>
          <p>Only sources assigned to the student's authorized Course and Batch can be retrieved.</p>
        </div>
      </div>
      <div className="education-knowledge-scope-card__notice">
        <strong>Fail closed:</strong> unscoped knowledge is never available to Education students.
      </div>
      {scopes.loading || courses.loading || batches.loading ? <div className="table-loading">Loading Education scopes…</div> : sources.length ? <div className="education-knowledge-scope-list">
        {sources.map((source) => {
          const bindings = scopes.data?.[source.id] ?? [];
          return <div className="education-knowledge-scope-row" key={source.id}>
            <div className="education-knowledge-scope-row__source">
              <strong>{source.name}</strong>
              <small>{source.kind} · {source.chunks} chunks</small>
            </div>
            <div className="education-knowledge-scope-row__bindings">
              {bindings.length ? bindings.map((scope) => <Badge key={scope.id} tone="purple">{scopeLabel(scope)}</Badge>) : <Badge tone="warning">Unscoped · blocked</Badge>}
            </div>
            <Button variant="secondary" size="sm" onClick={() => openScope(source)}>Manage scope</Button>
          </div>;
        })}
      </div> : <EmptyState icon={BookOpen} title="No knowledge to scope" description="Add a knowledge source first, then assign it to an Education Course and Batch." />}
    </Card>

    <Modal
      open={Boolean(editingSource)}
      onClose={closeScope}
      title={editingSource ? `Education scope · ${editingSource.name}` : 'Education scope'}
      description="A source may be shared with more than one Course and Batch. Leaving the list empty blocks it from Education retrieval."
      size="md"
      footer={<>
        <Button variant="secondary" disabled={saving} onClick={closeScope}>Cancel</Button>
        <Button icon={ShieldCheck} disabled={saving} onClick={() => void save()}>{saving ? 'Saving…' : 'Save scope'}</Button>
      </>}
    >
      <div className="education-knowledge-scope-editor">
        <div className="education-knowledge-scope-editor__picker">
          <Field label="Course" htmlFor="education-knowledge-course">
            <select
              id="education-knowledge-course"
              value={courseId}
              onChange={(event) => { setCourseId(event.target.value); setBatchId(''); setError(''); }}
            >
              <option value="">Choose Course</option>
              {(courses.data ?? []).map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}
            </select>
          </Field>
          <Field label="Batch" htmlFor="education-knowledge-batch">
            <select
              id="education-knowledge-batch"
              value={batchId}
              disabled={!courseId}
              onChange={(event) => { setBatchId(event.target.value); setError(''); }}
            >
              <option value="">Choose Batch</option>
              {availableBatches.map((batch) => <option value={batch.id} key={batch.id}>{batch.code} · {batch.name}</option>)}
            </select>
          </Field>
          <Button variant="secondary" icon={Plus} onClick={addPair}>Add pair</Button>
        </div>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <div className="education-knowledge-scope-editor__selected">
          {draft.length ? draft.map((scope) => <div key={scope.key}>
            <span>{scopeLabel(scope)}</span>
            <button
              type="button"
              aria-label={`Remove ${scopeLabel(scope)}`}
              onClick={() => setDraft((current) => current.filter((item) => item.key !== scope.key))}
            ><Trash2 /></button>
          </div>) : <p>No Course/Batch pair selected. This source will be blocked from Education retrieval.</p>}
        </div>
      </div>
    </Modal>
  </>;
}
