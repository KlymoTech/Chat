import { readStorage, writeStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export type CourseStatus = 'active' | 'archived';

export interface EducationCourse {
  id: string;
  tenantId: string;
  workspaceId: string;
  code: string;
  name: string;
  description: string;
  status: CourseStatus;
  createdAt: string;
  updatedAt: string;
}

export interface CourseCreateInput {
  code: string;
  name: string;
  description?: string;
}

export interface CoursePatchInput {
  code?: string;
  name?: string;
  description?: string;
  status?: CourseStatus;
}

export interface CourseFilters {
  status?: CourseStatus;
  search?: string;
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const DEMO_MODE = (import.meta.env.VITE_DEMO_MODE as string | undefined) !== 'false';
const SESSION_KEY = 'northstar.session';
const COURSES_KEY = 'northstar.education.courses';

export class EducationApiError extends Error {
  constructor(message: string, readonly status: number, readonly detail?: unknown) {
    super(message);
    this.name = 'EducationApiError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

function currentWorkspaceId(): string {
  return activeWorkspaceId() ?? 'workspace-demo';
}

function localCourses(): EducationCourse[] {
  return readStorage<EducationCourse[]>(COURSES_KEY, []);
}

function persistCourses(courses: EducationCourse[]): void {
  writeStorage(COURSES_KEY, courses);
}

function normalizeCode(value: string): string {
  return value.trim().toUpperCase();
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { detail?: unknown; error?: { message?: unknown } };
    if (typeof candidate.detail === 'string') return candidate.detail;
    if (candidate.error && typeof candidate.error.message === 'string') return candidate.error.message;
  }
  return `Education request failed (${status})`;
}

async function remote<T>(
  path: string,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  body?: unknown,
): Promise<T> {
  const token = bearer();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    method,
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as unknown;
    throw new EducationApiError(errorMessage(payload, response.status), response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function withFallback<T>(remoteCall: () => Promise<T>, fallback: () => Promise<T>): Promise<T> {
  if (!DEMO_MODE) return remoteCall();
  try {
    return await remoteCall();
  } catch (error) {
    if (error instanceof EducationApiError && [400, 401, 403, 409, 422].includes(error.status)) throw error;
    return fallback();
  }
}

function localList(filters: CourseFilters = {}): EducationCourse[] {
  const workspaceId = currentWorkspaceId();
  const search = filters.search?.trim().toLowerCase() ?? '';
  return localCourses()
    .filter((course) => course.workspaceId === workspaceId)
    .filter((course) => !filters.status || course.status === filters.status)
    .filter((course) => {
      if (!search) return true;
      return `${course.code} ${course.name} ${course.description}`.toLowerCase().includes(search);
    })
    .sort((left, right) => left.name.localeCompare(right.name) || left.code.localeCompare(right.code));
}

function localCreate(input: CourseCreateInput): EducationCourse {
  const courses = localCourses();
  const workspaceId = currentWorkspaceId();
  const code = normalizeCode(input.code);
  if (courses.some((course) => course.workspaceId === workspaceId && course.code === code)) {
    throw new EducationApiError('A course with this code already exists in this workspace', 409);
  }
  const now = new Date().toISOString();
  const course: EducationCourse = {
    id: `course-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
    tenantId: 'tenant-demo',
    workspaceId,
    code,
    name: input.name.trim(),
    description: input.description?.trim() ?? '',
    status: 'active',
    createdAt: now,
    updatedAt: now,
  };
  courses.push(course);
  persistCourses(courses);
  return course;
}

function localUpdate(courseId: string, patch: CoursePatchInput): EducationCourse {
  const courses = localCourses();
  const workspaceId = currentWorkspaceId();
  const index = courses.findIndex((course) => course.id === courseId && course.workspaceId === workspaceId);
  if (index < 0) throw new EducationApiError('Course not found', 404);
  const current = courses[index]!;
  const nextCode = patch.code === undefined ? current.code : normalizeCode(patch.code);
  if (courses.some((course, courseIndex) => (
    courseIndex !== index && course.workspaceId === workspaceId && course.code === nextCode
  ))) {
    throw new EducationApiError('A course with this code already exists in this workspace', 409);
  }
  const updated: EducationCourse = {
    ...current,
    ...patch,
    code: nextCode,
    name: patch.name === undefined ? current.name : patch.name.trim(),
    description: patch.description === undefined ? current.description : patch.description.trim(),
    updatedAt: new Date().toISOString(),
  };
  courses[index] = updated;
  persistCourses(courses);
  return updated;
}

export const educationApi = {
  courses: {
    list(filters: CourseFilters = {}): Promise<EducationCourse[]> {
      const params = new URLSearchParams();
      if (filters.status) params.set('status', filters.status);
      if (filters.search?.trim()) params.set('search', filters.search.trim());
      const suffix = params.size ? `?${params.toString()}` : '';
      return withFallback(
        () => remote<EducationCourse[]>(`/education/courses${suffix}`, 'GET'),
        async () => localList(filters),
      );
    },
    get(courseId: string): Promise<EducationCourse> {
      return withFallback(
        () => remote<EducationCourse>(`/education/courses/${courseId}`, 'GET'),
        async () => {
          const course = localList().find((item) => item.id === courseId);
          if (!course) throw new EducationApiError('Course not found', 404);
          return course;
        },
      );
    },
    create(input: CourseCreateInput): Promise<EducationCourse> {
      return withFallback(
        () => remote<EducationCourse>('/education/courses', 'POST', input),
        async () => localCreate(input),
      );
    },
    update(courseId: string, patch: CoursePatchInput): Promise<EducationCourse> {
      return withFallback(
        () => remote<EducationCourse>(`/education/courses/${courseId}`, 'PATCH', patch),
        async () => localUpdate(courseId, patch),
      );
    },
    archive(courseId: string): Promise<void> {
      return withFallback(
        () => remote<void>(`/education/courses/${courseId}`, 'DELETE'),
        async () => { localUpdate(courseId, { status: 'archived' }); },
      );
    },
  },
};
