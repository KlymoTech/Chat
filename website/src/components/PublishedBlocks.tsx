import type { PublicBlock } from "../lib/cms";
/** Fixed, accessible block registry: never execute owner-authored HTML or scripts. */
export function PublishedBlocks({ blocks }: { blocks: PublicBlock[] }) {
  return <div className="cms-blocks">{blocks.map((block, index) => {
    if (block.type === "heading") return <h2 key={index}>{block.text}</h2>;
    if (block.type === "paragraph") return <p key={index}>{block.text}</p>;
    if (block.type === "image") return <figure key={index} className="cms-media">
      <img src={"/media/"+encodeURIComponent(block.assetId)} alt={block.alt}
        loading="lazy" decoding="async" style={{maxWidth:"100%",height:"auto"}}/>
      {block.caption&&<figcaption>{block.caption}</figcaption>}
    </figure>;
    return <aside className="cms-callout" key={index} aria-label={block.title}><h2>{block.title}</h2><p>{block.body}</p></aside>;
  })}</div>;
}
