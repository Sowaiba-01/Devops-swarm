"use client";

import { RunStatus } from "@/lib/api";
import { cx } from "@/lib/format";

/**
 * Status colour is load-bearing, so it is never the *only* signal: each pill
 * carries a shape as well as a hue, and the label is always spelled out.
 */
const STATUS: Record<RunStatus, { label: string; tone: string; glyph: string }> = {
  queued: { label: "Queued", tone: "text-ink-muted border-line bg-raised", glyph: "○" },
  running: { label: "Running", tone: "text-live border-live/30 bg-live/10", glyph: "●" },
  success: { label: "Completed", tone: "text-pass border-pass/30 bg-pass/10", glyph: "✓" },
  failed: { label: "Failed", tone: "text-fail border-fail/30 bg-fail/10", glyph: "✕" },
  cancelled: { label: "Cancelled", tone: "text-ink-faint border-line bg-raised", glyph: "⊘" },
};

export function StatusPill({ status, className }: { status: RunStatus; className?: string }) {
  const config = STATUS[status] ?? STATUS.queued;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5",
        "text-2xs font-medium",
        config.tone,
        className,
      )}
    >
      <span
        aria-hidden
        className={cx("text-[9px] leading-none", status === "running" && "animate-breathe")}
      >
        {config.glyph}
      </span>
      {config.label}
    </span>
  );
}

/** Secondary outcome badge: the pipeline can complete with failing tests. */
export function TestBadge({ passed }: { passed: boolean | null }) {
  if (passed == null) return <span className="text-2xs text-ink-faint">tests n/a</span>;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs font-medium",
        passed ? "border-pass/30 bg-pass/10 text-pass" : "border-warn/30 bg-warn/10 text-warn",
      )}
    >
      {passed ? "tests pass" : "tests fail"}
    </span>
  );
}

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict || verdict === "UNKNOWN") return null;
  const approved = verdict === "APPROVED";
  return (
    <span
      className={cx(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-2xs font-medium",
        approved ? "border-pass/30 bg-pass/10 text-pass" : "border-warn/30 bg-warn/10 text-warn",
      )}
    >
      {approved ? "approved" : "needs revision"}
    </span>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "live" | "pass" | "fail";
}) {
  const toneClass = {
    default: "text-ink",
    live: "text-live",
    pass: "text-pass",
    fail: "text-fail",
  }[tone];

  return (
    <div className="panel p-4">
      <p className="text-2xs font-medium uppercase tracking-wide text-ink-faint">{label}</p>
      <p className={cx("mt-2 text-2xl font-semibold tabular-nums tracking-tight", toneClass)}>
        {value}
      </p>
      {hint && <p className="mt-0.5 text-2xs text-ink-faint">{hint}</p>}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mt-1 max-w-sm text-[13px] text-ink-muted">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNotice({
  title,
  detail,
  requestId,
  onRetry,
}: {
  title: string;
  detail: string;
  requestId?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-md border border-fail/30 bg-fail/[0.06] p-4 text-[13px]"
    >
      <p className="font-medium text-fail">{title}</p>
      <p className="mt-1 text-ink-muted">{detail}</p>
      {requestId && (
        // Surfacing the id lets a failure be matched to a server log line.
        <p className="mt-2 font-mono text-2xs text-ink-faint">request {requestId}</p>
      )}
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-ghost mt-3">
          Try again
        </button>
      )}
    </div>
  );
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-px" aria-hidden>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="skeleton h-11" />
      ))}
    </div>
  );
}
