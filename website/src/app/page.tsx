import Link from "next/link";
import { site } from "../lib/site";
export default function Home() {
  return <><section className="hero"><p className="eyebrow">Welcome</p><h1>{site.tagline}</h1><p>{site.description}</p><div className="actions"><Link className="button" href="/services">Explore services</Link><Link className="button secondary" href="/contact">Get in touch</Link></div></section><section aria-labelledby="explore"><h2 id="explore">How can we help?</h2><div className="cards"><article><h3>What we offer</h3><p>Read an overview of available services and how to enquire.</p><Link href="/services">View services →</Link></article><article><h3>Our approach</h3><p>Learn about our organization before you decide to contact us.</p><Link href="/about">Learn more →</Link></article><article><h3>Helpful information</h3><p>Find resources as they become available.</p><Link href="/resources">Browse resources →</Link></article></div></section></>;
}
