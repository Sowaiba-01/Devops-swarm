type Status = "running" | "success" | "failed" | string;

const config: Record<string, { border: string; text: string; bg: string; label: string; dot?: string }> = {
  running: {
    border: "border-indigo-500/30",
    bg:     "bg-indigo-500/10",
    text:   "text-indigo-300",
    label:  "Live",
    dot:    "bg-indigo-400",
  },
  success: {
    border: "border-emerald-500/30",
    bg:     "bg-emerald-500/10",
    text:   "text-emerald-400",
    label:  "Done",
  },
  failed: {
    border: "border-red-500/30",
    bg:     "bg-red-500/10",
    text:   "text-red-400",
    label:  "Failed",
  },
};

export function StatusBadge({ status }: { status: Status }) {
  const c = config[status] ?? {
    border: "border-white/10",
    bg:     "bg-white/5",
    text:   "text-white/30",
    label:  status,
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium border ${c.border} ${c.bg} ${c.text}`}>
      {c.dot && <span className={`w-1.5 h-1.5 rounded-full ${c.dot} pulse`} />}
      {!c.dot && status === "success" && <span className="text-[8px]">✓</span>}
      {!c.dot && status === "failed"  && <span className="text-[8px]">✕</span>}
      {c.label}
    </span>
  );
}
