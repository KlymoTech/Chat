import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { site } from "../../lib/site";
import { canonical } from "../../lib/seo";

const content = {
  services: { title: "Services", description: "Contact us to discuss which services meet your needs.", body: "Service details and prices will be published after review and approval." },
  about: { title: "About", description: "Learn more about our organization.", body: "Verified company history, team information, and credentials will be published here once provided." },
  resources: { title: "Resources", description: "A library of useful information.", body: "Reviewed articles and downloadable resources will appear here when the editorial workflow is connected." },
  contact: { title: "Contact", description: "Reach out to our team.", body: "A contact email address must be configured before launch." },
  privacy: { title: "Privacy", description: "How personal data is handled.", body: "The approved privacy notice must be published before collecting personal data or enabling analytics." },
  terms: { title: "Terms", description: "Terms of use.", body: "The legally approved terms of use must be supplied before production launch." },
} as const;
type Slug = keyof typeof content;
export function generateStaticParams() { return Object.keys(content).map(slug => ({slug})); }
export async function generateMetadata({params}: {params: Promise<{slug:string}>}): Promise<Metadata> {
  const {slug}=await params;
  if (!(slug in content)) return { robots: { index: false, follow: false } };
  return { title:content[slug as Slug].title, alternates: { canonical: canonical(`/${slug}`) },
    ...(slug === "privacy" || slug === "terms" ? {robots:{index:false,follow:false}} : {}) };
}
export default async function ContentPage({params}:{params:Promise<{slug:string}>}) {
  const {slug}=await params;
  if (!(slug in content)) notFound();
  const page = content[slug as Slug];
  return <section className="page"><h1>{page.title}</h1><p className="lead">{page.description}</p><p>{page.body}</p>{slug === "contact" && site.contactEmail && <a className="button" href={`mailto:${site.contactEmail}`}>Email our team</a>}</section>;
}
