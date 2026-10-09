import type { Metadata } from "next";
import Link from "next/link";
import { pages, site } from "../lib/site";
import { canonical, indexingApproved, publishedOrigin } from "../lib/seo";
import { ConsentPreferences } from "../components/ConsentPreferences";
import "./globals.css";

export const metadata: Metadata = {
  ...(publishedOrigin() ? { metadataBase: publishedOrigin()! } : {}),
  title: { default: site.name, template: `%s | ${site.name}` },
  description: site.description,
  robots: { index: indexingApproved(), follow: indexingApproved() },
  alternates: { canonical: canonical("/") },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="header"><div className="container nav"><Link className="brand" href="/">{site.name}</Link><nav aria-label="Primary navigation"><ul>{pages.map((page) => <li key={page.href}><Link href={page.href}>{page.label}</Link></li>)}</ul></nav></div></header>
    <main id="main" className="container" tabIndex={-1}>{children}</main>
    <footer className="footer"><div className="container"><p>© {new Date().getFullYear()} {site.name}</p><nav aria-label="Legal"><Link href="/privacy">Privacy</Link><Link href="/terms">Terms</Link><Link href="/privacy-choices">Privacy choices</Link><Link href="/owner">Owner CMS</Link></nav><ConsentPreferences /></div></footer>
  </body></html>;
}
