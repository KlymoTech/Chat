import type {Metadata} from 'next';
import {notFound} from 'next/navigation';
import Link from 'next/link';
import {getArticle} from '../../../lib/api';
type Props={params:Promise<{slug:string}>};
export async function generateMetadata({params}:Props):Promise<Metadata>{const {slug}=await params;try{const a=await getArticle(slug);return{title:a.title,description:a.description};}catch(e){if(e instanceof Error&&e.message==='NOT_FOUND')return{title:'Article unavailable'};throw e;}}
export default async function Article({params}:Props){
 const {slug}=await params;let a;
 try{a=await getArticle(slug);}catch(e){if(e instanceof Error&&e.message==='NOT_FOUND')notFound();throw e;}
 return <><section className="innerhero"><div className="shell narrow"><Link className="back" href="/blog">← All insights</Link><p className="eyebrow">Article</p><h1>{a.title}</h1><p>{a.description}</p></div></section><article className="shell narrow reading"><div className="prose">{a.body}</div><p><Link href="/contact">Ask us about this topic →</Link></p></article></>;
}
