export type LeadInput = {
  idempotencyKey: string;
  fullName: string;
  email: string;
  message: string;
  privacyAcknowledged: true;
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const mail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const hasControlCharacters = (text: string): boolean => /[\u0000-\u001f\u007f]/.test(text);
export function parseLeadInput(value: unknown): LeadInput | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.idempotencyKey !== "string" || !uuid.test(v.idempotencyKey)) return null;
  if (typeof v.fullName !== "string" || !v.fullName.trim() || v.fullName.trim().length > 160 || hasControlCharacters(v.fullName)) return null;
  if (typeof v.email !== "string" || v.email.trim().length > 254 || !mail.test(v.email.trim()) || hasControlCharacters(v.email)) return null;
  if (typeof v.message !== "string" || !v.message.trim() || v.message.trim().length > 4000 || hasControlCharacters(v.message)) return null;
  if (v.privacyAcknowledged !== true) return null;
  return {
    idempotencyKey: v.idempotencyKey,
    fullName: v.fullName.trim(), email: v.email.trim().toLowerCase(),
    message: v.message.trim(), privacyAcknowledged: true
  };
}
