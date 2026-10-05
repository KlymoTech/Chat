import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';
import type { EducationBatch, EducationCourse } from '@/lib/education-api';
import type { EducationStudent } from '@/lib/education-student-api';
import type { Agent } from '@/types';

export type EnrollmentStatus = 'pending' | 'active' | 'suspended' | 'expired' | 'revoked' | 'graduated';

export interface EducationEnrollment {
  id: string;
  tenantId: string;
  workspaceId: string;
  studentId: string;
  courseId: string;
  curriculumId?: string | null;
  batchId: string;
  agentId: string;
  allPapers?: boolean;
  paperIds?: string[];
  authorizationRevision?: number;
  startsOn: string | null;
  endsOn: string | null;
  status: EnrollmentStatus;
  createdAt: string;
  updatedAt: string;
}

export interface EnrollmentCreateInput {
  studentId: string;
  courseId: string;
  batchId: string;
  agentId?: string;
  curriculumId?: string | null;
  allPapers?: boolean;
  paperIds?: string[];
  startsOn?: string | null;
  endsOn?: string | null;
  status?: EnrollmentStatus;
}

export interface EnrollmentPatchInput {
  courseId?: string;
  batchId?: string;
  agentId?: string;
  curriculumId?: string | null;
  allPapers?: boolean;
  paperIds?: string[];
  startsOn?: string | null;
  endsOn?: string | null;
  status?: EnrollmentStatus;
}

export interface BulkEnrollmentAssignmentInput {
  courseId: string;
  batchId: string;
  curriculumId?: string | null;
  allPapers?: boolean;
  paperIds?: string[];
  startsOn?: string | null;
  endsOn?: string | null;
}

export interface BulkEnrollmentCreateInput {
  studentId: string;
  agentId: string;
  assignments: BulkEnrollmentAssignmentInput[];
  status?: 'pending' | 'active';
}

export interface EnrollmentFilters {
  status?: EnrollmentStatus;
  studentId?: string;
  courseId?: string;
  batchId?: string;
  agentId?: string;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) === 'true';
const SESSION_KEY = 'northstar.session';
const ENROLLMENTS_KEY = 'northstar.education.enrollments';
const STUDENTS_KEY = 'northstar.education.students';
const COURSES_KEY = 'northstar.education.courses';
const BATCHES_KEY = 'northstar.education.batches';
const AGENTS_KEY = 'northstar.agents';

const nonTerminalStatuses = new Set<EnrollmentStatus>(['pending', 'active', 'suspended']);
const allowedTransitions: Record<EnrollmentStatus, ReadonlySet<EnrollmentStatus>> = {
  pending: new Set(['pending', 'active', 'suspended', 'expired', 'revoked']),
  active: new Set(['active', 'suspended', 'expired', 'revoked', 'graduated']),
  suspended: new Set(['suspended', 'active', 'expired', 'revoked', 'graduated']),
  expired: new Set(['expired', 'active', 'revoked', 'graduated']),
  revoked: new Set(['revoked', 'pending']),
  graduated: new Set(['graduated']),
};

export class EducationEnrollmentApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'EducationEnrollmentApiError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

function workspaceId(): string {
  return activeWorkspaceId() ?? 'workspace-demo';
}

function storedEnrollments(): EducationEnrollment[] {
  return readStorage<Partial<EducationEnrollment>[]>(ENROLLMENTS_KEY, []).map((item) => ({
    ...item,
    curriculumId: item.curriculumId ?? null,
    allPapers: item.allPapers ?? true,
    paperIds: item.paperIds ?? [],
    authorizationRevision: item.authorizationRevision ?? 1,
  } as EducationEnrollment));
}

function persistEnrollments(enrollments: EducationEnrollment[]): void {
  writeStorage(ENROLLMENTS_KEY, enrollments);
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof candidate.detail === 'string') return candidate.detail;
    if (candidate.error && typeof candidate.error.message === 'string') return candidate.error.message;
  }
  return `Education enrollment request failed (${status})`;
}

async function remote<T>(
  path: string,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const token = bearer();
  const currentWorkspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(currentWorkspaceId ? { 'X-Workspace-ID': currentWorkspaceId } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as unknown;
    throw new EducationEnrollmentApiError(errorMessage(payload, response.status), response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function withFallback<T>(remoteCall: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
  if (!DEMO_MODE) return remoteCall();
  try {
    return await remoteCall();
  } catch (error) {
    if (error instanceof EducationEnrollmentApiError && [400, 401, 403, 409, 422].includes(error.status)) {
      throw error;
    }
    return fallback();
  }
}

function validateDateRange(startsOn: string | null, endsOn: string | null): void {
  if (startsOn && endsOn && endsOn < startsOn) {
    throw new EducationEnrollmentApiError('Enrollment end date cannot be before start date', 422);
  }
}

function localReferences(
  studentId: string,
  courseId: string,
  batchId: string,
  agentId: string,
  requireActive: boolean,
): void {
  const currentWorkspaceId = workspaceId();
  const student = readStorage<EducationStudent[]>(STUDENTS_KEY, []).find(
    (item) => item.id === studentId && item.workspaceId === currentWorkspaceId,
  );
  if (!student) throw new EducationEnrollmentApiError('Student not found', 404);
  const course = readStorage<EducationCourse[]>(COURSES_KEY, []).find(
    (item) => item.id === courseId && item.workspaceId === currentWorkspaceId,
  );
  if (!course) throw new EducationEnrollmentApiError('Course not found', 404);
  const batch = readStorage<EducationBatch[]>(BATCHES_KEY, []).find(
    (item) => item.id === batchId && item.workspaceId === currentWorkspaceId,
  );
  if (!batch) throw new EducationEnrollmentApiError('Batch not found', 404);
  if (batch.courseId !== course.id) {
    throw new EducationEnrollmentApiError('Batch does not belong to the selected Course', 422);
  }
  const agent = readStorage<Agent[]>(AGENTS_KEY, []).find(
    (item) => item.id === agentId && (!item.workspaceId || item.workspaceId === currentWorkspaceId),
  );
  if (!agent) throw new EducationEnrollmentApiError('Agent not found', 404);
  if (agent.purpose !== 'education') {
    throw new EducationEnrollmentApiError('Enrollment Agent must have Education purpose', 422);
  }
  if (requireActive) {
    if (student.status !== 'active') {
      throw new EducationEnrollmentApiError('Reactivate the Student before assigning enrollment access', 409);
    }
    if (course.status !== 'active') {
      throw new EducationEnrollmentApiError('Reactivate the Course before assigning enrollment access', 409);
    }
    if (batch.status !== 'active') {
      throw new EducationEnrollmentApiError('Reactivate the Batch before assigning enrollment access', 409);
    }
  }
}

function localList(filters: EnrollmentFilters = {}): EducationEnrollment[] {
  const currentWorkspaceId = workspaceId();
  return storedEnrollments()
    .filter((item) => item.workspaceId === currentWorkspaceId)
    .filter((item) => !filters.status || item.status === filters.status)
    .filter((item) => !filters.studentId || item.studentId === filters.studentId)
    .filter((item) => !filters.courseId || item.courseId === filters.courseId)
    .filter((item) => !filters.batchId || item.batchId === filters.batchId)
    .filter((item) => !filters.agentId || item.agentId === filters.agentId)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
}

function localCreate(input: EnrollmentCreateInput): EducationEnrollment {
  const currentWorkspaceId = workspaceId();
  const enrollments = storedEnrollments();
  const status = input.status ?? 'pending';
  const startsOn = input.startsOn ?? null;
  const endsOn = input.endsOn ?? null;
  validateDateRange(startsOn, endsOn);
  const course = readStorage<EducationCourse[]>(COURSES_KEY, []).find(
    (item) => item.id === input.courseId && item.workspaceId === currentWorkspaceId,
  );
  if (course?.simplifiedWorkflow && input.agentId && input.agentId !== course.assignedAgentId) {
    throw new EducationEnrollmentApiError('Simplified Course enrollments inherit the Course Agent', 422);
  }
  const agentId = course?.simplifiedWorkflow ? course.assignedAgentId ?? undefined : input.agentId;
  if (!agentId) throw new EducationEnrollmentApiError('Select an Education Agent for this enrollment', 422);
  localReferences(input.studentId, input.courseId, input.batchId, agentId, true);
  if (enrollments.some((item) => (
    item.workspaceId === currentWorkspaceId
    && item.studentId === input.studentId
    && item.courseId === input.courseId
    && item.batchId === input.batchId
    && item.agentId === agentId
  ))) {
    throw new EducationEnrollmentApiError(
      'This Student already has an Enrollment for the selected Course, Batch, and Agent',
      409,
    );
  }
  const now = new Date().toISOString();
  const enrollment: EducationEnrollment = {
    id: `enrollment-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
    tenantId: 'tenant-demo',
    workspaceId: currentWorkspaceId,
    studentId: input.studentId,
    courseId: input.courseId,
    curriculumId: input.curriculumId ?? null,
    batchId: input.batchId,
    agentId,
    allPapers: input.allPapers ?? true,
    paperIds: input.paperIds ?? [],
    authorizationRevision: 1,
    startsOn,
    endsOn,
    status,
    createdAt: now,
    updatedAt: now,
  };
  enrollments.push(enrollment);
  persistEnrollments(enrollments);
  return enrollment;
}

function localBulkCreate(input: BulkEnrollmentCreateInput): EducationEnrollment[] {
  if (!input.assignments.length) {
    throw new EducationEnrollmentApiError('Select at least one Course and Batch.', 422);
  }
  const currentWorkspaceId = workspaceId();
  const enrollments = storedEnrollments();
  const keys = new Set<string>();
  const courses = readStorage<EducationCourse[]>(COURSES_KEY, []);
  const now = new Date().toISOString();
  const status = input.status ?? 'pending';
  const created: EducationEnrollment[] = [];

  // Validate every assignment before persisting any of them, matching the
  // transactional server endpoint used outside demo mode.
  for (const assignment of input.assignments) {
    const key = `${assignment.courseId}:${assignment.batchId}`;
    if (keys.has(key)) throw new EducationEnrollmentApiError('Course and Batch selections must be unique.', 422);
    keys.add(key);
    const course = courses.find((item) => item.id === assignment.courseId && item.workspaceId === currentWorkspaceId);
    if (!course) throw new EducationEnrollmentApiError('Course not found', 404);
    const agentId = course.simplifiedWorkflow ? course.assignedAgentId : input.agentId;
    if (!agentId) throw new EducationEnrollmentApiError('Simplified Course needs an assigned Education Agent before enrollment', 409);
    if (course.simplifiedWorkflow && agentId !== input.agentId) {
      throw new EducationEnrollmentApiError('Every simplified Course in a bulk assignment must use the selected Education Agent', 422);
    }
    const startsOn = assignment.startsOn ?? null;
    const endsOn = assignment.endsOn ?? null;
    validateDateRange(startsOn, endsOn);
    localReferences(input.studentId, assignment.courseId, assignment.batchId, agentId, true);
    if (enrollments.some((item) => item.workspaceId === currentWorkspaceId && item.studentId === input.studentId && item.courseId === assignment.courseId && item.batchId === assignment.batchId && item.agentId === agentId)) {
      throw new EducationEnrollmentApiError('One or more selected Course/Batch assignments already exist for this Student and Education Agent', 409);
    }
    created.push({
      id: `enrollment-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
      tenantId: 'tenant-demo', workspaceId: currentWorkspaceId, studentId: input.studentId,
      courseId: assignment.courseId, curriculumId: assignment.curriculumId ?? null,
      batchId: assignment.batchId, agentId, allPapers: assignment.allPapers ?? true,
      paperIds: assignment.paperIds ?? [], authorizationRevision: 1,
      startsOn, endsOn, status, createdAt: now, updatedAt: now,
    });
  }
  persistEnrollments([...enrollments, ...created]);
  return created;
}

function localUpdate(enrollmentId: string, patch: EnrollmentPatchInput): EducationEnrollment {
  const enrollments = storedEnrollments();
  const currentWorkspaceId = workspaceId();
  const index = enrollments.findIndex(
    (item) => item.id === enrollmentId && item.workspaceId === currentWorkspaceId,
  );
  if (index < 0) throw new EducationEnrollmentApiError('Enrollment not found', 404);
  const current = enrollments[index]!;
  const nextStatus = patch.status ?? current.status;
  if (!allowedTransitions[current.status].has(nextStatus)) {
    throw new EducationEnrollmentApiError(
      `Enrollment cannot move from ${current.status} to ${nextStatus}`,
      409,
    );
  }
  const assignmentChanged = (
    (patch.courseId !== undefined && patch.courseId !== current.courseId)
    || (patch.batchId !== undefined && patch.batchId !== current.batchId)
    || (patch.agentId !== undefined && patch.agentId !== current.agentId)
  );
  if (assignmentChanged && !['pending', 'suspended'].includes(current.status)) {
    throw new EducationEnrollmentApiError(
      'Suspend the Enrollment before changing Course, Batch, or Agent assignment',
      409,
    );
  }
  const courseId = patch.courseId ?? current.courseId;
  const batchId = patch.batchId ?? current.batchId;
  const agentId = patch.agentId ?? current.agentId;
  const curriculumId = patch.curriculumId === undefined ? current.curriculumId : patch.curriculumId;
  const allPapers = patch.allPapers ?? current.allPapers;
  const paperIds = patch.paperIds ?? current.paperIds;
  const startsOn = patch.startsOn === undefined ? current.startsOn : patch.startsOn;
  const endsOn = patch.endsOn === undefined ? current.endsOn : patch.endsOn;
  validateDateRange(startsOn, endsOn);
  if (nonTerminalStatuses.has(nextStatus) || assignmentChanged) {
    localReferences(current.studentId, courseId, batchId, agentId, nonTerminalStatuses.has(nextStatus));
  }
  if (enrollments.some((item, itemIndex) => (
    itemIndex !== index
    && item.workspaceId === currentWorkspaceId
    && item.studentId === current.studentId
    && item.courseId === courseId
    && item.batchId === batchId
    && item.agentId === agentId
  ))) {
    throw new EducationEnrollmentApiError(
      'This Student already has an Enrollment for the selected Course, Batch, and Agent',
      409,
    );
  }
  const updated: EducationEnrollment = {
    ...current,
    ...patch,
    courseId,
    curriculumId,
    batchId,
    agentId,
    allPapers,
    paperIds,
    startsOn,
    endsOn,
    status: nextStatus,
    authorizationRevision: (current.authorizationRevision ?? 1) + 1,
    updatedAt: new Date().toISOString(),
  };
  enrollments[index] = updated;
  persistEnrollments(enrollments);
  return updated;
}

export const educationEnrollmentApi = {
  list(filters: EnrollmentFilters = {}): Promise<EducationEnrollment[]> {
    const params = new URLSearchParams();
    if (filters.status) params.set('status', filters.status);
    if (filters.studentId) params.set('student_id', filters.studentId);
    if (filters.courseId) params.set('course_id', filters.courseId);
    if (filters.batchId) params.set('batch_id', filters.batchId);
    if (filters.agentId) params.set('agent_id', filters.agentId);
    const suffix = params.size ? `?${params.toString()}` : '';
    return withFallback(
      () => remote<EducationEnrollment[]>(`/education/enrollments${suffix}`, 'GET'),
      async () => localList(filters),
    );
  },
  get(enrollmentId: string): Promise<EducationEnrollment> {
    return withFallback(
      () => remote<EducationEnrollment>(`/education/enrollments/${enrollmentId}`, 'GET'),
      async () => {
        const enrollment = localList().find((item) => item.id === enrollmentId);
        if (!enrollment) throw new EducationEnrollmentApiError('Enrollment not found', 404);
        return enrollment;
      },
    );
  },
  create(input: EnrollmentCreateInput): Promise<EducationEnrollment> {
    return withFallback(
      () => remote<EducationEnrollment>('/education/enrollments', 'POST', input),
      async () => localCreate(input),
    );
  },
  bulkCreate(input: BulkEnrollmentCreateInput): Promise<EducationEnrollment[]> {
    return withFallback(
      () => remote<EducationEnrollment[]>('/education/enrollments/bulk', 'POST', input),
      async () => localBulkCreate(input),
    );
  },
  update(enrollmentId: string, patch: EnrollmentPatchInput): Promise<EducationEnrollment> {
    return withFallback(
      () => remote<EducationEnrollment>(`/education/enrollments/${enrollmentId}`, 'PATCH', patch),
      async () => localUpdate(enrollmentId, patch),
    );
  },
  revoke(enrollmentId: string): Promise<void> {
    return withFallback(
      () => remote<void>(`/education/enrollments/${enrollmentId}`, 'DELETE'),
      async () => {
        const enrollment = localList().find((item) => item.id === enrollmentId);
        if (!enrollment) throw new EducationEnrollmentApiError('Enrollment not found', 404);
        if (enrollment.status === 'graduated') {
          throw new EducationEnrollmentApiError('Graduated Enrollment history cannot be revoked', 409);
        }
        localUpdate(enrollmentId, { status: 'revoked' });
      },
    );
  },
};
