"use client";

import Link from "next/link";

import { RunTable } from "@/components/RunTable";
import { ErrorNotice, SkeletonRows, Stat } from "@/components/primitives";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/hooks";

interface Overview {
  stats: Awaited<ReturnType<typeof api.stats>>;
  recent: Awaited<ReturnType<typeof api.listRuns>>;
}

export default function OverviewPage() {
  const { data, error, loading, refresh } = usePolling<Overview>(
    async () => {
      const [stats, recent] = await Promise.all([api.stats(), api.listRuns({ limit: 8 })]);
      return { stats, recent };
    },
    // Poll quickly only while something is actually executing. The previous
    // dashboard read this from a stale closure and so always used the slow path.
    (overview) => ((overview?.stats.running ?? 0) > 0 ? 3_000 : 15_000),
    [],
  );

  if (error && !data) {
    return (
      <ErrorNotice
        title={error.isOffline ? "Backend unreachable" : "Could not load the dashboard"}
        detail={
          error.isOffline
            ? "The API did not respond. Start the stack with `docker compose up --build`, then retry."
            : error.message
        }
        requestId={error.requestId}
        onRetry={refresh}
      />
    );
  }

  const stats = data?.stats;
  const running = stats?.running ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-ink">Overview</h1>
        <p className="mt-1 max-w-2xl text-[13px] text-ink-muted">
          Open a GitHub issue and the swarm reads the repository, writes a plan, implements it in a
          sandbox, runs the tests, reviews its own diff, and opens a draft pull request.
          {running > 0 && (
            <span className="ml-1 font-medium text-live">
              {running} run{running === 1 ? "" : "s"} executing now.
            </span>
          )}
        </p>
      </div>

      <section aria-label="Run statistics" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {loading && !stats ? (
          Array.from({ length: 4 }).map((_, index) => <div key={index} className="skeleton h-[92px]" />)
        ) : (
          <>
            <Stat label="Total runs" value={stats?.total ?? 0} />
            <Stat label="Executing" value={running} tone={running > 0 ? "live" : "default"} />
            <Stat
              label="Completed"
              value={stats?.success ?? 0}
              tone="pass"
              hint={`${stats?.failed ?? 0} failed`}
            />
            <Stat
              label="Success rate"
              value={`${stats?.success_rate ?? 0}%`}
              // Computed server-side across all runs, not just the loaded page.
              hint="across all finished runs"
              tone={
                (stats?.success_rate ?? 0) >= 70
                  ? "pass"
                  : (stats?.success_rate ?? 0) >= 40
                    ? "default"
                    : "fail"
              }
            />
          </>
        )}
      </section>

      <section className="panel" aria-label="Recent runs">
        <header className="flex items-center justify-between border-b border-line px-3 py-2.5">
          <h2 className="text-[13px] font-medium text-ink">Recent runs</h2>
          <Link href="/runs" className="text-2xs font-medium text-accent hover:underline">
            View all →
          </Link>
        </header>
        {loading && !data ? (
          <div className="p-3">
            <SkeletonRows rows={5} />
          </div>
        ) : (
          <RunTable runs={data?.recent.runs ?? []} />
        )}
      </section>

      <section className="panel p-4" aria-label="How the swarm works">
        <h2 className="text-[13px] font-medium text-ink">How a run proceeds</h2>
        <ol className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            {
              step: "01",
              title: "Architect",
              body: "Reads the file tree and the files the issue touches, then posts an implementation plan as an issue comment before any code is written.",
            },
            {
              step: "02",
              title: "Coder",
              body: "Clones into an isolated E2B sandbox, implements the plan, lints, commits, and runs the test suite — retrying up to three times on failure.",
            },
            {
              step: "03",
              title: "Reviewer",
              body: "Reads the full diff against the base commit, runs a security scan, and returns an explicit approval or a revision request.",
            },
            {
              step: "04",
              title: "Pull request",
              body: "Opens a draft PR stating the test outcome and the review verdict, then comments the link on the original issue.",
            },
          ].map((item) => (
            <li key={item.step} className="rounded border border-line bg-canvas p-3">
              <span className="font-mono text-2xs text-accent">{item.step}</span>
              <p className="mt-1 text-[13px] font-medium text-ink">{item.title}</p>
              <p className="mt-1 text-2xs leading-relaxed text-ink-muted">{item.body}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
