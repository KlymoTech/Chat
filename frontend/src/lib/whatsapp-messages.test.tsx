import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { WhatsAppText } from '@/components/whatsapp-message-editor';
import { demoAgents } from '@/lib/demo-data';
import { formatWhatsAppReply, validWhatsAppSettings, whatsappChatUrl, whatsappTemplateError } from './whatsapp-messages';

afterEach(cleanup);

describe('WhatsApp message formatting', () => {
  it('previews supported styles and keeps HTML as text', () => {
    const { container } = render(<WhatsAppText text={'*Welcome* _student_ ~old~ ```account\n123```\n- Topic\n> A quote\n<img src=x onerror=alert(1)>'} />);
    expect(screen.getByText('Welcome').tagName).toBe('STRONG');
    expect(screen.getByText('student').tagName).toBe('EM');
    expect(screen.getByText('old').tagName).toBe('S');
    expect(container.querySelector('code')?.textContent).toBe('account\n123');
    expect(screen.getByText('A quote')).toHaveClass('wa-text-quote');
    expect(container).toHaveTextContent('• Topic');
    expect(container.querySelector('img')).toBeNull();
    expect(container).toHaveTextContent('<img src=x onerror=alert(1)>');
  });

  it('matches outgoing structure without interpreting placeholders from an answer', () => {
    const agent = structuredClone(demoAgents[0]!);
    agent.name = 'CMA';
    agent.appearance.whatsapp = { welcomeEnabled: true, welcomeMessage: 'Welcome', replyTemplate: '*{bot_name}*\n\n{message}\n\n_Thank you_' };
    expect(formatWhatsAppReply(agent, '## Overview\n**Important**\n[Help](https://example.com)\nUse {bot_name}')).toBe('*CMA*\n\n*Overview*\n*Important*\nHelp: https://example.com\nUse {bot_name}\n\n_Thank you_');
    expect(whatsappTemplateError('{message} {email}')).toBeTruthy();
    expect(whatsappTemplateError('{message} {message}')).toBeTruthy();
    expect(validWhatsAppSettings({ ...agent.appearance.whatsapp, welcomeMessage: '  ' })).toBe(false);
    expect(validWhatsAppSettings({ ...agent.appearance.whatsapp, welcomeMessage: '', welcomeEnabled: false })).toBe(true);
    expect(whatsappChatUrl('+91 81470 24024')).toBe('https://wa.me/918147024024');
    expect(whatsappChatUrl(null)).toBeUndefined();
  });
});
