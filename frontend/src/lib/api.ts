/**
 * API client — all fetch calls go through here.
 *
 * WHY centralise this?
 * If the backend URL changes (e.g. deploy to a VPS), you change ONE line.
 * Every component imports from here, not from raw fetch() calls.
 */

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Run {
  id: string;
  repo: string;
  issue_number: number;
  issue_title: string;
  status: "running" | "success" | "failed";
  pr_url: string | null;
  branch_name: string | null;
  iteration_count: number;
  created_at: string | null;
  completed_at: string | null;
  error_message?: string | null;
}

export interface AgentLog {
  id: string;
  agent: string;
  log_type: string;
  content: string;
  timestamp: string | null;
}

export interface TriggerPayload {
  repo: string;
  issue_number: number;
  issue_title: string;
  issue_body: string;
}

// Fetch all runs (newest first)
export async function fetchRuns(limit = 30): Promise<Run[]> {
  const res = await fetch(`${API}/runs?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Runs fetch failed: ${res.status}`);
  return (await res.json()).runs as Run[];
}

// Fetch a single run
export async function fetchRun(id: string): Promise<Run> {
  const res = await fetch(`${API}/runs/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Run not found: ${res.status}`);
  return res.json() as Promise<Run>;
}

// Fetch agent logs for a completed run
export async function fetchLogs(id: string): Promise<AgentLog[]> {
  const res = await fetch(`${API}/runs/${id}/logs`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Logs fetch failed: ${res.status}`);
  return (await res.json()).logs as AgentLog[];
}

// Fire a test run via /trigger (bypasses GitHub webhook)
export async function triggerRun(payload: TriggerPayload): Promise<{ run_id: string }> {
  const res = await fetch(`${API}/trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail ?? `Trigger failed: ${res.status}`);
  }
  return res.json();
}

// Create a WebSocket connection for a live run
export function openStream(runId: string): WebSocket {
  const wsBase = API.replace(/^http/, "ws");
  return new WebSocket(`${wsBase}/ws/${runId}`);
}
