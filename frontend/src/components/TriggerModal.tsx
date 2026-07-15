"use client";

import { useState } from "react";
import { triggerRun } from "@/lib/api";

interface Props {
  onClose: () => void;
  onTriggered: (runId: string) => void;
}

export function TriggerModal({ onClose, onTriggered }: Props) {
  const [form, setForm] = useState({
    repo: "",
    issue_number: 1,
    issue_title: "",
    issue_body: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const { run_id } = await triggerRun(form);
      onTriggered(run_id);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const inputClass =
    "glass-input w-full glass rounded-xl px-4 py-2.5 text-sm text-white/80 placeholder-white/20 " +
    "border border-white/10 focus:border-indigo-500 bg-transparent transition-all duration-200";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        className="glass rounded-2xl w-full max-w-lg mx-4 p-6 border-indigo-500/20 shadow-[0_0_80px_rgba(99,102,241,0.12)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <p className="text-[10px] text-indigo-300/50 tracking-widest uppercase mb-1">New Run</p>
            <h2 className="text-base font-bold gradient-text">Trigger Swarm</h2>
            <p className="text-[11px] text-white/25 mt-0.5">Uses your GITHUB_PAT — no webhook needed</p>
          </div>
          <button
            onClick={onClose}
            className="text-white/20 hover:text-white/60 transition-colors text-xl leading-none w-7 h-7 flex items-center justify-center rounded-lg hover:bg-white/5"
          >
            ×
          </button>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-[10px] text-white/35 tracking-widest uppercase mb-1.5">
              Repository
            </label>
            <input
              required
              placeholder="owner/repo-name"
              value={form.repo}
              onChange={(e) => setForm({ ...form, repo: e.target.value })}
              className={inputClass}
            />
          </div>

          <div>
            <label className="block text-[10px] text-white/35 tracking-widest uppercase mb-1.5">
              Issue Number
            </label>
            <input
              required
              type="number"
              min={1}
              value={form.issue_number}
              onChange={(e) => setForm({ ...form, issue_number: parseInt(e.target.value) || 1 })}
              className={inputClass}
            />
          </div>

          <div>
            <label className="block text-[10px] text-white/35 tracking-widest uppercase mb-1.5">
              Issue Title
            </label>
            <input
              required
              placeholder="Add rate limiting to API endpoints"
              value={form.issue_title}
              onChange={(e) => setForm({ ...form, issue_title: e.target.value })}
              className={inputClass}
            />
          </div>

          <div>
            <label className="block text-[10px] text-white/35 tracking-widest uppercase mb-1.5">
              Issue Description
              <span className="text-white/15 normal-case ml-1">— the Architect reads this</span>
            </label>
            <textarea
              required
              rows={4}
              placeholder="When a user calls /api/refresh after their token expires, it returns 401 instead of issuing a new token..."
              value={form.issue_body}
              onChange={(e) => setForm({ ...form, issue_body: e.target.value })}
              className={`${inputClass} resize-none`}
            />
          </div>

          {error && (
            <div className="glass rounded-xl p-3 border-red-500/25 bg-red-500/5 text-[11px] text-red-400">
              {error}
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2.5 rounded-xl border border-white/10 text-white/30 hover:text-white/60 hover:border-white/20 transition-all text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 py-2.5 rounded-xl glass border-indigo-500/40 bg-indigo-500/10 hover:bg-indigo-500/20 disabled:opacity-40 disabled:cursor-not-allowed text-indigo-200 font-semibold text-sm transition-all"
            >
              {loading ? "Launching…" : "Run Swarm →"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
