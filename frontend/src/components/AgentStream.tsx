"use client";

import { useEffect, useRef, useState } from "react";
import { fetchLogs, openStream, AgentLog } from "@/lib/api";

const AGENT_COLOR: Record<string, string> = {
  architect: "text-[#a855f7]",
  coder:     "text-[#38bdf8]",
  reviewer:  "text-[#f59e0b]",
  supervisor:"text-white/25",
  system:    "text-white/15",
  pr:        "text-[#00ff87]",
};

const TYPE_PREFIX: Record<string, string> = {
  thought:     "THOUGHT  ",
  tool_call:   "TOOL▸    ",
  tool_result: "RESULT   ",
  status:      "STATUS   ",
  error:       "ERROR!!! ",
};

interface Props {
  runId: string;
  isLive: boolean;
}

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
  const color     = AGENT_COLOR[agent] ?? "text-white/50";
  const prefix    = TYPE_PREFIX[log_type] ?? "         ";
  const isError   = log_type === "error";
  const isToolCall= log_type === "tool_call";
  const isResult  = log_type === "tool_result";

  const contentColor =
    isError    ? "text-[#ff6b6b]" :
    isToolCall ? "text-[#38bdf8]" :
    isResult   ? "text-white/50"  :
                 "text-white/70";

  return (
    <div className={`flex gap-2 items-start py-0.5 text-[10px] leading-relaxed font-mono
      ${isError ? "bg-[#ff444408]" : ""}`}
    >
      <span className="text-white/15 shrink-0 w-[52px] text-right tabular-nums mt-px text-[9px]">
        {timestamp ? new Date(timestamp).toLocaleTimeString("en", { hour12: false }) : ""}
      </span>
      <span className={`shrink-0 w-[68px] text-right font-bold ${color} tracking-wider`}>
        [{agent}]
      </span>
      <span className="shrink-0 text-white/15 w-[60px] tracking-wider">{prefix}</span>
      <span className={`flex-1 whitespace-pre-wrap break-words ${contentColor}`}>
        {content}
      </span>
    </div>
  );
}

export function AgentStream({ runId, isLive }: Props) {
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
          agent: l.agent,
          log_type: l.log_type,
          content: l.content,
          timestamp: l.timestamp,
        })))
      )
      .catch(() => {});
  }, [runId, isLive]);

  return (
    <div className="flex flex-col h-full bg-[#030303]">
      {/* Terminal header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[#00ff8715] bg-[#0a0a0a]">
        <div className="flex items-center gap-4">
          <span className="text-[9px] text-[#00ff8550] tracking-widest uppercase font-mono">
            {eventCount > 0 ? `${eventCount} events` : isLive ? "waiting for agent···" : `${logs.length} log entries`}
          </span>
          <div className="hidden sm:flex items-center gap-3 text-[8px] tracking-widest">
            <span className="text-[#a855f7]">■ ARCHITECT</span>
            <span className="text-[#38bdf8]">■ CODER</span>
            <span className="text-[#f59e0b]">■ REVIEWER</span>
            <span className="text-[#00ff87]">■ PR</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-[#00ff87] neon-pulse" : "bg-white/10"}`} />
          <span className={`text-[9px] font-mono tracking-widest ${connected ? "text-[#00ff87]" : "text-white/20"}`}>
            {connected ? "LIVE" : isLive ? "CONNECTING···" : "ARCHIVED"}
          </span>
        </div>
      </div>

      {/* Log area */}
      <div className="flex-1 overflow-y-auto p-3 space-y-px">
        {logs.length === 0 && (
          <div className="flex flex-col items-center justify-center h-40 text-white/15 font-mono">
            <p className="text-[10px] tracking-widest">
              {isLive ? "// connecting to agent stream···" : "// no logs recorded"}
            </p>
          </div>
        )}
        {logs.map((log, i) => <LogRow key={i} {...log} />)}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
