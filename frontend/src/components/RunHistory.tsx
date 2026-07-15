"use client";

import Link from "next/link";
import { Run } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

function elapsed(start: string | null, end: string | null): string {
  if (!start) return "—";
  const ms = (end ? new Date(end) : new Date()).getTime() - new Date(start).getTime();
  const s  = Math.floor(ms / 1000);
  if (s < 60)   return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h`;
}
function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60)    return "just now";
  if (s < 3600)  return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

const AGENT_STEPS = [
  { name: "Architect", color: "violet" },
  { name: "Coder",     color: "indigo" },
  { name: "Reviewer",  color: "amber"  },
  { name: "PR",        color: "emerald"},
];

const STEP_STYLES = {
  violet:  { done: "border-violet-500/40 text-violet-300/80 bg-violet-500/10",  active: "border-violet-400/60 text-violet-300 bg-violet-500/15 pulse", pending: "border-white/8 text-white/20" },
  indigo:  { done: "border-indigo-500/40 text-indigo-300/80 bg-indigo-500/10",  active: "border-indigo-400/60 text-indigo-300 bg-indigo-500/15 pulse", pending: "border-white/8 text-white/20" },
  amber:   { done: "border-amber-500/40 text-amber-300/80 bg-amber-500/10",     active: "border-amber-400/60 text-amber-300 bg-amber-500/15 pulse",   pending: "border-white/8 text-white/20" },
  emerald: { done: "border-emerald-500/40 text-emerald-300/80 bg-emerald-500/10",active:"border-emerald-400/60 text-emerald-300 bg-emerald-500/15 pulse",pending:"border-white/8 text-white/20"},
};

function AgentPipeline({ status, iterations }: { status: string; iterations: number }) {
  const completedSteps =
    status === "failed"  ? Math.min(iterations + 1, 2) :
    status === "success" ? 4 :
    status === "running" ? Math.min(iterations + 1, 4) : 0;

  return (
    <div className="flex gap-1 mt-2.5">
      {AGENT_STEPS.map(({ name, color }, i) => {
        const done   = i < completedSteps;
        const active = i === completedSteps - 1 && status === "running";
        const failed = status === "failed" && i === completedSteps - 1;
        const styles = STEP_STYLES[color as keyof typeof STEP_STYLES];
        const cls    = failed  ? "border-red-500/30 text-red-400/60 bg-red-500/5" :
                       active  ? styles.active :
                       done    ? styles.done :
                                 styles.pending;
        return (
          <span key={name} className={`text-[9px] px-2 py-0.5 border rounded-full font-medium transition-all ${cls}`}>
            {name}{done && !active && !failed ? " ✓" : ""}
          </span>
        );
      })}
    </div>
  );
}

export function RunHistory({ runs }: { runs: Run[] }) {
  if (runs.length === 0) {
    return (
      <div className="text-center py-16 text-white/20">
        <p className="text-xs mb-2">No runs yet</p>
        <p className="text-[11px] text-white/15">Click <span className="text-indigo-300">Run Swarm →</span> to trigger your first run.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Timeline feed */}
      <div className="space-y-2">
        {runs.map((run, idx) => {
          const isLast = idx === runs.length - 1;
          const dotColor =
            run.status === "running" ? "border-indigo-400 bg-indigo-400 pulse" :
            run.status === "success" ? "border-emerald-400 bg-emerald-400" :
            run.status === "failed"  ? "border-red-500 bg-red-500/40" :
                                       "border-white/20 bg-white/5";
          const cardColor =
            run.status === "running" ? "border-indigo-500/25 hover:border-indigo-400/40" :
            run.status === "success" ? "border-emerald-500/20 hover:border-emerald-400/35" :
            run.status === "failed"  ? "border-red-500/20 hover:border-red-400/35" :
                                       "border-white/8 hover:border-white/15";
          const titleColor =
            run.status === "running" ? "text-indigo-300" :
            run.status === "success" ? "text-emerald-300" :
            run.status === "failed"  ? "text-red-400/70" :
                                       "text-white/60";

          return (
            <div key={run.id} className={`relative pl-5 ${!isLast ? "timeline-line" : ""}`}>
              <div className={`absolute left-0 top-4 w-2.5 h-2.5 rounded-full border ${dotColor}`} />

              <Link href={`/runs/${run.id}`}>
                <div className={`glass rounded-xl p-4 transition-all cursor-pointer ${cardColor}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-[10px] font-mono text-white/25">#{run.issue_number}</span>
                        <span className={`text-xs font-semibold truncate ${titleColor}`}>
                          {run.issue_title.length > 60 ? run.issue_title.slice(0, 60) + "…" : run.issue_title}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-white/25">
                        <span className="font-mono">{run.repo}</span>
                        <span className="text-white/10">·</span>
                        <span>{elapsed(run.created_at, run.completed_at)}</span>
                        <span className="text-white/10">·</span>
                        <span>{relativeTime(run.created_at)}</span>
                        {run.pr_url && (
                          <>
                            <span className="text-white/10">·</span>
                            <a
                              href={run.pr_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-indigo-300 hover:text-indigo-200 underline underline-offset-2"
                            >
                              PR ↗
                            </a>
                          </>
                        )}
                      </div>
                      <AgentPipeline status={run.status} iterations={run.iteration_count ?? 0} />
                    </div>
                    <StatusBadge status={run.status} />
                  </div>
                </div>
              </Link>
            </div>
          );
        })}
      </div>

      {/* Compact table */}
      <div className="glass rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-white/[0.07]">
          <span className="text-[10px] text-white/30 tracking-widest uppercase">All Runs</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-white/[0.06]">
                {["Issue", "Repo", "Status", "Loops", "Time", "PR"].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 text-[9px] text-white/20 tracking-widest uppercase font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                  <td className="px-4 py-2.5">
                    <Link href={`/runs/${run.id}`} className="flex items-center gap-2">
                      <span className="text-white/25 font-mono text-[10px]">#{run.issue_number}</span>
                      <span className={`font-medium truncate max-w-[180px] block
                        ${run.status === "running" ? "text-indigo-300" :
                          run.status === "success" ? "text-emerald-300" :
                          run.status === "failed"  ? "text-red-400/60" : "text-white/50"}`}>
                        {run.issue_title.length > 30 ? run.issue_title.slice(0, 30) + "…" : run.issue_title}
                      </span>
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 text-white/30 font-mono text-[10px]">{run.repo.split("/")[1] ?? run.repo}</td>
                  <td className="px-4 py-2.5"><StatusBadge status={run.status} /></td>
                  <td className="px-4 py-2.5 text-white/30 tabular-nums">
                    {run.iteration_count ?? 0}<span className="text-white/15">/3</span>
                  </td>
                  <td className="px-4 py-2.5 text-white/30 tabular-nums whitespace-nowrap">{elapsed(run.created_at, run.completed_at)}</td>
                  <td className="px-4 py-2.5">
                    {run.pr_url ? (
                      <a href={run.pr_url} target="_blank" rel="noopener noreferrer"
                         className="text-indigo-300 hover:text-indigo-200 underline underline-offset-2">
                        ↗
                      </a>
                    ) : <span className="text-white/15">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
