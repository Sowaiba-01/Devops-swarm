import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md py-20 text-center">
      <p className="font-mono text-2xs text-ink-faint">404</p>
      <h1 className="mt-1 text-base font-semibold text-ink">Page not found</h1>
      <p className="mt-2 text-[13px] text-ink-muted">
        That URL does not match anything in the console.
      </p>
      <Link href="/" className="btn-primary mt-5">
        Back to overview
      </Link>
    </div>
  );
}
