import Link from "next/link";
export default function NotFound() {
  return <section className="page" aria-labelledby="not-found-title"><p className="eyebrow">404</p><h1 id="not-found-title">Page not found</h1><p className="lead">That page may have moved or the address may be incorrect.</p><Link className="button" href="/">Return to homepage</Link></section>;
}
