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
  const failed      = runs.filter((r) => r.status === "failed").length;
  const successRate = total > 0 ? Math.round((success / total) * 100) : 0;

  return (
    <div className="space-y-5">

      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[9px] text-[#00ff8550] tracking-widest uppercase mb-1">// dashboard</div>
          <h1 className="text-base font-bold text-white tracking-wider">
            AUTONOMOUS DEVOPS SWARM
          </h1>
          <p className="text-white/25 text-[10px] mt-0.5 tracking-wide">
            Multi-agent LangGraph system that resolves GitHub issues autonomously.
            {running > 0 && (
              <span className="ml-2 text-[#38bdf8] neon-pulse">
                {running} agent{running > 1 ? "s" : ""} working now···
              </span>
            )}
          </p>
        </div>

        <button
          onClick={() => setShowModal(true)}
          className="border border-[#00ff8740] bg-[#00ff8710] hover:bg-[#00ff8720] text-[#00ff87] font-bold text-[10px] tracking-widest px-4 py-2 rounded-sm transition-all font-mono"
        >
          [ RUN SWARM ]
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {[
          { label: "TOTAL", value: total,          color: "text-white/70",   border: "border-white/10" },
          { label: "OK",    value: success,         color: "text-[#00ff87]", border: "border-[#00ff8740]", bg: "bg-[#00ff8708]" },
          { label: "LIVE",  value: running,         color: "text-[#38bdf8]", border: "border-[#38bdf840]", bg: "bg-[#38bdf808]" },
          { label: "RATE",  value: `${successRate}%`,
            color: successRate >= 80 ? "text-[#00ff87]" : successRate >= 50 ? "text-[#f59e0b]" : "text-[#ff6b6b]",
            border: "border-white/10" },
        ].map((s) => (
          <div
            key={s.label}
            className={`border rounded-sm p-4 ${s.border} ${(s as any).bg ?? ""}`}
          >
            <p className="text-[8px] text-white/25 tracking-[.18em] uppercase mb-2">{s.label}</p>
            <p className={`text-3xl font-bold tabular-nums leading-none ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Main panel */}
      <div className="border border-[#00ff8718] rounded-md">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#00ff8715] bg-[#00ff8705]">
          <div className="flex items-center gap-3">
            <span className="text-[9px] text-[#00ff8560] tracking-widest uppercase">// recent runs</span>
            <div className="flex items-center gap-1">
              <span className="h-1 w-1 rounded-full bg-[#00ff87] neon-pulse" />
              <span className="text-[9px] text-[#00ff8540] font-mono">
                auto-refresh {running > 0 ? "3s" : "10s"}
              </span>
            </div>
          </div>
          <span className="text-[9px] text-white/15 font-mono">{total} total</span>
        </div>

        <div className="p-4">
          {loading ? (
            <div className="flex items-center justify-center h-32 text-white/20 font-mono text-xs">
              <span className="tracking-widest">// connecting to backend···</span>
            </div>
          ) : error ? (
            <div className="bg-[#ff444408] border border-[#ff444425] rounded-sm p-4 text-[10px] text-[#ff6b6b] font-mono">
              <p className="font-bold tracking-wider mb-1">ERROR: BACKEND UNREACHABLE</p>
              <p className="text-[#ff6b6b60] mb-2">{error}</p>
              <p className="text-white/20">
                Run: <code className="text-[#38bdf8]">docker compose up --build</code>
              </p>
            </div>
          ) : (
            <RunHistory runs={runs} />
          )}
        </div>
      </div>

      {/* How it works */}
      <div className="border border-white/5 rounded-sm p-4">
        <div className="text-[9px] text-white/20 tracking-widest uppercase mb-3">// how it works</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { agent: "ARCHITECT", color: "border-[#a855f730] text-[#a855f7]", desc: "Reads issue + repo structure. Produces a step-by-step implementation plan." },
            { agent: "CODER",     color: "border-[#38bdf830] text-[#38bdf8]", desc: "Implements plan in E2B cloud sandbox. Runs tests. Self-corrects up to 3×." },
            { agent: "REVIEWER",  color: "border-[#f59e0b30] text-[#f59e0b]", desc: "Reads the git diff. Runs security scan. Produces APPROVED or NEEDS_REVISION." },
            { agent: "PR",        color: "border-[#00ff8730] text-[#00ff87]", desc: "Pushes branch to GitHub. Opens a draft PR with test results and review notes." },
          ].map((a) => (
            <div key={a.agent} className={`border rounded-sm p-3 ${a.color.split(" ")[0]}`}>
              <p className={`text-[9px] font-bold tracking-widest mb-2 ${a.color.split(" ")[1]}`}>{a.agent}</p>
              <p className="text-[9px] text-white/30 leading-relaxed">{a.desc}</p>
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
