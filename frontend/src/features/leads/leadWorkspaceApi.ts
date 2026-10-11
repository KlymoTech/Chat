import { request } from '@/lib/api';
import type { Lead } from '@/types';

export interface LeadSummary { total: number; new: number; qualified: number; converted: number }
export interface Assignee { id: string; name: string; kind: 'person' | 'team'; role: string }
export interface LeadAssignment extends Assignee { note: string; assignedAt: string }
export type FollowUpKind = 'call' | 'email' | 'whatsapp' | 'meeting' | 'task';
export interface FollowUp {
  id: string; kind: FollowUpKind; title: string; dueAt: string; timezone: string;
  assigneeKind: 'person' | 'team'; assigneeId: string; assigneeName: string;
  notes: string; reminderMinutes: number | null; createdAt: string;
  status: 'scheduled' | 'completed' | 'cancelled'; deliveryMode: 'calendar';
}
export interface LeadWorkspace { lead: Lead; version: number; assignment: LeadAssignment | null; followUps: FollowUp[] }
export type FollowUpInput = Omit<FollowUp, 'assigneeName' | 'createdAt' | 'status' | 'deliveryMode'> & { version: number };
export interface NewLead { agentId: string; name: string; email?: string; phone?: string; consent: boolean; fields: Record<string, string> }
const path = (id: string) => `/leads/${encodeURIComponent(id)}`;

export const leadWorkspaceApi = {
  summary: () => request<LeadSummary>('/leads/summary'),
  detail: (id: string) => request<LeadWorkspace>(`${path(id)}/workspace`),
  options: (id: string) => request<Assignee[]>(`${path(id)}/assignment-options`),
  create: (value: NewLead) => request<Lead>('/leads', { method: 'POST', body: JSON.stringify(value) }),
  assign: (id: string, value: { version: number; kind: 'person' | 'team'; targetId: string; note: string }) =>
    request<LeadWorkspace>(`${path(id)}/assignment`, { method: 'PUT', body: JSON.stringify(value) }),
  schedule: (id: string, value: FollowUpInput) => request<LeadWorkspace>(`${path(id)}/follow-ups`, { method: 'POST', body: JSON.stringify(value) }),
  setFollowUpState: (id: string, followUpId: string, version: number, status: 'completed' | 'cancelled') =>
    request<LeadWorkspace>(`${path(id)}/follow-ups/${encodeURIComponent(followUpId)}`, { method: 'PATCH', body: JSON.stringify({ version, status }) }),
  stage: (id: string, status: string, note: string) => request<Lead>(`${path(id)}/stage`, { method: 'PUT', body: JSON.stringify({ status, note }) }),
};
