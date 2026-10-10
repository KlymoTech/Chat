import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "next/link";
import { readPublishedResources } from "../../lib/cms-db";
import { site } from "../../lib/site";
import { EnquiryForm } from "../../components/EnquiryForm";
import { canonical } from "../../lib/seo";

export const dynamic = "force-dynamic";

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
  const resourceIndex = slug === "resources" ? await readPublishedResources() : null;
  return <section className="page"><h1>{page.title}</h1><p className="lead">{page.description}</p>
    {slug === "resources" ? (resourceIndex?.status === "unavailable" ? <p role="status">Resources are temporarily unavailable. Please try again later.</p> : resourceIndex?.resources.length ? <ul className="resource-list">{resourceIndex.resources.map(resource =>
      <li key={resource.path}><h2><Link href={resource.path}>{resource.title}</Link></h2>{resource.description && <p>{resource.description}</p>}</li>
    )}</ul> : <p>No published resources are available yet.</p>) : <p>{page.body}</p>}
    {slug === "contact" && <>{process.env.WEBSITE_LEAD_CAPTURE_ENABLED === "true" && <EnquiryForm fallbackEmail={site.contactEmail}/>} {site.contactEmail && <p><a href={`mailto:${site.contactEmail}`}>Email our team</a></p>}</>}
  </section>;
}
