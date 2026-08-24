"use client";

import Link from "next/link";

import { Run } from "@/lib/api";
import { cx, formatDuration, formatRelative, truncate } from "@/lib/format";

import { PipelineTrack } from "./Pipeline";
import { EmptyState, StatusPill, TestBadge } from "./primitives";

function RunRow({ run }: { run: Run }) {
  return (
    <tr className="group border-t border-line transition-colors hover:bg-raised/60">
      <td className="td">
        {/* The whole title cell is the link target, so the hit area matches
            what the row looks like rather than just the text glyphs. */}
        <Link href={`/runs/${run.id}`} className="block focus-visible:outline-offset-4">
          <span className="flex items-baseline gap-2">
            <span className="font-mono text-2xs text-ink-faint">#{run.issue_number}</span>
            <span className="text-[13px] font-medium text-ink group-hover:text-accent">
              {truncate(run.issue_title ?? "(untitled)", 64)}
            </span>
          </span>
          <span className="mt-0.5 block font-mono text-2xs text-ink-faint">{run.repo}</span>
        </Link>
      </td>

      <td className="td">
        <StatusPill status={run.status} />
      </td>

      <td className="td hidden md:table-cell">
        <PipelineTrack run={run} compact />
      </td>

      <td className="td hidden text-2xs text-ink-muted sm:table-cell">
        <TestBadge passed={run.tests_passed} />
      </td>

      <td className="td hidden tabular-nums text-2xs text-ink-muted lg:table-cell">
        {run.iteration_count}
      </td>

      <td className="td whitespace-nowrap tabular-nums text-2xs text-ink-muted">
        {formatDuration(run.duration_seconds)}
      </td>

      <td className="td hidden whitespace-nowrap text-2xs text-ink-faint sm:table-cell">
        <time dateTime={run.created_at ?? undefined}>{formatRelative(run.created_at)}</time>
      </td>

      <td className="td text-right">
        {run.pr_url ? (
          <a
            href={run.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-2xs font-medium text-accent hover:underline"
          >
            PR ↗
          </a>
        ) : (
          <span className="text-2xs text-ink-faint">—</span>
        )}
      </td>
    </tr>
  );
}

export function RunTable({
  runs,
  emptyAction,
  className,
}: {
  runs: Run[];
  emptyAction?: React.ReactNode;
  className?: string;
}) {
  if (runs.length === 0) {
    return (
      <EmptyState
        title="No runs yet"
        description="Trigger a run against a GitHub issue, or open an issue on a connected repository to start one automatically."
        action={emptyAction}
      />
    );
  }

  return (
    <div className={cx("overflow-x-auto", className)}>
      <table className="w-full min-w-[720px] border-collapse">
        <caption className="sr-only">Swarm runs, newest first</caption>
        <thead>
          <tr>
            <th className="th">Issue</th>
            <th className="th">Status</th>
            <th className="th hidden md:table-cell">Pipeline</th>
            <th className="th hidden sm:table-cell">Tests</th>
            <th className="th hidden lg:table-cell">Rounds</th>
            <th className="th">Duration</th>
            <th className="th hidden sm:table-cell">Started</th>
            <th className="th text-right">Output</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
