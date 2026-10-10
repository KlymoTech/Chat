import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export type CRMWorkflowStageStatus = 'ready' | 'warning' | 'blocked';
export type CRMWorkflowJourneyStage =
  | 'local_lead'
  | 'awaiting_routing'
  | 'in_progress'
  | 'provider_acknowledged'
  | 'verifying'
  | 'verified'
  | 'attention_required'
  | 'dead_letter';

export interface CRMWorkflowReadinessStage {
  id: string;
  label: string;
  description: string;
  status: CRMWorkflowStageStatus;
  detail: string;
  actionLabel?: string | null;
  actionPath?: string | null;
}

export interface CRMWorkflowReadiness {
  ready: boolean;
  stages: CRMWorkflowReadinessStage[];
}

export interface CRMWorkflowCounts {
  resolvedConversations: number;
  localLeads: number;
  leadsWithoutDelivery: number;
  totalDeliveries: number;
  inFlightDeliveries: number;
  verifiedDeliveries: number;
  attentionDeliveries: number;
  openDeadLetters: number;
  byStatus: Record<string, number>;
}

export interface CRMWorkflowConnection {
  id: string;
  name: string;
  provider: string;
  environment: string;
  status: string;
  credentialsConfigured: boolean;
  mappingConfigured: boolean;
  mappingStatus?: string | null;
  mappingVersion?: number | null;
  enabledRouteCount: number;
  autoSyncNewLeads: boolean;
  autoSyncUpdates: boolean;
  ready: boolean;
  lastHealthAt?: string | null;
  lastSuccessAt?: string | null;
  lastFailureAt?: string | null;
  lastError?: string | null;
}

export interface CRMWorkflowDelivery {
  id: string;
  connectionId: string;
  connectionName: string;
  provider: string;
  operation: string;
  status: string;
  verificationStatus: string;
  externalRecordId?: string | null;
  attemptCount: number;
  verificationAttemptCount: number;
  acknowledgedAt?: string | null;
  verifiedAt?: string | null;
  nextRetryAt?: string | null;
  nextVerificationAt?: string | null;
  lastErrorCode?: string | null;
  lastErrorMessage?: string | null;
  verificationErrorCode?: string | null;
  verificationErrorMessage?: string | null;
  deadLetterOpen: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface CRMWorkflowJourney {
  leadId: string;
  conversationId?: string | null;
  conversationPublicId?: string | null;
  agentId: string;
  agentName: string;
  customerName?: string | null;
  email?: string | null;
  phone?: string | null;
  sourceChannel?: string | null;
  lifecycleStatus: string;
  qualificationStatus?: string | null;
  qualificationScore?: number | null;
  stage: CRMWorkflowJourneyStage;
  stageLabel: string;
  stageDetail: string;
  nextActionLabel?: string | null;
  nextActionPath?: string | null;
  delivery?: CRMWorkflowDelivery | null;
  createdAt: string;
  updatedAt: string;
}

export interface CRMWorkflow {
  generatedAt: string;
  workspaceId: string;
  readiness: CRMWorkflowReadiness;
  counts: CRMWorkflowCounts;
  connections: CRMWorkflowConnection[];
  recentJourneys: CRMWorkflowJourney[];
}

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

async function request<T>(path: string, options?: { method?: 'PUT' | 'POST'; body?: string }): Promise<T> {
  const accessToken = readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    ...(options?.method ? { method: options.method } : {}),
    ...(options?.body ? { body: options.body } : {}),
    headers: {
      Accept: 'application/json',
      ...(options?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {
      detail?: unknown;
      error?: { message?: string };
    } | null;
    const detail = payload?.detail;
    const message = payload?.error?.message
      ?? (typeof detail === 'string' ? detail : undefined)
      ?? `CRM workflow request failed (${response.status})`;
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const crmWorkflowApi = {
  get: (limit = 25) => request<CRMWorkflow>(`/crm/workflow?limit=${limit}`),
};

export type LeadScoreField = 'source_channel' | 'utm_source' | 'utm_medium' | 'utm_campaign';

export interface LeadScoreRule {
  field: LeadScoreField;
  equals: string;
  points: number;
}

export interface LeadScoringPolicy {
  version: number;
  enabled: boolean;
  base_points: number;
  review_threshold: number;
  rules: LeadScoreRule[];
}

export interface LeadScoreExplanation extends LeadScoreRule {
  matched: boolean;
}

export interface LeadScorePreview {
  lead_id: string;
  policy_version: number;
  eligible: boolean;
  ineligible_reason: string | null;
  current_score: number | null;
  proposed_score: number | null;
  review_threshold: number;
  recommendation: 'review' | 'below_threshold' | 'blocked' | 'disabled';
  qualification_status: string | null;
  rules: LeadScoreExplanation[];
}

export const leadScoringApi = {
  policy: () => request<LeadScoringPolicy>('/crm/workflow/scoring-policy'),
  savePolicy: (policy: LeadScoringPolicy) => request<LeadScoringPolicy>(
    '/crm/workflow/scoring-policy',
    {
      method: 'PUT',
      body: JSON.stringify({
        expected_version: policy.version,
        enabled: policy.enabled,
        base_points: policy.base_points,
        review_threshold: policy.review_threshold,
        rules: policy.rules,
      }),
    },
  ),
  preview: (leadId: string) => request<LeadScorePreview>(
    '/crm/workflow/leads/' + encodeURIComponent(leadId) + '/score-preview',
  ),
  apply: (leadId: string, preview: LeadScorePreview) => request<LeadScorePreview>(
    '/crm/workflow/leads/' + encodeURIComponent(leadId) + '/apply-score',
    {
      method: 'POST',
      body: JSON.stringify({
        expected_policy_version: preview.policy_version,
        expected_score: preview.current_score,
      }),
    },
  ),
};


export type LeadSegmentField =
  | 'source_channel' | 'utm_source' | 'utm_medium' | 'utm_campaign'
  | 'lifecycle_status' | 'qualification_status';
export type LeadSegmentPurpose = 'operations' | 'marketing';

export interface LeadSegmentCondition {
  field: LeadSegmentField;
  equals: string;
}
export interface LeadSegment {
  id: string;
  name: string;
  purpose: LeadSegmentPurpose;
  enabled: boolean;
  logic: 'all' | 'any';
  include: LeadSegmentCondition[];
  exclude: LeadSegmentCondition[];
}
export interface LeadSegmentRegister {
  version: number;
  segments: LeadSegment[];
}
export interface LeadSegmentPreview {
  segmentId: string;
  policyVersion: number;
  purpose: LeadSegmentPurpose;
  enabled: boolean;
  matchedLeads: number;
  blockedByEligibility: number;
  unknownInputLeads: number;
  examinedLeads: number;
  truncated: boolean;
  exactCount: boolean;
  evaluatedAt: string;
  note: string;
}

export const leadSegmentsApi = {
  list: () => request<LeadSegmentRegister>('/crm/workflow/segments'),
  save: (register: LeadSegmentRegister) => request<LeadSegmentRegister>(
    '/crm/workflow/segments',
    {
      method: 'PUT',
      body: JSON.stringify({
        expected_version: register.version,
        segments: register.segments,
      }),
    },
  ),
  preview: (segmentId: string) => request<LeadSegmentPreview>(
    '/crm/workflow/segments/' + encodeURIComponent(segmentId) + '/preview',
  ),
};


export interface InternalLeadAutomation {
  id: string;
  name: string;
  segment_id: string;
  enabled: boolean;
  action: 'notify_admins';
  max_per_run: number;
}

export interface InternalLeadAutomationRegister {
  version: number;
  automations: InternalLeadAutomation[];
}

export interface InternalLeadAutomationPreview {
  automationId: string;
  policyVersion: number;
  segmentVersion: number;
  eligibleLeads: number;
  eligibleFingerprint: string;
  alreadyQueued: number;
  remainingEligible: number;
  blockedByConsentOrStatus: number;
  unknownInputLeads: number;
  examinedLeads: number;
  truncated: boolean;
  maxPerRun: number;
  action: 'notify_admins';
  externalDelivery: false;
  note: string;
}

export interface InternalLeadAutomationRun {
  automationId: string;
  policyVersion: number;
  queuedReviews: number;
  previouslyQueued: number;
  noRecipients: number;
  remainingEligible: number;
  externalDelivery: false;
  note: string;
}

export const internalAutomationsApi = {
  list: () => request<InternalLeadAutomationRegister>('/crm/workflow/internal-automations'),
  save: (register: InternalLeadAutomationRegister) => request<InternalLeadAutomationRegister>(
    '/crm/workflow/internal-automations',
    {
      method: 'PUT',
      body: JSON.stringify({
        expected_version: register.version,
        automations: register.automations,
      }),
    },
  ),
  preview: (automationId: string) => request<InternalLeadAutomationPreview>(
    '/crm/workflow/internal-automations/' + encodeURIComponent(automationId) + '/preview',
  ),
  execute: (automationId: string, preview: InternalLeadAutomationPreview) => request<InternalLeadAutomationRun>(
    '/crm/workflow/internal-automations/' + encodeURIComponent(automationId) + '/execute',
    {
      method: 'POST',
      body: JSON.stringify({
        expected_policy_version: preview.policyVersion,
        expected_segment_version: preview.segmentVersion,
        expected_eligible_leads: preview.eligibleLeads,
        expected_eligible_fingerprint: preview.eligibleFingerprint,
      }),
    },
  ),
};

/** Marketing permission is independent of the existing processing-consent receipt. */
export interface LeadMarketingPreferences {
  leadId: string;
  marketingStatus: string;
  marketingAllowed: boolean;
  processingConsentPreserved: true;
  note: string;
}

export interface MarketingUnsubscribeLink {
  path: string;
  expiresIn: string;
  note: string;
}

export interface MarketingWithdrawalResult {
  status: 'withdrawn';
  changed: boolean;
  processingConsentPreserved: true;
}

export const marketingPreferencesApi = {
  get: (leadId: string) => request<LeadMarketingPreferences>(
    '/site-marketing/leads/' + encodeURIComponent(leadId) + '/preferences',
  ),
  withdraw: (leadId: string) => request<MarketingWithdrawalResult>(
    '/site-marketing/leads/' + encodeURIComponent(leadId) + '/withdraw', { method: 'POST' },
  ),
  createUnsubscribeLink: (leadId: string) => request<MarketingUnsubscribeLink>(
    '/site-marketing/leads/' + encodeURIComponent(leadId) + '/unsubscribe-link',
    { method: 'POST' },
  ),
  publicUrl: (path: string) => new URL(
    path,
    API_URL.startsWith('http://') || API_URL.startsWith('https://')
      ? API_URL
      : window.location.origin,
  ).toString(),
};
