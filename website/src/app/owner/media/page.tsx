import type {Metadata} from "next";
import MediaIntake from "./media-intake";

export const dynamic="force-dynamic";
export const metadata:Metadata={
  title:"Owner Media Quarantine",robots:{index:false,follow:false},
};

export default function MediaPage(){return <MediaIntake/>;}
