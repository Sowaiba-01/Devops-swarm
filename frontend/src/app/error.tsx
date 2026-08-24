"use client";

import { useEffect } from "react";

/**
 * Route-level error boundary. Without one, a render-time exception replaces the
 * whole page with Next's default screen and the user has no way back.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Unhandled render error:", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-md py-20 text-center">
      <h1 className="text-base font-semibold text-ink">Something went wrong</h1>
      <p className="mt-2 text-[13px] text-ink-muted">
        This page failed to render. The rest of the console is still usable.
      </p>
      {error.digest && (
        <p className="mt-2 font-mono text-2xs text-ink-faint">digest {error.digest}</p>
      )}
      <button type="button" onClick={reset} className="btn-primary mt-5">
        Reload this page
      </button>
    </div>
  );
}
