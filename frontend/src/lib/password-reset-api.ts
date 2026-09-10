import { ApiError } from '@/lib/api';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';

export interface PasswordResetResult {
  reset: boolean;
}

async function errorFrom(response: Response, fallback: string): Promise<ApiError> {
  let payload: unknown;
  try { payload = await response.json() as unknown; } catch { payload = undefined; }
  if (payload && typeof payload === 'object') {
    const apiError = (payload as { error?: unknown }).error;
    if (apiError && typeof apiError === 'object') {
      const message = (apiError as { message?: unknown }).message;
      if (typeof message === 'string' && message.trim()) return new ApiError(message, response.status, payload);
    }
  }
  return new ApiError(fallback, response.status, payload);
}

export const passwordResetApi = {
  async request(email: string): Promise<void> {
    const response = await fetch(`${API_URL}/auth/password-reset/request`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase() }),
    });
    if (!response.ok) throw await errorFrom(response, 'Unable to request a password reset email.');
  },

  async confirm(token: string, password: string, confirmPassword: string): Promise<PasswordResetResult> {
    const response = await fetch(`${API_URL}/auth/password-reset/confirm`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, password, confirmPassword }),
    });
    if (!response.ok) throw await errorFrom(response, 'Password reset link is invalid or expired.');
    return response.json() as Promise<PasswordResetResult>;
  },
};
