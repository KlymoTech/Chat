import { describe, expect, it } from 'vitest';
import type { EducationEnrollment } from '@/lib/education-enrollment-api';
import { courseDuration, enrollmentHasAccess, uniqueStudents } from './educationPresentation';

const today = new Date('2026-10-09T12:30:00Z');
const active = { studentId: 'one', status: 'active', startsOn: '2026-10-09', endsOn: '2026-10-09' } as EducationEnrollment;

describe('Education display calculations use actual records', () => {
  it('treats both validity boundaries as inclusive UTC dates', () => {
    expect(enrollmentHasAccess(active, today)).toBe(true);
    expect(enrollmentHasAccess({ ...active, startsOn: '2026-10-10' }, today)).toBe(false);
    expect(enrollmentHasAccess({ ...active, endsOn: '2026-10-08' }, today)).toBe(false);
    expect(enrollmentHasAccess({ ...active, startsOn: null, endsOn: null }, today)).toBe(true);
  });
  it.each(['pending', 'suspended', 'expired', 'revoked', 'graduated'] as const)('never counts %s as a valid enrollment', (status) => {
    expect(enrollmentHasAccess({ ...active, status }, today)).toBe(false);
  });
  it('counts people rather than counting every enrollment as a different student', () => {
    expect(uniqueStudents([active, { ...active, id: 'second-course' }, { ...active, studentId: 'two' }])).toBe(2);
    expect(uniqueStudents([])).toBe(0);
  });
  it('shows inclusive duration and handles open or invalid dates without invented numbers', () => {
    expect(courseDuration('2026-10-09', '2026-10-09')).toBe('1 day');
    expect(courseDuration('2026-10-09', '2026-10-15')).toBe('7 days');
    expect(courseDuration(null, '2026-10-15')).toBe('Open dates');
    expect(courseDuration('invalid', '2026-10-15')).toBe('Dates unavailable');
    expect(courseDuration('2026-10-15', '2026-10-09')).toBe('Dates unavailable');
  });
});
