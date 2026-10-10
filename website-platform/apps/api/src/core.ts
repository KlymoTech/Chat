import {
  BadRequestException, CanActivate, ExecutionContext, Injectable,
  OnModuleDestroy, UnauthorizedException, ConflictException,
} from '@nestjs/common';
import { PrismaClient } from '@prisma/client';
import { createHash, randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import type { Request } from 'express';

@Injectable()
export class Db extends PrismaClient implements OnModuleDestroy {
  async onModuleDestroy(): Promise<void> { await this.$disconnect(); }
}

export const hashToken = (value: string): string => createHash('sha256').update(value).digest('hex');
export const createToken = (): string => randomBytes(32).toString('base64url');
export function hashPassword(password: string): string {
  const salt = randomBytes(16).toString('hex');
  return salt + ':' + scryptSync(password, salt, 64).toString('hex');
}
export function verifyPassword(password: string, stored: string): boolean {
  const parts = stored.split(':');
  if (parts.length !== 2 || !/^[a-f0-9]{32}$/.test(parts[0]) || !/^[a-f0-9]{128}$/.test(parts[1])) return false;
  const actual = scryptSync(password, parts[0], 64);
  const expected = Buffer.from(parts[1], 'hex');
  return timingSafeEqual(actual, expected);
}
export function parseInput<T>(schema: { safeParse: (input: unknown) => { success: boolean; data?: T; error?: { issues: unknown[] } } }, input: unknown): T {
  const result = schema.safeParse(input);
  if (!result.success || !result.data) throw new BadRequestException(result.error?.issues ?? 'Invalid request');
  return result.data;
}
export function enforceOrigin(req: Request): void {
  const expected = process.env.WEB_ORIGIN;
  if (!expected) throw new Error('WEB_ORIGIN must be configured');
  const origin = req.headers.origin;
  if (origin !== expected) throw new UnauthorizedException('Untrusted request origin');
}
export function sessionCookie(req: Request): string | null {
  const raw = req.headers.cookie ?? '';
  const match = raw.split(';').map(x => x.trim()).find(x => x.startsWith('studio_session='));
  return match ? match.slice('studio_session='.length) : null;
}
export type AdminRequest = Request & { adminId: string; adminRole: string; sessionId: string };
@Injectable()
export class AdminGuard implements CanActivate {
  constructor(private readonly db: Db) {}
  async canActivate(context: ExecutionContext): Promise<boolean> {
    const req = context.switchToHttp().getRequest<AdminRequest>();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method)) enforceOrigin(req);
    const token = sessionCookie(req);
    if (!token) throw new UnauthorizedException('Sign in required');
    const session = await this.db.adminSession.findUnique({
      where: { tokenHash: hashToken(token) },
      include: { user: true },
    });
    if (!session || session.revokedAt || session.expiresAt <= new Date()) {
      throw new UnauthorizedException('Session expired');
    }
    req.adminId = session.user.id;
    req.adminRole = session.user.role;
    req.sessionId = session.id;
    return true;
  }
}
export function requireRevision(expected: number | undefined, actual: number): void {
  if (expected === undefined || expected !== actual) {
    throw new ConflictException('Content changed. Refresh the editor before saving.');
  }
}
