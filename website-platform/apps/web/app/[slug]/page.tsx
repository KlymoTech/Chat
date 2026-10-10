import type {Metadata} from 'next';
import {notFound} from 'next/navigation';
import Link from 'next/link';
import {getPage} from '../../lib/api';
type Props={params:Promise<{slug:string}>};
export async function generateMetadata({params}:Props):Promise<Metadata>{const {slug}=await params;try{const p=await getPage(slug);return{title:p.title,description:p.description};}catch(e){if(e instanceof Error&&e.message==='NOT_FOUND')return{title:'Page unavailable'};throw e;}}
export default async function PublicPage({params}:Props){
 const {slug}=await params;let page;
 try{page=await getPage(slug);}catch(e){if(e instanceof Error&&e.message==='NOT_FOUND')notFound();throw e;}
 return <><section className="innerhero"><div className="shell narrow"><p className="eyebrow">More information</p><h1>{page.title}</h1><p>{page.description}</p></div></section><article className="shell narrow reading"><div className="prose">{page.body}</div><div className="reading-action"><Link className="button" href="/contact">Ask a question ↗</Link></div></article></>;
}
