import { afterEach, describe, expect, it, vi } from 'vitest';
import { passwordResetApi } from '@/lib/password-reset-api';

describe('passwordResetApi', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('normalizes email and requests a recovery link without credentials in storage', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ accepted: true }), {
      status: 202,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await passwordResetApi.request('  Owner@Example.COM  ');

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/password-reset/request', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
    }));
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ email: 'owner@example.com' });
  });

  it('submits the token and both password fields to the confirm endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ reset: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await passwordResetApi.confirm(
      'secure-reset-token-value',
      'Replacement-Password-2026!',
      'Replacement-Password-2026!',
    );

    expect(result).toEqual({ reset: true });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      token: 'secure-reset-token-value',
      password: 'Replacement-Password-2026!',
      confirmPassword: 'Replacement-Password-2026!',
    });
  });

  it('surfaces the backend reset error message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { message: 'Password reset link is invalid or expired' },
    }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    })));

    await expect(passwordResetApi.confirm(
      'expired-reset-token-value',
      'Replacement-Password-2026!',
      'Replacement-Password-2026!',
    )).rejects.toThrow('Password reset link is invalid or expired');
  });
});
