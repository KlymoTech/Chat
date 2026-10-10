import {freshBuilderBlock,validBuilderIdentities} from "./builder-contract";
import type {PublicBlock} from "./cms";

/**
 * Preapproved *layout patterns*, not preapproved business claims.
 * The owner must replace neutral placeholders and pass normal CMS review.
 * Never executes templates or imports external CSS/scripts.
 */
export const BUILDER_TEMPLATES=[
  {id:"services-overview",title:"Services overview",
    description:"A structured introduction, action and frequently asked questions."},
  {id:"resource-article",title:"Resource article",
    description:"Readable editorial headings, body, FAQ and a follow-up action."},
  {id:"contact-conversion",title:"Contact conversion",
    description:"A clear contact call-to-action with accessible supporting information."},
] as const;
export type BuilderTemplateId=typeof BUILDER_TEMPLATES[number]["id"];
export function isBuilderTemplateId(value:unknown):value is BuilderTemplateId {
  return typeof value==="string" && BUILDER_TEMPLATES.some(t=>t.id===value);
}
export function instantiateTemplate(
  id:BuilderTemplateId,uuid:()=>string,
):PublicBlock[] {
  function hero(heading:string,variant:"center"|"split") {
    return {...freshBuilderBlock("hero",uuid()),heading,variant,
      eyebrow:"About this page",description:"Replace this text with reviewed information."};
  }
  function cta(heading:string) {
    return {...freshBuilderBlock("cta",uuid()),heading,
      description:"Explain why visitors should get in touch before publishing."};
  }
  function faq() {
    return {...freshBuilderBlock("faq",uuid()),items:[
      {question:"How can I learn more?",answer:"Visit our contact page to send an enquiry."},
      {question:"Where can I find more information?",answer:"Explore the resources section."},
    ]};
  }
  const article=(text:string):PublicBlock=>({
    type:"paragraph",blockId:uuid(),schemaVersion:1,text,
  });
  let blocks:PublicBlock[];
  switch(id) {
    case "services-overview":
      blocks=[hero("How we can help", "split"),
        article("Replace this paragraph with an approved explanation of your services."),
        faq(),cta("Ask about our services")];break;
    case "resource-article":
      blocks=[
        {type:"heading",blockId:uuid(),schemaVersion:1,text:"Article section"},
        article("Replace this paragraph with accurate, reviewed resource content."),
        faq(),cta("Have a question?")];break;
    case "contact-conversion":
      blocks=[hero("Talk to our team","center"),
        article("Describe how enquiries are handled and what visitors can expect."),
        cta("Get in touch")];break;
    default:throw Error("Unknown template");
  }
  if(!validBuilderIdentities(blocks))throw Error("Template block identity conflict");
  return blocks;
}
