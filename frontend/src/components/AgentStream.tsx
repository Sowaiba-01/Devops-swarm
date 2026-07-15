"use client";

import { useEffect, useRef, useState } from "react";
import { fetchLogs, openStream } from "@/lib/api";

const AGENT_COLOR: Record<string, string> = {
  architect: "text-violet-400",
  coder:     "text-indigo-300",
  reviewer:  "text-amber-400",
  supervisor:"text-white/20",
  system:    "text-white/15",
  pr:        "text-emerald-400",
};
const TYPE_PREFIX: Record<string, string> = {
  thought:     "THINK  ",
  tool_call:   "TOOL ▸ ",
  tool_result: "RESULT ",
  status:      "STATUS ",
  error:       "ERROR  ",
};

interface StreamEvent {
  type: string;
  agent?: string;
  content?: string;
  tool?: string;
  args?: Record<string, unknown>;
  timestamp?: string;
}

function LogRow({ agent, log_type, content, timestamp }: {
  agent: string; log_type: string; content: string; timestamp: string | null;
}) {
  const color  = AGENT_COLOR[agent] ?? "text-white/40";
  const prefix = TYPE_PREFIX[log_type] ?? "       ";
  const isError    = log_type === "error";
  const isToolCall = log_type === "tool_call";
  const isResult   = log_type === "tool_result";

  const contentColor =
    isError    ? "text-red-400" :
    isToolCall ? "text-indigo-300" :
    isResult   ? "text-white/40"  :
                 "text-white/60";

  return (
    <div className={`flex gap-2 items-start py-0.5 text-[10px] leading-relaxed font-mono ${isError ? "bg-red-500/5 rounded" : ""}`}>
      <span className="text-white/15 shrink-0 w-[48px] text-right tabular-nums mt-px text-[9px]">
        {timestamp ? new Date(timestamp).toLocaleTimeString("en", { hour12: false }) : ""}
      </span>
      <span className={`shrink-0 w-[68px] text-right font-semibold ${color}`}>
        [{agent}]
      </span>
      <span className="shrink-0 text-white/20 w-[54px]">{prefix}</span>
      <span className={`flex-1 whitespace-pre-wrap break-words ${contentColor}`}>
        {content}
      </span>
    </div>
  );
}

export function AgentStream({ runId, isLive }: { runId: string; isLive: boolean }) {
  const [logs, setLogs] = useState<Array<{ agent: string; log_type: string; content: string; timestamp: string | null }>>([]);
  const [connected, setConnected] = useState(false);
  const [eventCount, setEventCount] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  useEffect(() => {
    if (!isLive) return;
    const ws = openStream(runId);
    ws.onopen  = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data) as StreamEvent;
        if (!ev.agent) return;
        setLogs((prev) => [
          ...prev.slice(-999),
          {
            agent:     ev.agent!,
            log_type:  ev.type,
            content:   ev.content ?? JSON.stringify(ev),
            timestamp: ev.timestamp ?? new Date().toISOString(),
          },
        ]);
        setEventCount((n) => n + 1);
      } catch { /* ignore malformed */ }
    };
    return () => ws.close();
  }, [runId, isLive]);

  useEffect(() => {
    if (isLive) return;
    fetchLogs(runId)
      .then((items) =>
        setLogs(items.map((l) => ({
          agent:     l.agent,
          log_type:  l.log_type,
          content:   l.content,
          timestamp: l.timestamp,
        })))
      )
      .catch(() => {});
  }, [runId, isLive]);

  return (
    <div className="flex flex-col h-full" style={{ background: "rgba(15,11,42,0.8)" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.07]">
        <div className="flex items-center gap-4">
          <span className="text-[9px] text-white/25 tracking-widest uppercase font-mono">
            {eventCount > 0 ? `${eventCount} events` : isLive ? "waiting for agent…" : `${logs.length} entries`}
          </span>
          <div className="hidden sm:flex items-center gap-3 text-[9px]">
            <span className="text-violet-400">■ Architect</span>
            <span className="text-indigo-300">■ Coder</span>
            <span className="text-amber-400">■ Reviewer</span>
            <span className="text-emerald-400">■ PR</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-indigo-400 pulse" : "bg-white/10"}`} />
          <span className={`text-[9px] font-mono tracking-wider ${connected ? "text-indigo-300" : "text-white/20"}`}>
            {connected ? "Live" : isLive ? "Connecting…" : "Archived"}
          </span>
        </div>
      </div>

      {/* Log area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-px">
        {logs.length === 0 && (
          <div className="flex flex-col items-center justify-center h-40 text-white/15 font-mono">
            <p className="text-[10px] tracking-widest">
              {isLive ? "// connecting to agent stream…" : "// no logs recorded"}
            </p>
          </div>
        )}
        {logs.map((log, i) => <LogRow key={i} {...log} />)}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
