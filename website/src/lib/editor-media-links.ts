import type {PoolClient} from "pg";
import type {CmsBlock} from "./cms-editor";

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
/** Deduplicate media references in one immutable CMS revision. */
export function mediaAssetIds(blocks:readonly CmsBlock[]):string[] {
  return [...new Set(blocks.filter((b):b is Extract<CmsBlock,{type:"image"}> =>
    b.type==="image").map(block=>block.assetId))];
}
/**
 * Called during the SAME transaction as public revision creation. A private,
 * unapproved, withdrawn or different-site asset blocks page publication.
 * Usage references are append-only, preserving impact history.
 */
export async function attachPublishedMediaUsages(
  client:PoolClient,siteId:string,pageId:string,revisionId:string,
  blocks:readonly CmsBlock[],
):Promise<void> {
  const ids=mediaAssetIds(blocks);
  if(!ids.length)return;
  if(process.env.WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED!=="true"||
     process.env.WEBSITE_MEDIA_PUBLIC_READER_GRANTS_VERIFIED!=="true")
    throw new Error("Image publication not enabled");
  for(const id of ids){
    if(!uuid.test(id))throw new Error("Invalid media reference");
    const eligible=await client.query(
      `SELECT id FROM website_cms.media_assets
        WHERE id=$1 AND site_id=$2 AND state='approved'
          AND published_at IS NOT NULL AND withdrawn_at IS NULL
          AND inspected_at IS NOT NULL AND reviewed_at IS NOT NULL
          AND sanitized_sha256 IS NOT NULL FOR SHARE`,
      [id,siteId],
    );
    if(eligible.rowCount!==1)
      throw new Error("Page refers to a private, withdrawn or unapproved asset");
    await client.query(
      `INSERT INTO website_cms.media_usages(site_id,asset_id,page_id,revision_id)
       VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING`,
      [siteId,id,pageId,revisionId],
    );
  }
}
