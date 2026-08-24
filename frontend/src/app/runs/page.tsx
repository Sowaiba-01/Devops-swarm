"use client";

import { useState } from "react";

import { RunTable } from "@/components/RunTable";
import { ErrorNotice, SkeletonRows } from "@/components/primitives";
import { RunStatus, api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { cx } from "@/lib/format";

const PAGE_SIZE = 25;

const FILTERS: { value: RunStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "running", label: "Running" },
  { value: "success", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

export default function RunsPage() {
  const [filter, setFilter] = useState<RunStatus | "all">("all");
  const [page, setPage] = useState(0);

  const { data, error, loading, refresh } = usePolling(
    () =>
      api.listRuns({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        status: filter === "all" ? undefined : filter,
      }),
    (list) => (list?.runs.some((run) => run.status === "running") ? 4_000 : 20_000),
    // Refetch immediately when the filter or page changes rather than waiting
    // for the next scheduled tick.
    [filter, page],
  );

  const total = data?.page.total ?? 0;
  const shown = data?.runs.length ?? 0;
  const first = total === 0 ? 0 : page * PAGE_SIZE + 1;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-ink">Runs</h1>
          <p className="mt-0.5 text-[13px] text-ink-muted">
            {total > 0
              ? `Showing ${first}–${first + shown - 1} of ${total}`
              : "No runs match this filter"}
          </p>
        </div>

        <div className="flex items-center gap-1" role="group" aria-label="Filter by status">
          {FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                setFilter(option.value);
                // A filter change invalidates the current offset; staying on
                // page 3 of a smaller result set shows an empty table.
                setPage(0);
              }}
              aria-pressed={filter === option.value}
              className={cx(
                "rounded border px-2.5 py-1 text-2xs font-medium transition-colors",
                filter === option.value
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : "border-line text-ink-muted hover:border-line-strong hover:text-ink",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {error && !data ? (
        <ErrorNotice
          title={error.isOffline ? "Backend unreachable" : "Could not load runs"}
          detail={error.message}
          requestId={error.requestId}
          onRetry={refresh}
        />
      ) : (
        <>
          <div className="panel">
            {loading && !data ? (
              <div className="p-3">
                <SkeletonRows rows={8} />
              </div>
            ) : (
              <RunTable runs={data?.runs ?? []} />
            )}
          </div>

          {(page > 0 || data?.page.has_more) && (
            <nav className="flex items-center justify-between" aria-label="Pagination">
              <button
                type="button"
                onClick={() => setPage((value) => Math.max(0, value - 1))}
                disabled={page === 0}
                className="btn-ghost"
              >
                ← Newer
              </button>
              <span className="text-2xs tabular-nums text-ink-faint">Page {page + 1}</span>
              <button
                type="button"
                onClick={() => setPage((value) => value + 1)}
                disabled={!data?.page.has_more}
                className="btn-ghost"
              >
                Older →
              </button>
            </nav>
          )}
        </>
      )}
    </div>
  );
}
