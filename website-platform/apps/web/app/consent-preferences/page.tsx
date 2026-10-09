import type {Metadata} from 'next';
import {ConsentControl} from './consent-control';
export const metadata:Metadata={title:'Cookie preferences'};
export default function CookiePreferences(){return <div className="shell narrow reading"><p className="eyebrow">Preferences</p><h1>Cookie preferences</h1><p>A necessary login cookie is used for owner access. This starter does not load optional tracking providers.</p><ConsentControl/></div>}
