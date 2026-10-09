import type { Metadata } from "next";
import Link from "next/link";
import { pages, site } from "../lib/site";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(site.siteUrl),
  title: { default: site.name, template: `%s | ${site.name}` },
  description: site.description,
  robots: { index: process.env.NEXT_PUBLIC_SITE_URL !== undefined },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>
    <a className="skip-link" href="#main">Skip to content</a>
    <header className="header"><div className="container nav"><Link className="brand" href="/">{site.name}</Link><nav aria-label="Primary navigation"><ul>{pages.map((page) => <li key={page.href}><Link href={page.href}>{page.label}</Link></li>)}</ul></nav></div></header>
    <main id="main" className="container" tabIndex={-1}>{children}</main>
    <footer className="footer"><div className="container"><p>© {new Date().getFullYear()} {site.name}</p><nav aria-label="Legal"><Link href="/privacy">Privacy</Link><Link href="/terms">Terms</Link></nav></div></footer>
  </body></html>;
}
