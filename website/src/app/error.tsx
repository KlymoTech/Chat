"use client";
import { useEffect } from "react";
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { /* Avoid logging error details or visitor data into public analytics. */ void error; }, [error]);
  return <section className="container page" role="alert"><h1>We couldn’t load this page</h1><p>Try again. If the problem continues, please return later.</p><button className="button" type="button" onClick={reset}>Try again</button></section>;
}
