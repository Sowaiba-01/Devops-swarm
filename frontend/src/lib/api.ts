/**
 * Typed API client.
 *
 * Every response shape here mirrors a Pydantic model in `backend/app/schemas.py`.
 * Errors surface as `ApiError` carrying the status and the backend's request id,
 * so a failure in the UI can be traced to a specific server log line.
 */

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

// Set when the backend has API_KEYS configured. Reading from localStorage keeps
// the key out of the bundle and out of the URL.
const API_KEY_STORAGE = "swarm.apiKey";

export function getApiKey(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(API_KEY_STORAGE) ?? "";
}

export function setApiKey(key: string): void {
  if (typeof window === "undefined") return;
  if (key) window.localStorage.setItem(API_KEY_STORAGE, key);
  else window.localStorage.removeItem(API_KEY_STORAGE);
}

// ── Types ─────────────────────────────────────────────────────────────

export type RunStatus = "queued" | "running" | "success" | "failed" | "cancelled";
export type Phase = "architect" | "coder" | "reviewer" | "pr" | "done";
export type Agent = "architect" | "coder" | "reviewer" | "supervisor" | "system";
export type LogType = "thought" | "tool_call" | "tool_result" | "status" | "error";

export interface Run {
  id: string;
  repo: string;
  issue_number: number;
  issue_title: string | null;
  status: RunStatus;
  phase: Phase | null;
  pr_url: string | null;
  branch_name: string | null;
  iteration_count: number;
  tests_passed: boolean | null;
  review_verdict: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  error_message?: string | null;
}

export interface PageMeta {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface RunList {
  runs: Run[];
  page: PageMeta;
}

export interface Stats {
  total: number;
  queued: number;
  running: number;
  success: number;
  failed: number;
  cancelled: number;
  success_rate: number;
}

export interface LogEntry {
  id: string;
  seq: number;
  agent: string;
  log_type: string;
  content: string;
  timestamp: string | null;
}

export interface StreamEvent {
  seq?: number;
  run_id?: string;
  agent?: string;
  type: string;
  content?: string;
  tool?: string;
  args?: Record<string, unknown>;
  timestamp?: string | null;
  replay?: boolean;
  status?: RunStatus;
  phase?: Phase;
  last_seq?: number;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  database: "up" | "down";
  runs_in_flight: number;
  sandboxes_active: number;
}

export interface TriggerInput {
  repo: string;
  issue_number: number;
  issue_title: string;
  issue_body: string;
}

// ── Transport ─────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly requestId?: string,
    readonly fieldErrors?: { field: string; message: string }[],
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Failures the user can act on themselves. */
  get isAuth() {
    return this.status === 401 || this.status === 403;
  }
  get isRateLimited() {
    return this.status === 429;
  }
  get isOffline() {
    return this.status === 0;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");

  const key = getApiKey();
  if (key) headers.set("X-API-Key", key);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    // A network-level failure has no status; give it one the UI can branch on
    // rather than letting a raw TypeError reach a component.
    throw new ApiError(0, "Cannot reach the API. Is the backend running?");
  }

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(
      response.status,
      payload?.detail ?? `Request failed with ${response.status}`,
      payload?.request_id ?? response.headers.get("X-Request-ID") ?? undefined,
      payload?.errors,
    );
  }

  return payload as T;
}

// ── Endpoints ─────────────────────────────────────────────────────────

export const api = {
  health: () => request<Health>("/health"),

  stats: () => request<Stats>("/runs/stats"),

  listRuns: (params: { limit?: number; offset?: number; status?: string; repo?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.limit != null) query.set("limit", String(params.limit));
    if (params.offset) query.set("offset", String(params.offset));
    if (params.status) query.set("status", params.status);
    if (params.repo) query.set("repo", params.repo);
    const suffix = query.toString();
    return request<RunList>(`/runs${suffix ? `?${suffix}` : ""}`);
  },

  getRun: (id: string) => request<Run>(`/runs/${id}`),

  getLogs: (id: string, afterSeq = 0) =>
    request<{ logs: LogEntry[]; last_seq: number }>(
      `/runs/${id}/logs?after_seq=${afterSeq}&limit=2000`,
    ),

  trigger: (input: TriggerInput) =>
    request<{ run_id: string; status: string; stream_url: string }>("/trigger", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  cancel: (id: string) => request<Run>(`/runs/${id}/cancel`, { method: "POST" }),
};

/**
 * Build the live-stream URL.
 *
 * `after_seq` tells the server which events the client already holds, so a
 * reconnect resumes exactly where it left off instead of replaying the whole
 * run or silently dropping what it missed.
 */
export function streamUrl(runId: string, afterSeq: number): string {
  const base = API_BASE.replace(/^http/, "ws");
  const params = new URLSearchParams({ after_seq: String(afterSeq) });
  const key = getApiKey();
  // A WebSocket handshake cannot carry custom headers from a browser, so the
  // key has to travel as a query parameter here.
  if (key) params.set("api_key", key);
  return `${base}/ws/${runId}?${params}`;
}

export const TERMINAL_STATUSES: readonly RunStatus[] = ["success", "failed", "cancelled"];

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}
