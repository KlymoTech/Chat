import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PublishedBlocks } from "../../../components/PublishedBlocks";
import { getPublishedPage } from "../../../lib/cms";
import { canonical, indexingApproved } from "../../../lib/seo";

const validSlug = (slug: string) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug);
export async function generateMetadata({ params }: { params: Promise<{slug: string}> }): Promise<Metadata> {
  const { slug } = await params;
  const page = validSlug(slug) ? await getPublishedPage(`/content/${slug}`) : null;
  if (!page) return { robots: { index: false, follow: false } };
  return { title: page.title, description: page.description,
    alternates: { canonical: canonical(page.path) }, robots: { index: indexingApproved() } };
}
export default async function ContentPage({ params }: { params: Promise<{slug: string}> }) {
  const { slug } = await params;
  if (!validSlug(slug)) notFound();
  const page = await getPublishedPage(`/content/${slug}`);
  if (!page) notFound();
  return <article className="page"><h1>{page.title}</h1>{page.description && <p className="lead">{page.description}</p>}<PublishedBlocks blocks={page.blocks}/></article>;
}
