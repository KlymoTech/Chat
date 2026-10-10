import type {Metadata} from "next";
import PrivacyRightsConsole from "./rights-console";
export const dynamic="force-dynamic";
export const metadata:Metadata={title:"Privacy Rights Cases",robots:{index:false,follow:false}};
export default function PrivacyRightsPage(){return <PrivacyRightsConsole/>;}
