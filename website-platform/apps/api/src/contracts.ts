import { z } from 'zod';

export const slugSchema = z.string().trim().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, 'Use lower-case URL-safe slugs').max(80);
export const documentSchema = z.object({
  title: z.string().trim().min(1).max(160),
  slug: slugSchema,
  description: z.string().trim().max(300).default(''),
  body: z.string().max(100000).default(''),
  revision: z.number().int().min(0).optional(),
}).strict();
export const siteSchema = z.object({
  name: z.string().trim().min(1).max(120),
  tagline: z.string().trim().max(240),
  description: z.string().trim().max(500),
}).strict();
export const leadSchema = z.object({
  name: z.string().trim().min(1).max(120),
  email: z.string().trim().email().max(254),
  message: z.string().trim().min(5).max(4000),
  idempotencyKey: z.string().uuid(),
  marketingOptIn: z.boolean().default(false),
  utm: z.object({
    source: z.string().max(100).optional(),
    medium: z.string().max(100).optional(),
    campaign: z.string().max(100).optional(),
  }).strict().optional(),
  website: z.string().max(100).optional()
}).strict();
export const credentialsSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1).max(256),
}).strict();
