import Link from 'next/link';
import {getPage,getPages,getSite} from '../lib/api';
export default async function Home(){
 const [site,home,pages]=await Promise.all([getSite(),getPage('home'),getPages()]);
 return <><section className="hero"><div className="shell herogrid"><div>
  <p className="eyebrow"><span className="eyebrowdot"/> Welcome</p><h1>{home.title}</h1>
  <p className="hero-copy">{site.tagline||home.description}</p><div className="cta"><Link className="button" href="/contact">Get in touch ↗</Link><Link className="button secondary" href="/blog">Read our insights</Link></div>
 </div><div className="hero-visual" aria-hidden="true"><div className="visual-orbit"><div className="center-logo">W</div><div className="orbit-dot one"/><div className="orbit-dot two"/></div><div className="visual-annotation">Clarity · Confidence · Connection</div></div></div></section>
 <section className="section"><div className="shell narrow"><p className="eyebrow">Explore</p><h2>Find what matters to you.</h2><p className="intro">{home.body}</p></div></section>
 {pages.some(p=>p.slug!=='home')&&<section className="section subdued"><div className="shell"><p className="eyebrow">Explore more</p><h2>Our pages</h2><div className="cards">{pages.filter(p=>p.slug!=='home').map(p=><Link className="tile" key={p.slug} href={'/'+p.slug}><div className="tile-icon">↗</div><h3>{p.title}</h3><p>{p.description}</p><span className="tile-more">Explore page →</span></Link>)}</div></div></section>}
 <section className="closing"><div className="shell closing-inner"><p className="eyebrow">Start a conversation</p><h2>Ready to connect?</h2><p>Tell us what you need, and we can take it from there.</p><Link className="button light" href="/contact">Contact us ↗</Link></div></section></>;
}
