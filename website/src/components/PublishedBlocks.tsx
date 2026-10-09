import type { PublicBlock } from "../lib/cms";
/** Fixed, accessible block registry: never execute owner-authored HTML or scripts. */
export function PublishedBlocks({ blocks }: { blocks: PublicBlock[] }) {
  return <div className="cms-blocks">{blocks.map((block, index) => {
    if (block.type === "heading") return <h2 key={index}>{block.text}</h2>;
    if (block.type === "paragraph") return <p key={index}>{block.text}</p>;
    return <aside className="cms-callout" key={index} aria-label={block.title}><h2>{block.title}</h2><p>{block.body}</p></aside>;
  })}</div>;
}
