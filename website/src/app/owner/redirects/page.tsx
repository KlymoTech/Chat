import type {Metadata} from "next";
import RedirectConsole from "./redirect-console";
export const dynamic="force-dynamic";
export const metadata:Metadata={title:"Owner Content Redirects",robots:{index:false,follow:false}};
export default function RedirectsPage(){return <RedirectConsole/>;}
