/**
 * Display formatting.
 *
 * The backend sends timezone-aware ISO strings. A naive string (no offset) is
 * parsed by browsers as *local* time, which previously made every duration and
 * relative timestamp wrong by the viewer's UTC offset — so `parseInstant`
 * treats an offsetless value as UTC rather than trusting the runtime default.
 */

export function parseInstant(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  const date = new Date(hasOffset ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Compact duration: 45s, 3m 12s, 1h 04m. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return "—";
  const total = Math.floor(seconds);
  if (total < 60) return `${total}s`;
  if (total < 3600) return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, "0")}s`;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return `${hours}h ${String(minutes).padStart(2, "0")}m`;
}

export function formatRelative(iso: string | null | undefined): string {
  const date = parseInstant(iso);
  if (!date) return "—";

  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatAbsolute(iso: string | null | undefined): string {
  const date = parseInstant(iso);
  if (!date) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatClock(iso: string | null | undefined): string {
  const date = parseInstant(iso);
  if (!date) return "--:--:--";
  return date.toLocaleTimeString(undefined, {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

/** Tailwind class joiner: skips falsy values so conditionals stay inline. */
export function cx(...values: (string | false | null | undefined)[]): string {
  return values.filter(Boolean).join(" ");
}
