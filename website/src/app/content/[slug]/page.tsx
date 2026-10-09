import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PublishedBlocks } from "../../../components/PublishedBlocks";
import { loadPublishedPage } from "../../../lib/cms-db";
import { canonical, indexingApproved } from "../../../lib/seo";

// Publication and trash visibility must be read from the live published-only view.
// Do not cache a page after its publication pointer has been revoked.
export const dynamic = "force-dynamic";

// Always resolve the live published pointer. Never prerender a CMS snapshot at build time.
export const dynamic = "force-dynamic";
export const revalidate = 0;

const validSlug = (slug: string) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug);
export async function generateMetadata({ params }: { params: Promise<{slug: string}> }): Promise<Metadata> {
  const { slug } = await params;
  const page = validSlug(slug) ? await loadPublishedPage(`/content/${slug}`) : null;
  if (!page) return { robots: { index: false, follow: false } };
  return { title: page.title, description: page.description,
    alternates: { canonical: canonical(page.path) }, robots: { index: indexingApproved() } };
}
export default async function ContentPage({ params }: { params: Promise<{slug: string}> }) {
  const { slug } = await params;
  if (!validSlug(slug)) notFound();
  const page = await loadPublishedPage(`/content/${slug}`);
  if (!page) notFound();
  return <article className="page"><h1>{page.title}</h1>{page.description && <p className="lead">{page.description}</p>}<PublishedBlocks blocks={page.blocks}/></article>;
}
