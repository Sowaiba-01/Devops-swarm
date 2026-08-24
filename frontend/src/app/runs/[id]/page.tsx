"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { LogConsole } from "@/components/LogConsole";
import { PipelineTrack } from "@/components/Pipeline";
import { ErrorNotice, StatusPill, TestBadge, VerdictBadge } from "@/components/primitives";
import { ApiError, api, isTerminal } from "@/lib/api";
import { useRun } from "@/lib/hooks";
import { formatAbsolute, formatDuration } from "@/lib/format";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-2xs font-medium uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="mt-1 truncate text-[13px] text-ink">{children}</dd>
    </div>
  );
}

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: run, error, loading, refresh } = useRun(id);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  if (error && !run) {
    return (
      <ErrorNotice
        title={error.status === 404 ? "Run not found" : "Could not load this run"}
        detail={
          error.status === 404
            ? "This run does not exist. It may have been removed, or the link may be wrong."
            : error.message
        }
        requestId={error.requestId}
        onRetry={refresh}
      />
    );
  }

  if (loading && !run) {
    return (
      <div className="space-y-4">
        <div className="skeleton h-28" />
        <div className="skeleton h-[520px]" />
      </div>
    );
  }

  if (!run) return null;

  const live = !isTerminal(run.status);

  async function cancel() {
    setCancelling(true);
    setCancelError(null);
    try {
      await api.cancel(id);
      await refresh();
    } catch (caught) {
      setCancelError(caught instanceof ApiError ? caught.message : "Could not cancel the run");
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-9rem)] flex-col gap-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-2xs text-ink-faint">
        <Link href="/runs" className="hover:text-ink">
          Runs
        </Link>
        <span aria-hidden>/</span>
        <span className="font-mono text-ink-muted">{id.slice(0, 8)}</span>
      </nav>

      <header className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="flex flex-wrap items-baseline gap-2 text-base font-semibold text-ink">
              <span className="font-mono text-2xs text-ink-faint">#{run.issue_number}</span>
              {run.issue_title ?? "(untitled issue)"}
            </h1>
            <p className="mt-1 font-mono text-2xs text-ink-muted">{run.repo}</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <TestBadge passed={run.tests_passed} />
            <VerdictBadge verdict={run.review_verdict} />
            <StatusPill status={run.status} />
            {live && (
              <button
                type="button"
                onClick={cancel}
                disabled={cancelling}
                className="btn-ghost text-fail hover:border-fail/40 hover:text-fail"
              >
                {cancelling ? "Cancelling…" : "Cancel"}
              </button>
            )}
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-4 border-t border-line pt-4 lg:grid-cols-5">
          <Field label="Branch">
            {run.branch_name ? (
              <span className="font-mono text-2xs text-accent">{run.branch_name}</span>
            ) : (
              <span className="text-ink-faint">—</span>
            )}
          </Field>
          <Field label="Correction rounds">
            <span className="tabular-nums">{run.iteration_count}</span>
          </Field>
          <Field label="Duration">
            <span className="tabular-nums">{formatDuration(run.duration_seconds)}</span>
          </Field>
          <Field label="Started">
            <span className="text-2xs">{formatAbsolute(run.created_at)}</span>
          </Field>
          <Field label="Pull request">
            {run.pr_url ? (
              <a
                href={run.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
              >
                Open on GitHub ↗
              </a>
            ) : (
              <span className="text-ink-faint">not opened yet</span>
            )}
          </Field>
        </dl>

        {cancelError && (
          <p role="alert" className="mt-3 text-2xs text-fail">
            {cancelError}
          </p>
        )}

        {run.error_message && (
          <div
            role="alert"
            className="mt-4 rounded border border-fail/30 bg-fail/[0.06] p-3 text-2xs text-ink"
          >
            <span className="font-medium text-fail">Run failed. </span>
            {run.error_message}
          </div>
        )}

        {run.status === "success" && run.tests_passed === false && (
          // The pipeline finishing and the change being correct are different
          // facts, and conflating them was how a broken PR looked like a win.
          <div className="mt-4 rounded border border-warn/30 bg-warn/[0.06] p-3 text-2xs text-ink">
            <span className="font-medium text-warn">Tests did not pass. </span>
            A pull request was opened so a human can inspect the attempt. Do not merge it as-is.
          </div>
        )}
      </header>

      <section aria-label="Pipeline">
        <PipelineTrack run={run} />
      </section>

      <div className="min-h-[440px] flex-1">
        {/* Keyed on the run so navigating between runs remounts the console
            rather than leaving the previous run's events on screen. */}
        <LogConsole key={id} runId={id} live={live} />
      </div>
    </div>
  );
}
