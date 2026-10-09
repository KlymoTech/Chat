import type { Metadata } from "next";
import OwnerConsole from "./owner-console";
export const dynamic="force-dynamic";
export const metadata:Metadata={title:"Owner CMS",robots:{index:false,follow:false},alternates:{canonical:undefined}};
export default function OwnerPage(){return <OwnerConsole/>;}
