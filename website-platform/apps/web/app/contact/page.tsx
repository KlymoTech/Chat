import type {Metadata} from 'next';
import {LeadForm} from './lead-form';
export const metadata:Metadata={title:'Contact',description:'Submit an enquiry'};
export default function Contact(){
 return <><section className="innerhero"><div className="shell narrow"><p className="eyebrow">Talk to us</p><h1>How can we help?</h1><p>Share a few details and send an enquiry.</p></div></section><section className="section"><div className="shell narrow"><div className="contact-card"><h2>Send an enquiry</h2><p>Your information will be used to handle the request. Marketing opt-in is separate and optional.</p><LeadForm/></div></div></section></>;
}
