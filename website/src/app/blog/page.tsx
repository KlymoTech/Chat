import type {Metadata} from "next";
import Link from "next/link";
import {readPublishedBlogIndex} from "../../lib/blog-db";
import {canonical,indexingApproved} from "../../lib/seo";

export const dynamic="force-dynamic";
export const metadata:Metadata={
  title:"Blog",
  description:"Published articles and updates from our editorial team.",
  alternates:{canonical:canonical("/blog")},
  robots:{index:indexingApproved(),follow:indexingApproved()},
};
type Params={searchParams:Promise<{q?:string|string[];category?:string|string[]}>};
const first=(value:string|string[]|undefined)=>typeof value==="string"?value:"";
export default async function BlogIndexPage({searchParams}:Params){
  const params=await searchParams;
  const q=first(params.q).trim().slice(0,80);
  const category=first(params.category).trim().toLowerCase().slice(0,60);
  const result=await readPublishedBlogIndex(q,category);
  return <section className="page blog-index">
    <p className="eyebrow">Editorial resources</p>
    <h1>Blog</h1>
    <p className="lead">Explore published articles, guidance and updates.</p>
    <form action="/blog" method="get" role="search" className="blog-search">
      <label htmlFor="blog-query">Search published articles</label>
      <input id="blog-query" name="q" type="search" defaultValue={q} maxLength={80}
        placeholder="Enter a topic or keyword" />
      <label htmlFor="blog-category">Category (optional)</label>
      <input id="blog-category" name="category" type="text" defaultValue={category} maxLength={60}
        pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="e.g. product-updates"/>
      <div className="actions"><button className="button" type="submit">Search blog</button>
        <Link href="/blog" className="button secondary">Clear filters</Link></div>
    </form>
    {result.status==="unavailable"?
      <p role="status">The blog is temporarily unavailable. Please try again later.</p>:
      result.posts.length===0?
      <p role="status">No published articles match these filters.</p>:
      <ul className="blog-results">{result.posts.map(post=>
        <li key={post.path}>
          <article>
            <p className="blog-category">{post.category.replaceAll("-"," ")}</p>
            <h2><Link href={post.path}>{post.title}</Link></h2>
            {post.description&&<p>{post.description}</p>}
            {post.tags.length>0&&<p className="blog-tags">
              <span className="visually-hidden">Topics: </span>
              {post.tags.map(tag=><span key={tag}>{tag.replaceAll("-"," ")}</span>)}
            </p>}
          </article>
        </li>
      )}</ul>}
  </section>;
}
