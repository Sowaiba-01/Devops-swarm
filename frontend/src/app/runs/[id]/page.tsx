"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { fetchRun, Run } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { AgentStream } from "@/components/AgentStream";

function MetaField({ label, value, mono = false, link = false }: {
  label: string; value: string | null | undefined; mono?: boolean; link?: boolean;
}) {
  return (
    <div>
      <p className="text-[9px] text-white/25 tracking-widest uppercase mb-1.5">{label}</p>
      {link && value ? (
        <a href={value} target="_blank" rel="noopener noreferrer"
           className="text-indigo-300 hover:text-indigo-200 text-[11px] underline underline-offset-2">
          View PR ↗
        </a>
      ) : (
        <p className={`text-[11px] ${mono ? "font-mono text-indigo-300" : "text-white/60"} truncate`}>
          {value ?? "—"}
        </p>
      )}
    </div>
  );
}

export default function RunDetailPage() {
  const { id }  = useParams<{ id: string }>();
  const router  = useRouter();
  const [run, setRun]     = useState<Run | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let timer: NodeJS.Timeout;
    async function refresh() {
      try {
        const data = await fetchRun(id);
        setRun(data);
        if (data.status === "running") {
          timer = setTimeout(refresh, 5000);
        }
      } catch {
        setError(true);
      }
    }
    refresh();
    return () => clearTimeout(timer);
  }, [id]);

  if (error) {
    return (
      <div className="glass rounded-2xl p-6 border-red-500/20">
        <p className="text-red-400 text-sm font-medium mb-1">Run not found</p>
        <p className="text-white/30 text-xs mb-3">Backend may be unreachable.</p>
        <button onClick={() => router.push("/")} className="text-xs text-indigo-300 hover:text-indigo-200 underline underline-offset-2">
          ← Dashboard
        </button>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex items-center justify-center h-64 text-white/20 text-sm">
        Loading run…
      </div>
    );
  }

  const duration = (() => {
    if (!run.created_at) return "—";
    const ms = (run.completed_at ? new Date(run.completed_at) : new Date()).getTime()
             - new Date(run.created_at).getTime();
    const s = Math.floor(ms / 1000);
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
  })();

  return (
    <div className="space-y-5">

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-[10px] text-white/25">
        <Link href="/" className="hover:text-indigo-300 transition-colors">Dashboard</Link>
        <span className="text-white/15">/</span>
        <span className="text-indigo-300/60 font-mono">{id.slice(0, 8)}…</span>
      </div>

      {/* Run header */}
      <div className="glass rounded-2xl p-5">
        <div className="flex items-start justify-between gap-4 mb-5">
          <div className="flex-1 min-w-0">
            <p className="text-[9px] text-white/25 tracking-widest uppercase mb-1.5">Run Detail</p>
            <h1 className="text-sm font-bold text-white leading-tight">
              <span className="text-white/30 font-mono mr-2">#{run.issue_number}</span>
              {run.issue_title}
            </h1>
            <p className="text-indigo-300/50 font-mono text-[11px] mt-1">{run.repo}</p>
          </div>
          <StatusBadge status={run.status} />
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-4 pt-4 border-t border-white/[0.07]">
          <MetaField label="Branch"     value={run.branch_name}               mono />
          <MetaField label="Iterations" value={`${run.iteration_count ?? 0} / 3`} />
          <MetaField label="Duration"   value={duration} />
          <MetaField label="Pull Request" value={run.pr_url} link />
        </div>

        {run.error_message && (
          <div className="mt-4 glass rounded-xl p-3 border-red-500/20 bg-red-500/5">
            <p className="text-[11px] text-red-400">{run.error_message}</p>
          </div>
        )}

        {run.status === "success" && run.pr_url && (
          <div className="mt-4 glass rounded-xl p-4 border-emerald-500/25 flex items-center justify-between">
            <div>
              <p className="text-emerald-300 font-semibold text-sm">Swarm completed</p>
              <p className="text-white/30 text-[11px] mt-0.5">Draft PR is waiting for your review on GitHub.</p>
            </div>
            <a
              href={run.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="glass rounded-xl px-4 py-2 border-emerald-500/30 hover:border-emerald-400/50 bg-emerald-500/10 hover:bg-emerald-500/15 text-emerald-300 text-xs font-semibold transition-all whitespace-nowrap"
            >
              Review PR ↗
            </a>
          </div>
        )}
      </div>

      {/* Agent stream */}
      <div className="glass rounded-2xl overflow-hidden">
        <div className="px-5 py-3 border-b border-white/[0.07] flex items-center justify-between">
          <span className="text-xs font-medium text-white/50">Agent Stream</span>
          <div className="flex items-center gap-3 text-[9px]">
            <span className="text-violet-400">■ Architect</span>
            <span className="text-indigo-300">■ Coder</span>
            <span className="text-amber-400">■ Reviewer</span>
            <span className="text-emerald-400">■ PR</span>
          </div>
        </div>
        <div className="h-[560px]">
          <AgentStream runId={id} isLive={run.status === "running"} />
        </div>
      </div>

    </div>
  );
}
