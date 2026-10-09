export type Site={name:string;tagline:string;description:string};
export type Doc={slug:string;title:string;description:string;body:string;publishedAt?:string};
const endpoint=process.env.API_INTERNAL_URL||'http://localhost:4100';
export async function api<T>(path:string):Promise<T>{
 const res=await fetch(endpoint+path,{cache:'no-store'});
 if(res.status===404)throw new Error('NOT_FOUND');
 if(!res.ok)throw new Error('Website API unavailable: '+res.status);
 return res.json() as Promise<T>;
}
export const getSite=()=>api<Site>('/v1/public/site');
export const getPages=()=>api<Doc[]>('/v1/public/pages');
export const getPage=(slug:string)=>api<Doc>('/v1/public/pages/'+encodeURIComponent(slug));
export const getArticles=()=>api<Doc[]>('/v1/public/articles');
export const getArticle=(slug:string)=>api<Doc>('/v1/public/articles/'+encodeURIComponent(slug));
