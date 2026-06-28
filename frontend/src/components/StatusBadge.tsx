type Status = "running" | "success" | "failed" | string;

const config: Record<string, { border: string; text: string; bg: string; label: string; pulse: boolean }> = {
  running: {
    border: "border-[#38bdf840]",
    bg:     "bg-[#38bdf808]",
    text:   "text-[#38bdf8]",
    label:  "LIVE",
    pulse:  true,
  },
  success: {
    border: "border-[#00ff8740]",
    bg:     "bg-[#00ff8708]",
    text:   "text-[#00ff87]",
    label:  "OK",
    pulse:  false,
  },
  failed: {
    border: "border-[#ff444430]",
    bg:     "bg-[#ff44440a]",
    text:   "text-[#ff6b6b]",
    label:  "FAIL",
    pulse:  false,
  },
};

export function StatusBadge({ status }: { status: Status }) {
  const c = config[status] ?? {
    border: "border-white/10",
    bg:     "bg-white/5",
    text:   "text-white/40",
    label:  status.toUpperCase(),
    pulse:  false,
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 border rounded-sm text-[9px] font-bold tracking-widest
        ${c.border} ${c.bg} ${c.text} ${c.pulse ? "neon-pulse" : ""}`}
    >
      {c.pulse && (
        <span className="inline-block h-1 w-1 rounded-full bg-[#38bdf8] neon-pulse" />
      )}
      {c.label}
    </span>
  );
}
