import type { PublicBlock } from "../lib/cms";
import {ACTION_PATH} from "../lib/builder-contract";
import {MeasuredActionLink,MeasuredFaq} from "./MeasuredActions";
/** Fixed, accessible block registry: never execute owner-authored HTML or scripts. */
export function PublishedBlocks({ blocks }: { blocks: PublicBlock[] }) {
  return <div className="cms-blocks">{blocks.map((block, index) => {
    const key=block.blockId??index;
    if (block.type === "heading") return <h2 key={key}>{block.text}</h2>;
    if (block.type === "paragraph") return <p key={key}>{block.text}</p>;
    if (block.type === "image") {
      const ready = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(block.assetId);
      return <figure key={key} className="cms-media">
        {ready?<img src={"/media/"+encodeURIComponent(block.assetId)} alt={block.alt}
          loading="lazy" decoding="async" style={{maxWidth:"100%",height:"auto"}}/>:
          <p>Image preview is available after selecting a published media asset.</p>}
        {block.caption&&<figcaption>{block.caption}</figcaption>}
      </figure>;
    }
    if (block.type === "hero") return <section key={key} className={"cms-hero cms-hero-"+block.variant}>
      {block.eyebrow&&<p className="eyebrow">{block.eyebrow}</p>}
      <h2>{block.heading}</h2><p>{block.description}</p>
      {ACTION_PATH.test(block.actionPath)?
        <MeasuredActionLink className="button" href={block.actionPath}
          actionKey={"cta_"+(block.blockId??index)}>{block.actionLabel}</MeasuredActionLink>:
        <p>Choose an approved internal action path before publishing.</p>}
    </section>;
    if (block.type === "cta") return <section key={key} className={"cms-cta cms-cta-"+block.variant}>
      <h2>{block.heading}</h2><p>{block.description}</p>
      {ACTION_PATH.test(block.actionPath)?
        <MeasuredActionLink className="button" href={block.actionPath}
          actionKey={"cta_"+(block.blockId??index)}>{block.actionLabel}</MeasuredActionLink>:
        <p>Choose an approved internal action path before publishing.</p>}
    </section>;
    if (block.type === "faq") return <section key={key} className="cms-faq" aria-label="Frequently asked questions">
      {block.items.map((entry,i)=><MeasuredFaq key={i} question={entry.question}
        answer={entry.answer} actionKey={"faq_"+(block.blockId??index)+"_"+i}/> )}
    </section>;
    return <aside className="cms-callout" key={key} aria-label={block.title}><h2>{block.title}</h2><p>{block.body}</p></aside>;
  })}</div>;
}
