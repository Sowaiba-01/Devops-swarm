"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { LogEntry } from "@/lib/api";
import { useRunStream } from "@/lib/hooks";
import { cx, formatClock } from "@/lib/format";

const AGENT_TONE: Record<string, string> = {
  architect: "text-live",
  coder: "text-accent",
  reviewer: "text-warn",
  supervisor: "text-ink-faint",
  system: "text-ink-faint",
};

const TYPE_LABEL: Record<string, string> = {
  thought: "think",
  tool_call: "call",
  tool_result: "result",
  status: "status",
  error: "error",
};

const AGENTS = ["architect", "coder", "reviewer", "supervisor", "system"] as const;

function LogLine({ entry, query }: { entry: LogEntry; query: string }) {
  const isError = entry.log_type === "error";
  const tone = AGENT_TONE[entry.agent] ?? "text-ink-muted";

  const body =
    entry.log_type === "tool_result"
      ? "text-ink-muted"
      : isError
        ? "text-fail"
        : entry.log_type === "tool_call"
          ? "text-accent"
          : "text-ink";

  return (
    <div
      className={cx(
        "flex gap-3 border-l-2 px-3 py-1 font-mono text-2xs leading-relaxed",
        isError ? "border-fail bg-fail/[0.06]" : "border-transparent hover:bg-raised/50",
      )}
    >
      <time className="w-[62px] shrink-0 tabular-nums text-ink-faint" dateTime={entry.timestamp ?? undefined}>
        {formatClock(entry.timestamp)}
      </time>
      <span className={cx("w-[72px] shrink-0 font-medium", tone)}>{entry.agent}</span>
      <span className="w-[46px] shrink-0 text-ink-faint">
        {TYPE_LABEL[entry.log_type] ?? entry.log_type}
      </span>
      <span className={cx("min-w-0 flex-1 whitespace-pre-wrap break-words", body)}>
        {highlight(entry.content, query)}
      </span>
    </div>
  );
}

/** Wrap search matches so the eye can find them in a wall of monospace text. */
function highlight(text: string, query: string) {
  if (!query) return text;
  const index = text.toLowerCase().indexOf(query.toLowerCase());
  if (index === -1) return text;
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded-sm bg-warn/30 text-ink">{text.slice(index, index + query.length)}</mark>
      {text.slice(index + query.length)}
    </>
  );
}

export function LogConsole({ runId, live }: { runId: string; live: boolean }) {
  const { logs, connected, reconnecting, droppedCount } = useRunStream(runId, live);

  const [query, setQuery] = useState("");
  const [hiddenAgents, setHiddenAgents] = useState<Set<string>>(new Set());
  const [follow, setFollow] = useState(true);

  const scrollRef = useRef<HTMLDivElement>(null);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return logs.filter(
      (entry) =>
        !hiddenAgents.has(entry.agent) &&
        (!needle || entry.content.toLowerCase().includes(needle)),
    );
  }, [logs, hiddenAgents, query]);

  // Auto-scroll only while the reader is at the bottom. Yanking someone back
  // down while they are reading history is the classic log-viewer annoyance.
  useEffect(() => {
    if (!follow || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [visible, follow]);

  const onScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    setFollow(distanceFromBottom < 40);
  };

  const toggleAgent = (agent: string) =>
    setHiddenAgents((current) => {
      const next = new Set(current);
      if (next.has(agent)) next.delete(agent);
      else next.add(agent);
      return next;
    });

  const download = () => {
    const text = logs
      .map((entry) => `${entry.timestamp ?? ""} [${entry.agent}] ${entry.log_type}: ${entry.content}`)
      .join("\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `swarm-run-${runId.slice(0, 8)}.log`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="panel flex min-h-0 flex-col" aria-label="Agent event stream">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-3 py-2">
        <div className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={cx(
              "h-1.5 w-1.5 rounded-full",
              connected ? "bg-live animate-breathe" : reconnecting ? "bg-warn" : "bg-line-strong",
            )}
          />
          <span className="text-2xs font-medium text-ink-muted">
            {connected ? "Live" : reconnecting ? "Reconnecting…" : live ? "Connecting…" : "Archived"}
          </span>
        </div>

        <span className="text-2xs tabular-nums text-ink-faint">
          {visible.length === logs.length
            ? `${logs.length} events`
            : `${visible.length} of ${logs.length}`}
          {droppedCount > 0 && ` · ${droppedCount} older trimmed`}
        </span>

        <div className="flex items-center gap-1" role="group" aria-label="Filter by agent">
          {AGENTS.map((agent) => {
            const hidden = hiddenAgents.has(agent);
            return (
              <button
                key={agent}
                type="button"
                onClick={() => toggleAgent(agent)}
                aria-pressed={!hidden}
                className={cx(
                  "rounded border px-1.5 py-0.5 text-2xs font-medium transition-colors",
                  hidden
                    ? "border-line text-ink-faint line-through"
                    : cx("border-line-strong", AGENT_TONE[agent]),
                )}
              >
                {agent}
              </button>
            );
          })}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter…"
            aria-label="Filter events"
            className="w-32 rounded border border-line bg-canvas px-2 py-1 text-2xs
                       placeholder:text-ink-faint focus:border-accent focus:outline-none"
          />
          <button
            type="button"
            onClick={() => setFollow((value) => !value)}
            aria-pressed={follow}
            className={cx(
              "rounded border px-2 py-1 text-2xs font-medium transition-colors",
              follow
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-line text-ink-muted hover:text-ink",
            )}
          >
            Follow
          </button>
          <button
            type="button"
            onClick={download}
            disabled={logs.length === 0}
            className="rounded border border-line px-2 py-1 text-2xs font-medium text-ink-muted
                       hover:text-ink disabled:opacity-40"
          >
            Export
          </button>
        </div>
      </header>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto py-1"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
      >
        {visible.length === 0 ? (
          <p className="px-3 py-12 text-center font-mono text-2xs text-ink-faint">
            {logs.length === 0
              ? live
                ? "waiting for the first agent event…"
                : "no events were recorded for this run"
              : "no events match the current filter"}
          </p>
        ) : (
          visible.map((entry) => (
            <LogLine key={`${entry.seq}-${entry.id}`} entry={entry} query={query.trim()} />
          ))
        )}
      </div>

      {!follow && (
        <button
          type="button"
          onClick={() => setFollow(true)}
          className="border-t border-line bg-raised px-3 py-1.5 text-2xs font-medium text-accent"
        >
          ↓ Jump to newest
        </button>
      )}
    </section>
  );
}
