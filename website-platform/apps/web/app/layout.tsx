import Link from 'next/link';
import type {Metadata} from 'next';
import {getSite} from '../lib/api';
import './globals.css';
export const dynamic='force-dynamic';
export const metadata:Metadata={title:{default:'Website Studio',template:'%s | Website Studio'},description:'Owner-managed website and resources'};
export default async function RootLayout({children}:{children:React.ReactNode}){
  const site=await getSite().catch(()=>({name:'Website Studio',tagline:'',description:''}));
  return <html lang="en"><body><a className="skip" href="#content">Skip to main content</a>
    <header className="header"><nav className="nav shell" aria-label="Main navigation">
      <Link className="brand" href="/"><span className="brandmark" aria-hidden="true">W</span>{site.name}</Link>
      <div className="navlinks"><Link href="/">Home</Link><Link href="/blog">Insights</Link><Link href="/contact">Contact</Link><Link className="quiet-link" href="/admin">Owner console</Link></div>
    </nav></header>
    <main id="content">{children}</main>
    <footer className="footer"><div className="footerrow shell"><div><strong>{site.name}</strong><p>Information and services, clearly explained.</p></div><nav aria-label="Footer links"><Link href="/contact">Contact</Link><Link href="/privacy">Privacy</Link><Link href="/consent-preferences">Cookie preferences</Link></nav></div></footer>
  </body></html>;
}
