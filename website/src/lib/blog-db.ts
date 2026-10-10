import "server-only";
import {Pool} from "pg";
import {isPublishedPage} from "./cms";
import {parseBlogClassification} from "./blog-contract";

export type BlogSummary=Readonly<{
  path:string;title:string;description:string;
  category:string;tags:readonly string[];createdAt:string;
}>;
export type BlogIndex=Readonly<{
  status:"available"|"unavailable";posts:BlogSummary[];
}>;
let db:Pool|undefined;
function publicReader():Pool|null{
  const connectionString=process.env.WEBSITE_CMS_DATABASE_URL;
  if(!connectionString)return null;
  if(!db)db=new Pool({connectionString,max:4,connectionTimeoutMillis:3000,idleTimeoutMillis:10000});
  return db;
}
/** Only views with published, non-trashed snapshots are queried. */
export async function readPublishedBlogIndex(
  query:string,category:string,locale="en",
):Promise<BlogIndex>{
  const site=process.env.WEBSITE_CMS_SITE_SLUG;
  if(!site||!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(site)||
    !/^[a-z]{2}(?:-[A-Z]{2})?$/.test(locale))return {status:"unavailable",posts:[]};
  const reader=publicReader();
  if(!reader)return {status:"unavailable",posts:[]};
  const search=typeof query==="string"?query.trim().slice(0,80):"";
  const categoryName=typeof category==="string"&&/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(category)?
    category.slice(0,60):"";
  try {
    const result=await reader.query<{
      id:string;path:string;locale:string;revision:number;title:string;description:string;
      blocks:unknown;category:string;tags:unknown;blog_created_at:Date|string;
    }>(
      "SELECT id,path,locale,revision,title,description,blocks,category,tags,blog_created_at "+
      "FROM website_cms.public_published_blog_entries "+
      "WHERE site_slug=$1 AND locale=$2 "+
      "AND ($3::text='' OR strpos(lower(title||' '||description),lower($3::text))>0) "+
      "AND ($4::text='' OR category=$4) "+
      "ORDER BY blog_created_at DESC,path ASC LIMIT 100",
      [site,locale,search,categoryName],
    );
    const posts:BlogSummary[]=[];
    for(const row of result.rows){
      const meta=parseBlogClassification({category:row.category,tags:row.tags});
      if(!isPublishedPage(row)||!meta||!row.path.startsWith("/content/"))continue;
      posts.push({
        path:row.path,title:row.title,description:row.description,
        category:meta.category,tags:meta.tags,
        createdAt:row.blog_created_at instanceof Date?
          row.blog_created_at.toISOString():String(row.blog_created_at),
      });
    }
    return {status:"available",posts};
  }catch{
    return {status:"unavailable",posts:[]};
  }
}
