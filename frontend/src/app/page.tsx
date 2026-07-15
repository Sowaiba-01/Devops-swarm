"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchRuns, Run } from "@/lib/api";
import { RunHistory } from "@/components/RunHistory";
import { TriggerModal } from "@/components/TriggerModal";

export default function Dashboard() {
  const router = useRouter();
  const [runs, setRuns]       = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  async function loadRuns() {
    try {
      const data = await fetchRuns(30);
      setRuns(data);
      setError(null);
    } catch {
      setError("Cannot reach backend. Is Docker running?");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadRuns();
    function scheduleNext() {
      const hasActive = runs.some((r) => r.status === "running");
      const interval  = hasActive ? 3000 : 10000;
      timerRef.current = setTimeout(async () => {
        if (!document.hidden) await loadRuns();
        scheduleNext();
      }, interval);
    }
    scheduleNext();
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleTriggered(runId: string) {
    setShowModal(false);
    router.push(`/runs/${runId}`);
  }

  const total       = runs.length;
  const success     = runs.filter((r) => r.status === "success").length;
  const running     = runs.filter((r) => r.status === "running").length;
  const successRate = total > 0 ? Math.round((success / total) * 100) : 0;

  const stats = [
    { label: "Total Runs",  value: total,           accent: "text-white/80" },
    { label: "Resolved",    value: success,          accent: "text-emerald-400" },
    { label: "Live",        value: running,          accent: "text-indigo-300" },
    { label: "Success Rate",value: `${successRate}%`,
      accent: successRate >= 80 ? "text-emerald-400" : successRate >= 50 ? "text-amber-400" : "text-red-400" },
  ];

  return (
    <div className="space-y-8">

      {/* Hero header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-indigo-300/50 text-xs tracking-widest uppercase mb-2">
            Agentic DevOps · LangGraph StateGraph
          </p>
          <h1 className="text-2xl font-bold gradient-text leading-tight">
            DevOps Swarm AI
          </h1>
          <p className="text-white/35 text-sm mt-1.5 max-w-lg leading-relaxed">
            Opens a GitHub issue — swarm reads it, writes code, runs tests, opens a PR. Fully autonomous.
            {running > 0 && (
              <span className="ml-2 text-indigo-300 pulse">
                {running} agent{running > 1 ? "s" : ""} running now
              </span>
            )}
          </p>
        </div>

        <button
          onClick={() => setShowModal(true)}
          className="glass rounded-xl px-5 py-2.5 text-sm font-medium text-indigo-200
                     border-indigo-500/30 hover:border-indigo-400/50 hover:bg-indigo-500/10
                     transition-all duration-200"
        >
          Run Swarm →
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {stats.map((s) => (
          <div key={s.label} className="glass rounded-2xl p-5">
            <p className="text-xs text-white/35 mb-2">{s.label}</p>
            <p className={`text-3xl font-bold tabular-nums ${s.accent}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Runs */}
      <div className="glass rounded-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.07]">
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-white/70">Recent Runs</span>
            <div className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-indigo-400 pulse" />
              <span className="text-xs text-indigo-300/50">
                refreshing every {running > 0 ? "3s" : "10s"}
              </span>
            </div>
          </div>
          <span className="text-xs text-white/20">{total} total</span>
        </div>

        <div className="p-5">
          {loading ? (
            <div className="flex items-center justify-center h-32 text-white/20 text-sm">
              Connecting to backend…
            </div>
          ) : error ? (
            <div className="glass rounded-xl p-5 border-red-500/20">
              <p className="font-semibold text-red-400 mb-1 text-sm">Backend unreachable</p>
              <p className="text-white/30 text-xs mb-2">{error}</p>
              <code className="text-indigo-300 text-xs">docker compose up --build</code>
            </div>
          ) : (
            <RunHistory runs={runs} />
          )}
        </div>
      </div>

      {/* How it works */}
      <div className="glass rounded-2xl p-6">
        <p className="text-xs text-white/35 uppercase tracking-widest mb-5">How the swarm works</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { icon: "🏛", agent: "Architect", color: "text-violet-300", bg: "bg-violet-500/10 border-violet-500/20",
              desc: "Reads repo context + issue. Posts implementation plan as GitHub comment." },
            { icon: "⌨", agent: "Coder",     color: "text-indigo-300", bg: "bg-indigo-500/10 border-indigo-500/20",
              desc: "Writes code in E2B sandbox. Searches web. Self-corrects up to 3×." },
            { icon: "🔍", agent: "Reviewer",  color: "text-amber-300",  bg: "bg-amber-500/10 border-amber-500/20",
              desc: "Reads diff. Runs security scan. Returns APPROVED or NEEDS_REVISION." },
            { icon: "🔀", agent: "PR",        color: "text-emerald-300",bg: "bg-emerald-500/10 border-emerald-500/20",
              desc: "Opens draft PR. Posts success comment on the original issue." },
          ].map((a) => (
            <div key={a.agent} className={`rounded-xl p-4 border ${a.bg}`}>
              <div className="text-xl mb-2">{a.icon}</div>
              <p className={`text-xs font-semibold mb-1.5 ${a.color}`}>{a.agent}</p>
              <p className="text-xs text-white/30 leading-relaxed">{a.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {showModal && (
        <TriggerModal onClose={() => setShowModal(false)} onTriggered={handleTriggered} />
      )}
    </div>
  );
}
