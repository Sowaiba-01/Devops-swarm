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
      <p className="text-[8px] text-white/20 tracking-[.18em] uppercase mb-1">{label}</p>
      {link && value ? (
        <a href={value} target="_blank" rel="noopener noreferrer"
           className="text-[#38bdf8] hover:text-[#38bdf8] text-[10px] underline underline-offset-2">
          View PR ↗
        </a>
      ) : (
        <p className={`text-[10px] ${mono ? "font-mono text-[#00ff87]" : "text-white/60"} truncate`}>
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
      <div className="bg-[#ff444408] border border-[#ff444425] rounded-sm p-6 text-[#ff6b6b] text-[10px] font-mono">
        ERROR: Run not found or backend unreachable.
        <button onClick={() => router.push("/")} className="ml-3 underline text-[#ff6b6b80]">← back</button>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex items-center justify-center h-64 text-white/20 font-mono text-[10px] tracking-widest">
        // loading run···
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
    <div className="space-y-4">

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-[9px] text-white/20 font-mono tracking-wider">
        <Link href="/" className="hover:text-[#00ff87] transition-colors">DASHBOARD</Link>
        <span className="text-white/10">/</span>
        <span className="text-[#00ff8760]">{id.slice(0, 8)}···</span>
      </div>

      {/* Run header */}
      <div className="border border-[#00ff8720] rounded-sm p-5 bg-[#00ff8705]">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="flex-1 min-w-0">
            <div className="text-[8px] text-[#00ff8550] tracking-widest uppercase mb-1">// run detail</div>
            <h1 className="text-sm font-bold text-white tracking-wide leading-tight">
              <span className="text-[#00ff8770] mr-2 font-mono">#{run.issue_number}</span>
              {run.issue_title}
            </h1>
            <p className="text-[#00ff8750] font-mono text-[10px] mt-1">{run.repo}</p>
          </div>
          <StatusBadge status={run.status} />
        </div>

        {/* Meta grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-3 pt-4 border-t border-[#00ff8715]">
          <MetaField label="Branch" value={run.branch_name} mono />
          <MetaField label="Iterations" value={`${run.iteration_count ?? 0} / 3`} />
          <MetaField label="Duration" value={duration} />
          <MetaField label="Pull Request" value={run.pr_url} link />
        </div>

        {/* Error */}
        {run.error_message && (
          <div className="mt-4 bg-[#ff444408] border border-[#ff444425] rounded-sm p-3 text-[10px] text-[#ff6b6b] font-mono">
            ERROR: {run.error_message}
          </div>
        )}

        {/* Success */}
        {run.status === "success" && run.pr_url && (
          <div className="mt-4 bg-[#00ff8708] border border-[#00ff8730] rounded-sm p-3 flex items-center justify-between">
            <div>
              <p className="text-[#00ff87] font-bold text-[10px] tracking-wider">SWARM COMPLETED SUCCESSFULLY</p>
              <p className="text-[#00ff8760] text-[9px] mt-0.5">Draft PR is waiting for your review on GitHub.</p>
            </div>
            <a
              href={run.pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="border border-[#00ff8740] bg-[#00ff8715] hover:bg-[#00ff8725] text-[#00ff87] text-[9px] font-bold tracking-widest px-3 py-1.5 rounded-sm transition-all font-mono whitespace-nowrap"
            >
              [ REVIEW PR ]
            </a>
          </div>
        )}
      </div>

      {/* Agent stream */}
      <div className="border border-[#00ff8718] rounded-sm overflow-hidden">
        <div className="px-4 py-2.5 border-b border-[#00ff8715] bg-[#0a0a0a] flex items-center justify-between">
          <span className="text-[9px] text-[#00ff8560] tracking-widest uppercase">// agent thought stream</span>
          <div className="flex items-center gap-3 text-[8px] tracking-widest font-mono">
            <span className="text-[#a855f7]">■ ARCHITECT</span>
            <span className="text-[#38bdf8]">■ CODER</span>
            <span className="text-[#f59e0b]">■ REVIEWER</span>
            <span className="text-[#00ff87]">■ PR</span>
          </div>
        </div>

        <div className="h-[560px]">
          <AgentStream runId={id} isLive={run.status === "running"} />
        </div>
      </div>

    </div>
  );
}
