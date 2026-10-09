import Link from 'next/link';
import {getArticles} from '../../lib/api';
export const metadata={title:'Insights',description:'Latest published resources'};
export default async function Blog(){
 const articles=await getArticles();
 return <><section className="innerhero"><div className="shell"><p className="eyebrow">Resources</p><h1>Insights & ideas</h1><p>Information, written with care.</p></div></section><section className="section"><div className="shell">
 {articles.length===0?<div className="empty"><h2>Articles coming soon</h2><p>Published resources will appear here.</p></div>:<div className="cards">{articles.map(a=><Link className="tile" key={a.slug} href={'/blog/'+a.slug}><p className="eyebrow">Article</p><h2>{a.title}</h2><p>{a.description}</p><span className="tile-more">Read article →</span></Link>)}</div>}
 </div></section></>;
}
