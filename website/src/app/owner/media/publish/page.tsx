import type {Metadata} from "next";
import MediaPublicationConsole from "./publication-console";
export const dynamic="force-dynamic";
export const metadata:Metadata={title:"Approved Media Publication",
  robots:{index:false,follow:false}};
export default function MediaPublishPage(){return <MediaPublicationConsole/>;}
