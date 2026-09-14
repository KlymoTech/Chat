import { getWidgetLocale } from '@/lib/widget-localization';
import type { Agent, WhatsAppMessageSettings } from '@/types';

export function whatsappMessageSettings(agent: Agent): WhatsAppMessageSettings {
  const locale = getWidgetLocale(agent.language);
  const heading = agent.language === 'English' ? `Hi! Welcome to ${agent.name}.` : `${agent.name}\n${locale.welcomeTitle}`;
  return {
    welcomeEnabled: agent.appearance.whatsapp?.welcomeEnabled ?? true,
    welcomeMessage: agent.appearance.whatsapp?.welcomeMessage ?? `${heading}\n\n${agent.appearance.welcomeMessage || locale.welcomeMessage}`,
    replyTemplate: agent.appearance.whatsapp?.replyTemplate ?? '{message}',
  };
}

export function whatsappTemplateError(value: string): string | undefined {
  if (value.length > 1500) return 'Use at most 1,500 characters.';
  if (value.split('{message}').length !== 2) return 'Include {message} exactly once for the bot’s answer.';
  if (/[{}]/.test(value.replaceAll('{message}', '').replaceAll('{bot_name}', ''))) return 'Use only {message} and {bot_name} placeholders.';
}

export function validWhatsAppSettings(settings?: WhatsAppMessageSettings | null): boolean {
  if (!settings) return true;
  return !whatsappTemplateError(settings.replyTemplate)
    && (settings.welcomeMessage === null || (settings.welcomeMessage.length <= 4096 && (!settings.welcomeEnabled || Boolean(settings.welcomeMessage.trim()))));
}

export function formatWhatsAppReply(agent: Agent, message: string): string {
  const body = message.replace(/\*\*(.+?)\*\*/g, '*$1*')
    .replace(/^#{1,6}\s+(.+)$/gm, '*$1*')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '$1: $2')
    .replace(/```[a-zA-Z][\w+-]*\n/g, '```\n');
  return whatsappMessageSettings(agent).replyTemplate.replace(/\{(message|bot_name)\}/g, (_, key: string) => key === 'message' ? body : agent.name).trim();
}

export function whatsappChatUrl(number?: string | null): string | undefined {
  const digits = (number ?? '').replace(/\D/g, '');
  return /^[1-9]\d{6,14}$/.test(digits) ? `https://wa.me/${digits}` : undefined;
}
