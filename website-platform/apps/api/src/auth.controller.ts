import {
  Body, Controller, Get, Post, Req, Res, UnauthorizedException, UseGuards,
} from '@nestjs/common';
import type { Request, Response } from 'express';
import { addDays } from './date';
import { Db, AdminGuard, AdminRequest, createToken, enforceOrigin, hashToken, parseInput, verifyPassword } from './core';
import { credentialsSchema } from './contracts';

@Controller('v1/auth')
export class AuthController {
  constructor(private readonly db: Db) {}
  @Post('login')
  async login(@Body() body: unknown, @Req() req: Request, @Res({ passthrough: true }) res: Response) {
    enforceOrigin(req);
    const input = parseInput(credentialsSchema, body);
    const user = await this.db.adminUser.findUnique({ where: { email: input.email.toLowerCase() } });
    if (!user || !verifyPassword(input.password, user.passwordHash)) {
      throw new UnauthorizedException('Invalid email or password');
    }
    const token = createToken();
    await this.db.adminSession.create({
      data: { tokenHash: hashToken(token), userId: user.id, expiresAt: addDays(new Date(), 7) }
    });
    res.cookie('studio_session', token, {
      httpOnly: true, secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict', path: '/', maxAge: 7 * 24 * 60 * 60 * 1000,
    });
    return { role: user.role, email: user.email };
  }
  @UseGuards(AdminGuard)
  @Get('me')
  async me(@Req() req: AdminRequest) {
    const user = await this.db.adminUser.findUniqueOrThrow({ where: { id: req.adminId } });
    return { email: user.email, role: user.role };
  }
  @UseGuards(AdminGuard)
  @Post('logout')
  async logout(@Req() req: AdminRequest, @Res({ passthrough: true }) res: Response) {
    await this.db.adminSession.update({ where: { id: req.sessionId }, data: { revokedAt: new Date() } });
    res.clearCookie('studio_session', { path: '/' });
    return { ok: true };
  }
}
