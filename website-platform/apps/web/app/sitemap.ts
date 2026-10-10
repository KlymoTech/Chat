import type {MetadataRoute} from 'next';
import {getPages,getArticles} from '../lib/api';
export const dynamic='force-dynamic';
export default async function sitemap():Promise<MetadataRoute.Sitemap>{
 const origin=process.env.WEB_ORIGIN;
 if(!origin)return [];
 const [pages,articles]=await Promise.all([getPages(),getArticles()]);
 return [{url:origin+'/',priority:1,changeFrequency:'monthly'},
  {url:origin+'/blog',priority:0.6,changeFrequency:'weekly'},
  ...pages.filter(p=>p.slug!=='home').map(p=>({url:origin+'/'+p.slug,priority:0.7,changeFrequency:'monthly' as const})),
  ...articles.map(a=>({url:origin+'/blog/'+a.slug,priority:0.5,changeFrequency:'monthly' as const}))];
}
