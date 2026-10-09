import { BadRequestException, Body, Controller, Get, Param, Post } from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { Db, parseInput } from './core';
import { leadSchema } from './contracts';

@Controller('v1/public')
export class PublicController {
  constructor(private readonly db: Db) {}
  private site() { return this.db.site.findUniqueOrThrow({ where: { key: 'default' } }); }

  @Get('site')
  async getSite() {
    const s = await this.site();
    return { name: s.name, tagline: s.tagline, description: s.description };
  }

  @Get('pages/:slug')
  async getPage(@Param('slug') slug: string) {
    const s = await this.site();
    return this.db.page.findFirstOrThrow({
      where: { siteId: s.id, slug, status: 'PUBLISHED' },
      select: { slug: true, title: true, description: true, body: true, publishedAt: true },
    });
  }

  @Get('pages')
  async pages() {
    const s = await this.site();
    return this.db.page.findMany({
      where: { siteId: s.id, status: 'PUBLISHED' },
      select: { slug: true, title: true, description: true },
      orderBy: { title: 'asc' },
    });
  }

  @Get('articles')
  async articles() {
    const s = await this.site();
    return this.db.article.findMany({
      where: { siteId: s.id, status: 'PUBLISHED' },
      select: { slug: true, title: true, description: true, publishedAt: true },
      orderBy: { publishedAt: 'desc' },
      take: 100,
    });
  }

  @Get('articles/:slug')
  async article(@Param('slug') slug: string) {
    const s = await this.site();
    return this.db.article.findFirstOrThrow({
      where: { siteId: s.id, slug, status: 'PUBLISHED' },
      select: { slug: true, title: true, description: true, body: true, publishedAt: true },
    });
  }

  @Post('leads')
  async createLead(@Body() body: unknown) {
    const input = parseInput(leadSchema, body);
    if (input.website) throw new BadRequestException('Invalid submission');
    const s = await this.site();
    const existing = await this.db.lead.findUnique({ where: { idempotencyKey: input.idempotencyKey } });
    if (existing) return { id: existing.id, accepted: true };
    try {
      const lead = await this.db.$transaction(async tx => {
        const created = await tx.lead.create({
          data: {
            siteId: s.id, name: input.name, email: input.email, message: input.message,
            idempotencyKey: input.idempotencyKey, marketingOptIn: input.marketingOptIn,
            utm: input.marketingOptIn && input.utm ? input.utm : Prisma.JsonNull,
          },
        });
        await tx.outboxEvent.create({
          data: { topic: 'lead.accepted', payload: { leadId: created.id, siteId: s.id } }
        });
        return created;
      });
      return { id: lead.id, accepted: true };
    } catch (e) {
      if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
        const previous = await this.db.lead.findUnique({ where: { idempotencyKey: input.idempotencyKey } });
        if (previous) return { id: previous.id, accepted: true };
      }
      throw e;
    }
  }
}
