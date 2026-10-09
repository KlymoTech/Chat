import { describe, expect, it } from 'vitest';
import { calendarText, capturedAt, initials, leadSource } from './presentation';
import type { FollowUp } from './leadWorkspaceApi';
import { demoLeads } from '@/lib/demo-data';
const record: FollowUp = { id: 'follow-up-a', kind: 'call', title: 'Demo, pricing; next steps', dueAt: '2026-11-03T10:30:00+05:30', timezone: 'Asia/Kolkata', assigneeId: 'owner', assigneeKind: 'person', assigneeName: 'Owner', notes: 'Follow up\nBEGIN:ATTENDEE', reminderMinutes: 30, createdAt: '2026-10-09T11:00:00Z', status: 'scheduled', deliveryMode: 'calendar' };
describe('Calendar and lead presentation', () => {
  it('uses UTC, escaped text and an actual calendar alarm without outbound attendees', () => {
    const result = calendarText(record);
    expect(result).toContain('DTSTART:20261103T050000Z\r\n');
    expect(result).toContain('SUMMARY:Demo\\, pricing\\; next steps\r\n');
    expect(result).toContain('TRIGGER:-PT30M\r\nACTION:DISPLAY');
    expect(result).not.toContain('\r\nBEGIN:ATTENDEE');
    expect(result.match(/BEGIN:VEVENT/g)).toHaveLength(1);
  });
  it('folds Unicode at UTF-8 byte boundaries and omits alarms when none was requested', () => {
    const result = calendarText({ ...record, title: 'नमस्ते '.repeat(24), reminderMinutes: null });
    for (const line of result.split('\r\n')) expect(new TextEncoder().encode(line).length).toBeLessThanOrEqual(74);
    expect(result).not.toContain('VALARM');
    expect(result.replace(/\r\n /g, '')).toContain('नमस्ते '.repeat(24));
  });
  it('does not invent a source, date or name from missing values', () => {
    expect(leadSource({ ...demoLeads[0]!, fields: {} })).toBe('unknown');
    expect(capturedAt('invalid')).toBe('Not recorded');
    expect(initials('')).toBe('?');
  });
});
