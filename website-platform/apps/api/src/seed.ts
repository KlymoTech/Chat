import 'dotenv/config';
import { PrismaClient } from '@prisma/client';
import { hashPassword } from './core';

async function main() {
  if (!process.env.DATABASE_URL || !process.env.ADMIN_EMAIL || !process.env.ADMIN_PASSWORD) {
    throw new Error('Set DATABASE_URL, ADMIN_EMAIL and ADMIN_PASSWORD before seeding');
  }
  if (process.env.ADMIN_PASSWORD.length < 16) {
    throw new Error('ADMIN_PASSWORD must contain at least 16 characters');
  }
  const db = new PrismaClient();
  try {
    const site = await db.site.upsert({
      where: { key: 'default' },
      update: {},
      create: { key: 'default', name: 'Your business', tagline: 'A website you control', description: 'Replace these placeholders with approved business content.' }
    });
    await db.page.upsert({
      where: { siteId_slug: { siteId: site.id, slug: 'home' } },
      update: {},
      create: {
        siteId: site.id, slug: 'home', title: 'Welcome',
        description: 'An owner-managed website', body: 'Publish accurate information about your business from the owner console.',
        status: 'PUBLISHED', revision: 1, draftVersion: 1,
        publishedSnapshot: { slug: 'home', title: 'Welcome', description: 'An owner-managed website', body: 'Publish accurate information about your business from the owner console.' },
        publishedAt: new Date(),
      }
    });
    const currentHome = await db.page.findUniqueOrThrow({ where: { siteId_slug: { siteId: site.id, slug: 'home' } } });
    if (currentHome.revision > 0 && currentHome.publishedSnapshot) {
      await db.pageRevision.upsert({
        where: { pageId_revision: { pageId: currentHome.id, revision: currentHome.revision } },
        update: {}, create: { pageId: currentHome.id, revision: currentHome.revision,
          snapshot: currentHome.publishedSnapshot, actorId: 'system-bootstrap' }
      });
    }
    const email = process.env.ADMIN_EMAIL.toLowerCase().trim();
    const existingUser = await db.adminUser.findUnique({ where: { email } });
    if (!existingUser) {
      await db.adminUser.create({
        data: { email, passwordHash: hashPassword(process.env.ADMIN_PASSWORD), role: 'OWNER' }
      });
    }
    console.info('Site initialized; existing administrator credentials have not been changed.');
  } finally {
    await db.$disconnect();
  }
}
void main().catch(err => { console.error(err); process.exitCode = 1; });
