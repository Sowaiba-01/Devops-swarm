"use client";

import { Phase, Run } from "@/lib/api";
import { cx } from "@/lib/format";

const STAGES: { key: Phase; label: string; description: string }[] = [
  { key: "architect", label: "Architect", description: "Reads the repository and writes the plan" },
  { key: "coder", label: "Coder", description: "Implements and tests in a cloud sandbox" },
  { key: "reviewer", label: "Reviewer", description: "Reviews the diff and scans for vulnerabilities" },
  { key: "pr", label: "Pull request", description: "Opens a draft PR and reports back" },
];

type StageState = "done" | "active" | "pending" | "failed";

/**
 * Derive each stage's state from the run's own `phase` field.
 *
 * The previous version inferred progress from `iteration_count`, which counts
 * *coder retries* — so a run that self-corrected twice rendered as though it
 * had reached the reviewer, and a first-attempt success looked stalled.
 */
export function stageStates(run: Pick<Run, "status" | "phase">): StageState[] {
  const index = STAGES.findIndex((stage) => stage.key === run.phase);

  if (run.status === "success") return STAGES.map(() => "done");
  if (run.status === "cancelled") return STAGES.map(() => "pending");

  if (run.status === "failed") {
    const failedAt = index === -1 ? 0 : index;
    return STAGES.map((_, i) => (i < failedAt ? "done" : i === failedAt ? "failed" : "pending"));
  }

  if (index === -1) return STAGES.map((_, i) => (i === 0 ? "active" : "pending"));
  return STAGES.map((_, i) => (i < index ? "done" : i === index ? "active" : "pending"));
}

const DOT: Record<StageState, string> = {
  done: "bg-pass border-pass",
  active: "bg-live border-live animate-breathe",
  failed: "bg-fail border-fail",
  pending: "bg-transparent border-line-strong",
};

const TEXT: Record<StageState, string> = {
  done: "text-ink-muted",
  active: "text-ink font-medium",
  failed: "text-fail font-medium",
  pending: "text-ink-faint",
};

export function PipelineTrack({
  run,
  compact = false,
}: {
  run: Pick<Run, "status" | "phase">;
  compact?: boolean;
}) {
  const states = stageStates(run);

  if (compact) {
    return (
      <div className="flex items-center gap-1" aria-label="Pipeline progress">
        {STAGES.map((stage, index) => (
          <span
            key={stage.key}
            title={`${stage.label}: ${states[index]}`}
            className={cx(
              "h-1 w-6 rounded-full border-0",
              states[index] === "done" && "bg-pass/70",
              states[index] === "active" && "bg-live animate-breathe",
              states[index] === "failed" && "bg-fail",
              states[index] === "pending" && "bg-line-strong/60",
            )}
          />
        ))}
      </div>
    );
  }

  return (
    <ol className="grid gap-px overflow-hidden rounded border border-line bg-line sm:grid-cols-4">
      {STAGES.map((stage, index) => {
        const state = states[index];
        return (
          <li key={stage.key} className="bg-surface p-3">
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className={cx("h-2 w-2 shrink-0 rounded-full border", DOT[state])}
              />
              <span className={cx("text-[13px]", TEXT[state])}>{stage.label}</span>
              {state === "active" && (
                <span className="ml-auto text-2xs text-live">running</span>
              )}
              {state === "failed" && <span className="ml-auto text-2xs text-fail">stopped</span>}
            </div>
            <p className="mt-1.5 pl-4 text-2xs leading-relaxed text-ink-faint">
              {stage.description}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
