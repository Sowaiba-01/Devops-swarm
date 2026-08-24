"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, api, setApiKey } from "@/lib/api";
import { useDialog } from "@/lib/hooks";

const REPO_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._-]*\\/[A-Za-z0-9][A-Za-z0-9._-]*$";

export function TriggerDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const dialogRef = useDialog(true, onClose);

  const [form, setForm] = useState({
    repo: "",
    issue_number: "1",
    issue_title: "",
    issue_body: "",
  });
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [needsKey, setNeedsKey] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const fieldError = (name: string) =>
    error?.fieldErrors?.find((entry) => entry.field === name)?.message;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    if (apiKeyInput.trim()) setApiKey(apiKeyInput.trim());

    try {
      const { run_id } = await api.trigger({
        repo: form.repo.trim(),
        issue_number: Number(form.issue_number) || 1,
        issue_title: form.issue_title.trim(),
        issue_body: form.issue_body.trim() || "No description provided.",
      });
      router.push(`/runs/${run_id}`);
    } catch (caught) {
      const apiError = caught instanceof ApiError ? caught : new ApiError(0, "Unexpected error");
      setError(apiError);
      // Reveal the key field only once the server says authentication matters.
      if (apiError.isAuth) setNeedsKey(true);
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 sm:items-center"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="trigger-title"
        className="w-full max-w-lg animate-fade-up rounded-lg border border-line bg-surface shadow-overlay"
      >
        <header className="flex items-start justify-between border-b border-line px-5 py-4">
          <div>
            <h2 id="trigger-title" className="text-sm font-semibold text-ink">
              Start a run
            </h2>
            <p className="mt-0.5 text-2xs text-ink-muted">
              The swarm plans, implements, tests and reviews the change, then opens a draft PR.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded p-1 text-ink-faint hover:bg-raised hover:text-ink"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden fill="none">
              <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </button>
        </header>

        <form onSubmit={submit} className="space-y-4 px-5 py-4">
          <div>
            <label className="label" htmlFor="repo">
              Repository
            </label>
            <input
              id="repo"
              required
              pattern={REPO_PATTERN}
              placeholder="owner/repository"
              value={form.repo}
              onChange={(event) => setForm({ ...form, repo: event.target.value })}
              className="field font-mono"
              aria-describedby={fieldError("repo") ? "repo-error" : undefined}
            />
            {fieldError("repo") && (
              <p id="repo-error" className="mt-1 text-2xs text-fail">
                {fieldError("repo")}
              </p>
            )}
          </div>

          <div>
            <label className="label" htmlFor="issue-number">
              Issue number
            </label>
            <input
              id="issue-number"
              required
              type="number"
              min={1}
              value={form.issue_number}
              onChange={(event) => setForm({ ...form, issue_number: event.target.value })}
              className="field tabular-nums"
            />
          </div>

          <div>
            <label className="label" htmlFor="issue-title">
              Issue title
            </label>
            <input
              id="issue-title"
              required
              maxLength={500}
              placeholder="Add rate limiting to the public API"
              value={form.issue_title}
              onChange={(event) => setForm({ ...form, issue_title: event.target.value })}
              className="field"
            />
          </div>

          <div>
            <label className="label" htmlFor="issue-body">
              Description
              <span className="ml-1 normal-case text-ink-faint">— the architect plans from this</span>
            </label>
            <textarea
              id="issue-body"
              rows={4}
              maxLength={50000}
              placeholder="Calling /api/refresh with an expired token returns 401 instead of issuing a new one…"
              value={form.issue_body}
              onChange={(event) => setForm({ ...form, issue_body: event.target.value })}
              className="field resize-y"
            />
            <p className="mt-1 text-2xs text-ink-faint">
              Specific descriptions produce better plans. Name the file or endpoint if you know it.
            </p>
          </div>

          {needsKey && (
            <div>
              <label className="label" htmlFor="api-key">
                API key
              </label>
              <input
                id="api-key"
                type="password"
                autoComplete="off"
                placeholder="Required by this deployment"
                value={apiKeyInput}
                onChange={(event) => setApiKeyInput(event.target.value)}
                className="field font-mono"
              />
              <p className="mt-1 text-2xs text-ink-faint">
                Stored in this browser only and sent as the X-API-Key header.
              </p>
            </div>
          )}

          {error && (
            <div role="alert" className="rounded border border-fail/30 bg-fail/[0.06] p-3">
              <p className="text-[13px] font-medium text-fail">
                {error.isRateLimited
                  ? "Rate limit reached"
                  : error.isAuth
                    ? "Authentication required"
                    : error.isOffline
                      ? "Backend unreachable"
                      : "Could not start the run"}
              </p>
              <p className="mt-0.5 text-2xs text-ink-muted">{error.message}</p>
              {error.requestId && (
                <p className="mt-1 font-mono text-2xs text-ink-faint">request {error.requestId}</p>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="btn-ghost">
              Cancel
            </button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? "Starting…" : "Start run"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
