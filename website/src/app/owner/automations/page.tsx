import type {Metadata} from "next";
import AutomationConsole from "./automation-console";
export const dynamic="force-dynamic";
export const metadata:Metadata={title:"Owner Workflow Builder",robots:{index:false,follow:false}};
export default function AutomationPage(){return <AutomationConsole/>;}
