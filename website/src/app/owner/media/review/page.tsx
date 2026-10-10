import type {Metadata} from "next";
import MediaReviewConsole from "./review-console";
export const dynamic="force-dynamic";
export const metadata:Metadata={
  title:"Independent Media Review",robots:{index:false,follow:false},
};
export default function ReviewPage(){return <MediaReviewConsole/>;}
