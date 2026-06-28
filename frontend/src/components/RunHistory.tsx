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

const AGENT_STEPS = ["ARCHITECT", "CODER", "REVIEWER", "PR"];

function AgentPipeline({ status, iterations }: { status: string; iterations: number }) {
  const completedSteps =
    status === "failed"  ? Math.min(iterations + 1, 2) :
    status === "success" ? 4 :
    status === "running" ? Math.min(iterations + 1, 4) : 0;

  return (
    <div className="flex gap-1 mt-2">
      {AGENT_STEPS.map((step, i) => {
        const done    = i < completedSteps;
        const active  = i === completedSteps - 1 && status === "running";
        const failed  = status === "failed" && i === completedSteps - 1;
        return (
          <span
            key={step}
            className={`text-[8px] px-1.5 py-0.5 border rounded-sm tracking-wider font-bold
              ${failed  ? "border-[#ff444430] text-[#ff6b6b70]" :
                active  ? "border-[#38bdf840] text-[#38bdf8] neon-pulse" :
                done    ? "border-[#00ff8730] text-[#00ff8780]" :
                          "border-white/5 text-white/15"}`}
          >
            {step}{done && !active && !failed ? " ✓" : ""}
          </span>
        );
      })}
    </div>
  );
}

export function RunHistory({ runs }: { runs: Run[] }) {
  if (runs.length === 0) {
    return (
      <div className="text-center py-20 text-white/20">
        <p className="text-[10px] tracking-widest uppercase mb-2">// no runs yet</p>
        <p className="text-xs">Click <span className="text-[#00ff87]">[ RUN SWARM ]</span> to trigger your first run.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0">
      {/* Timeline feed */}
      <div className="space-y-2 mb-6">
        <div className="text-[9px] text-[#00ff8550] tracking-widest uppercase mb-3">// activity feed</div>
        {runs.map((run, idx) => {
          const isLast = idx === runs.length - 1;
          return (
            <div key={run.id} className={`relative pl-5 ${!isLast ? "timeline-line" : ""}`}>
              {/* Timeline dot */}
              <div
                className={`absolute left-0 top-3.5 w-2.5 h-2.5 rounded-full border
                  ${run.status === "running" ? "border-[#38bdf8] bg-[#38bdf8] neon-pulse" :
                    run.status === "success" ? "border-[#00ff87] bg-[#00ff87]" :
                    run.status === "failed"  ? "border-[#ff4444] bg-[#ff444440]" :
                                              "border-white/20 bg-white/5"}`}
              />

              <Link href={`/runs/${run.id}`}>
                <div
                  className={`border rounded-md p-3 transition-all cursor-pointer
                    ${run.status === "running" ? "border-[#38bdf835] bg-[#38bdf808] hover:border-[#38bdf860]" :
                      run.status === "success" ? "border-[#00ff8728] bg-[#00ff8705] hover:border-[#00ff8750]" :
                      run.status === "failed"  ? "border-[#ff444418] bg-[#ff44440a] hover:border-[#ff444435]" :
                                                "border-white/8 bg-white/3 hover:border-white/15"}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-[10px] font-bold
                          ${run.status === "running" ? "text-[#38bdf870]" :
                            run.status === "success" ? "text-[#00ff8760]" :
                            "text-[#ff6b6b60]"}`}>
                          #{run.issue_number}
                        </span>
                        <span className={`text-xs font-semibold truncate
                          ${run.status === "running" ? "text-[#38bdf8]" :
                            run.status === "success" ? "text-[#00ff87]" :
                            run.status === "failed"  ? "text-[#ff6b6b70]" :
                            "text-white/60"}`}>
                          {run.issue_title.length > 60 ? run.issue_title.slice(0, 60) + "…" : run.issue_title}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-1">
                        <span className={`text-[9px] tracking-wider
                          ${run.status === "running" ? "text-[#38bdf850]" :
                            run.status === "success" ? "text-[#00ff8750]" :
                            "text-[#ff6b6b40]"}`}>
                          {run.repo}
                        </span>
                        <span className="text-white/10 text-[9px]">·</span>
                        <span className="text-white/20 text-[9px]">{elapsed(run.created_at, run.completed_at)}</span>
                        <span className="text-white/10 text-[9px]">·</span>
                        <span className="text-white/20 text-[9px]">{relativeTime(run.created_at)}</span>
                        {run.pr_url && (
                          <>
                            <span className="text-white/10 text-[9px]">·</span>
                            <a
                              href={run.pr_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="text-[9px] text-[#38bdf8] hover:text-[#38bdf8] underline underline-offset-2"
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
      <div className="border border-[#00ff8718] rounded-md overflow-hidden">
        <div className="px-3 py-2 bg-[#00ff8708] border-b border-[#00ff8715]">
          <span className="text-[9px] text-[#00ff8560] tracking-widest uppercase">// run table</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[10px]">
            <thead>
              <tr className="border-b border-white/5">
                {["Issue", "Repo", "Status", "Loops", "Time", "PR"].map((h) => (
                  <th key={h} className="text-left px-3 py-2 text-[9px] text-white/20 tracking-widest uppercase font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-b border-white/5 hover:bg-white/3 transition-colors">
                  <td className="px-3 py-2">
                    <Link href={`/runs/${run.id}`} className="flex items-center gap-1.5">
                      <span className="text-white/30">#{run.issue_number}</span>
                      <span className={`font-semibold truncate max-w-[180px] block
                        ${run.status === "running" ? "text-[#38bdf8]" :
                          run.status === "success" ? "text-[#00ff87]" :
                          run.status === "failed"  ? "text-[#ff6b6b70]" : "text-white/50"}`}>
                        {run.issue_title.length > 30 ? run.issue_title.slice(0, 30) + "…" : run.issue_title}
                      </span>
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-white/30 font-mono">{run.repo.split("/")[1] ?? run.repo}</td>
                  <td className="px-3 py-2"><StatusBadge status={run.status} /></td>
                  <td className="px-3 py-2 text-white/30 tabular-nums">
                    {run.iteration_count ?? 0}<span className="text-white/15">/3</span>
                  </td>
                  <td className="px-3 py-2 text-white/30 tabular-nums whitespace-nowrap">{elapsed(run.created_at, run.completed_at)}</td>
                  <td className="px-3 py-2">
                    {run.pr_url ? (
                      <a href={run.pr_url} target="_blank" rel="noopener noreferrer"
                         className="text-[#38bdf8] hover:text-[#38bdf8] underline underline-offset-2">
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
