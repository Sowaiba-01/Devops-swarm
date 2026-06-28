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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[#0a0a0a] border border-[#00ff8725] rounded-lg w-full max-w-lg mx-4 p-6 shadow-[0_0_60px_#00ff8715]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-5 pb-4 border-b border-[#00ff8715]">
          <div>
            <div className="text-[9px] text-[#00ff8560] tracking-widest uppercase mb-1">// new run</div>
            <h2 className="text-sm font-bold text-[#00ff87] tracking-wider">TRIGGER SWARM</h2>
            <p className="text-[10px] text-white/25 mt-0.5 tracking-wide">Uses your GITHUB_PAT — no webhook needed</p>
          </div>
          <button
            onClick={onClose}
            className="text-white/20 hover:text-[#00ff87] transition-colors text-lg leading-none font-mono"
          >
            ×
          </button>
        </div>

        <form onSubmit={submit} className="space-y-4">
          {/* Repo */}
          <div>
            <label className="block text-[9px] text-[#00ff8560] tracking-widest uppercase mb-1.5">
              Repository
            </label>
            <input
              required
              placeholder="owner/repo-name"
              value={form.repo}
              onChange={(e) => setForm({ ...form, repo: e.target.value })}
              className="neon-input w-full bg-[#0f0f0f] border border-[#00ff8720] rounded-sm px-3 py-2 text-xs text-[#00ff87] placeholder-white/15 font-mono tracking-wider"
            />
          </div>

          {/* Issue number */}
          <div>
            <label className="block text-[9px] text-[#00ff8560] tracking-widest uppercase mb-1.5">
              Issue Number
            </label>
            <input
              required
              type="number"
              min={1}
              value={form.issue_number}
              onChange={(e) => setForm({ ...form, issue_number: parseInt(e.target.value) || 1 })}
              className="neon-input w-full bg-[#0f0f0f] border border-[#00ff8720] rounded-sm px-3 py-2 text-xs text-[#00ff87] font-mono tracking-wider"
            />
          </div>

          {/* Issue title */}
          <div>
            <label className="block text-[9px] text-[#00ff8560] tracking-widest uppercase mb-1.5">
              Issue Title
            </label>
            <input
              required
              placeholder="Add rate limiting to API endpoints"
              value={form.issue_title}
              onChange={(e) => setForm({ ...form, issue_title: e.target.value })}
              className="neon-input w-full bg-[#0f0f0f] border border-[#00ff8720] rounded-sm px-3 py-2 text-xs text-[#00ff87] placeholder-white/15 font-mono"
            />
          </div>

          {/* Issue body */}
          <div>
            <label className="block text-[9px] text-[#00ff8560] tracking-widest uppercase mb-1.5">
              Issue Description <span className="text-white/15 normal-case">— be specific, the Architect reads this</span>
            </label>
            <textarea
              required
              rows={4}
              placeholder="When a user calls /api/refresh after their token expires, it returns 401 instead of issuing a new token. Steps to reproduce..."
              value={form.issue_body}
              onChange={(e) => setForm({ ...form, issue_body: e.target.value })}
              className="neon-input w-full bg-[#0f0f0f] border border-[#00ff8720] rounded-sm px-3 py-2 text-xs text-[#00ff87] placeholder-white/15 font-mono resize-none"
            />
          </div>

          {/* Error */}
          {error && (
            <div className="bg-[#ff444408] border border-[#ff444425] rounded-sm p-3 text-[10px] text-[#ff6b6b] font-mono">
              ERROR: {error}
            </div>
          )}

          {/* Buttons */}
          <div className="flex gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 rounded-sm border border-white/10 text-white/30 hover:text-white/60 hover:border-white/20 transition-colors text-[10px] tracking-widest uppercase font-mono"
            >
              CANCEL
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 py-2 rounded-sm border border-[#00ff8740] bg-[#00ff8710] hover:bg-[#00ff8720] disabled:opacity-40 disabled:cursor-not-allowed text-[#00ff87] font-bold text-[10px] tracking-widest uppercase font-mono transition-all"
            >
              {loading ? "LAUNCHING···" : "[ RUN SWARM ]"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
