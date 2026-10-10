/** Inert, bounded editorial classification. Never accepts HTML or URLs. */
export type BlogClassification = Readonly<{ category:string; tags:readonly string[] }>;
const slug=/^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export function parseBlogClassification(value:unknown):BlogClassification|null {
  if (!value || typeof value!=="object" || Array.isArray(value))return null;
  const data=value as Record<string,unknown>;
  if(typeof data.category!=="string" || !Array.isArray(data.tags))return null;
  const category=data.category.trim().toLowerCase();
  if(category.length>60 || !slug.test(category) || data.tags.length>8)return null;
  const tags:string[]=[];
  for(const raw of data.tags){
    if(typeof raw!=="string")return null;
    const tag=raw.trim().toLowerCase();
    if(tag.length>40 || !slug.test(tag) || tags.includes(tag))return null;
    tags.push(tag);
  }
  return {category,tags};
}
