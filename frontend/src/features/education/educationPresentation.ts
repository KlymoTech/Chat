import type { EducationEnrollment } from '@/lib/education-enrollment-api';

/** Enrollment status alone is not proof of current access. Dates are inclusive. */
export function enrollmentHasAccess(enrollment: EducationEnrollment, now = new Date()): boolean {
  const today = now.toISOString().slice(0, 10);
  return enrollment.status === 'active'
    && (!enrollment.startsOn || enrollment.startsOn <= today)
    && (!enrollment.endsOn || enrollment.endsOn >= today);
}
export function uniqueStudents(enrollments: EducationEnrollment[]): number {
  return new Set(enrollments.map((entry) => entry.studentId).filter(Boolean)).size;
}
export function courseDuration(startsOn: string | null, endsOn: string | null): string {
  if (!startsOn || !endsOn) return 'Open dates';
  const days = Math.round((Date.parse(endsOn) - Date.parse(startsOn)) / 86_400_000) + 1;
  return Number.isFinite(days) && days > 0 ? `${days} ${days === 1 ? 'day' : 'days'}` : 'Dates unavailable';
}
