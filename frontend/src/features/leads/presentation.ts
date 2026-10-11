import type { Lead } from '@/types';
import type { FollowUp, LeadWorkspace } from './leadWorkspaceApi';

export function displayName(lead: Lead): string { return lead.name || lead.email || lead.phone || 'Anonymous visitor'; }
export function initials(value: string): string { return value.trim().split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase() || '?'; }
export function label(value: string): string { return value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase()); }
export function leadSource(lead: Lead): string {
  const source = lead.fields?.sourceChannel;
  return typeof source === 'string' ? source : 'unknown';
}
export function sourceLabel(source: string): string {
  return ({ widget: 'Website', website: 'Website', whatsapp: 'WhatsApp', telegram: 'Telegram', api: 'API', unknown: 'Not recorded' } as Record<string, string>)[source] ?? label(source);
}
export function stringField(lead: Lead, key: string): string {
  const value = lead.fields?.[key]; return typeof value === 'string' ? value : '';
}
export function capturedAt(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.valueOf())) return 'Not recorded';
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return `Today, ${date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
}

// Export a real calendar reminder, not an outbound email or WhatsApp promise.
export function calendarText(record: FollowUp): string {
  const escape = (value: string) => value.replace(/\\/g, '\\\\').replace(/\r\n|\r|\n/g, '\\n').replace(/;/g, '\\;').replace(/,/g, '\\,');
  const utc = (value: string) => new Date(value).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Northstar//Lead follow-up//EN', 'CALSCALE:GREGORIAN', 'BEGIN:VEVENT',
    `UID:${escape(record.id)}@northstar.local`, `DTSTAMP:${utc(record.createdAt)}`, `DTSTART:${utc(record.dueAt)}`,
    `DURATION:PT30M`, `SUMMARY:${escape(record.title)}`, `DESCRIPTION:${escape(`${label(record.kind)} follow-up. Assigned to ${record.assigneeName}.\n${record.notes}`)}`];
  if (record.reminderMinutes !== null) lines.push('BEGIN:VALARM', `TRIGGER:-PT${record.reminderMinutes}M`, 'ACTION:DISPLAY', `DESCRIPTION:${escape(record.title)}`, 'END:VALARM');
  lines.push('END:VEVENT', 'END:VCALENDAR');
  // RFC 5545 folding counts UTF-8 bytes, not JavaScript UTF-16 code units.
  return lines.map((line) => {
    let current = '', size = 0; const folded: string[] = [];
    for (const character of line) {
      const bytes = new TextEncoder().encode(character).length;
      if (size + bytes > 74) { folded.push(current); current = ' '; size = 1; }
      current += character; size += bytes;
    }
    return [...folded, current].join('\r\n');
  }).join('\r\n') + '\r\n';
}
export function downloadCalendar(record: FollowUp): void {
  const url = URL.createObjectURL(new Blob([calendarText(record)], { type: 'text/calendar;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'lead-follow-up.ics'; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** An optimistic mutation must not mask an equally new or newer server snapshot. */
export function currentLeadWorkspace(id: string | null, loaded: LeadWorkspace | null, pending: LeadWorkspace | null): LeadWorkspace | null {
  const current = loaded?.lead.id === id ? loaded : null;
  const optimistic = pending?.lead.id === id ? pending : null;
  if (!current) return optimistic;
  if (!optimistic) return current;
  return optimistic.version > current.version || (optimistic.version === current.version && Date.parse(optimistic.lead.updatedAt) > Date.parse(current.lead.updatedAt)) ? optimistic : current;
}
