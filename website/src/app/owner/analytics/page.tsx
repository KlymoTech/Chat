import type {Metadata} from "next";
import AnalyticsOverview from "./overview";
export const dynamic="force-dynamic";
export const metadata:Metadata={title:"Owner Analytics",robots:{index:false,follow:false}};
export default function AnalyticsPage(){return <AnalyticsOverview/>;}
