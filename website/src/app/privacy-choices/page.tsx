import type { Metadata } from "next";
import Link from "next/link";
export const metadata: Metadata = { title: "Privacy choices", robots: { index: false, follow: false } };
export default function PrivacyChoicesPage() {
  return <section className="page"><h1>Privacy choices</h1>
    <p className="lead">Manage optional analytics and marketing permissions. All optional tracking stays disabled unless you choose otherwise.</p>
    <p>Your decision is stored on this device. It is not a substitute for the approved privacy notice or a jurisdiction-specific consent policy.</p>
    <p>Use the Privacy choices control in the footer to review or change your decision at any time.</p>
    <Link href="/privacy">Read the privacy notice</Link>
  </section>;
}
