import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { GeneratedPatch } from '../types';
import {
  GitPullRequest,
  Check,
  X,
  Sparkles,
  FileDiff,
  ShieldCheck,
  ShieldAlert,
  Play,
  Code2,
} from 'lucide-react';

interface PatchProps {
  currentRepo: string;
}

const PatchReviewPage: React.FC<PatchProps> = ({ currentRepo }) => {
  const [patches, setPatches] = useState<GeneratedPatch[]>([]);
  const [errorReport, setErrorReport] = useState<string>(
    "KeyError: 'val'\n  File \"calc.py\", line 3, in calculate\n    return data['val']"
  );
  const [loading, setLoading] = useState<boolean>(false);
  const [expandedPatch, setExpandedPatch] = useState<string | null>(null);

  useEffect(() => {
    fetchPatches();
  }, [currentRepo]);

  const fetchPatches = async () => {
    try {
      const res = await api.get(`/patches/list/${currentRepo}`);
      setPatches(res.data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post('/patches/generate', {
        repo_id: currentRepo,
        error_report: errorReport,
      });
      fetchPatches();
    } catch (err: any) {
      alert(`Patch generation error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleStatusUpdate = async (
    patchId: string,
    status: 'approved' | 'rejected' | 'applied'
  ) => {
    try {
      await api.post('/patches/approve', { patch_id: patchId, status });
      fetchPatches();
    } catch (err: any) {
      alert(`Status update error: ${err.response?.data?.detail || err.message}`);
    }
  };

  const ValidationBadge: React.FC<{ patch: GeneratedPatch }> = ({ patch }) => {
    const v = patch.validation;
    if (!v) return null;
    return (
      <div className="flex gap-2 flex-wrap">
        <span
          className={`px-2 py-0.5 rounded text-xs font-medium flex items-center gap-1 ${
            v.syntax_valid
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
              : 'bg-red-500/10 text-red-400 border border-red-500/30'
          }`}
        >
          {v.syntax_valid ? <ShieldCheck className="w-3 h-3" /> : <ShieldAlert className="w-3 h-3" />}
          Syntax {v.syntax_valid ? 'OK' : 'Error'}
        </span>
        <span
          className={`px-2 py-0.5 rounded text-xs font-medium flex items-center gap-1 ${
            v.git_apply_valid || v.git_apply_skipped
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
              : 'bg-red-500/10 text-red-400 border border-red-500/30'
          }`}
        >
          Git Apply {v.git_apply_skipped ? 'Skipped' : v.git_apply_valid ? 'OK' : 'Failed'}
        </span>
        {patch.llm_generated !== undefined && (
          <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-700/50 text-gray-300 border border-gray-600">
            {patch.llm_generated ? 'LLM Generated' : 'Heuristic Fallback'}
          </span>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <GitPullRequest className="w-7 h-7 text-brand-400" /> AI Patch Generation & Review
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          Generate context-aware fixes from bug reports. Review diffs, validation results, and approve before applying.
        </p>
      </div>

      <form onSubmit={handleGenerate} className="glass-card p-6 space-y-4">
        <label className="block text-xs font-semibold text-gray-300">
          Generate Patch from Bug Report / Stack Trace
        </label>
        <textarea
          value={errorReport}
          onChange={(e) => setErrorReport(e.target.value)}
          rows={4}
          className="w-full bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white font-mono focus:outline-none focus:border-brand-500 resize-y"
          placeholder="Paste error message or full stack trace..."
        />
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-2.5 bg-brand-600 hover:bg-brand-700 text-white font-semibold rounded-xl transition flex items-center gap-2 text-sm shadow-lg shadow-brand-500/20 disabled:opacity-50"
        >
          <Sparkles className="w-4 h-4" /> {loading ? 'Generating...' : 'Generate Patch'}
        </button>
      </form>

      <div className="space-y-6">
        <h3 className="font-semibold text-white">
          Generated Patches ({patches.length})
        </h3>

        {patches.map((p) => (
          <div key={p.patch_id} className="glass-card p-6 space-y-4 border border-gray-800">
            <div className="flex items-start justify-between gap-4">
              <div>
                <span className="text-xs text-gray-400">Target File</span>
                <h4 className="text-lg font-bold text-white font-mono">{p.target_file}</h4>
                {p.error_type && (
                  <span className="text-xs text-red-400 font-mono">{p.error_type}</span>
                )}
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="px-3 py-1 bg-brand-500/10 border border-brand-500/30 text-brand-300 rounded-full text-xs font-bold">
                  {Math.round(p.confidence_score * 100)}% confidence
                </span>
                <span
                  className={`px-3 py-1 rounded-full text-xs font-bold uppercase ${
                    p.status === 'approved' || p.status === 'applied'
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                      : p.status === 'rejected' || p.status === 'failed'
                      ? 'bg-red-500/20 text-red-400 border border-red-500/40'
                      : 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                  }`}
                >
                  {p.status}
                </span>
              </div>
            </div>

            <ValidationBadge patch={p} />

            <p className="text-xs text-gray-300 bg-gray-900/60 p-3 rounded-lg border border-gray-800">
              <span className="font-semibold text-brand-400">Fix Rationale: </span>
              {p.explanation}
            </p>

            {/* Toggle original / diff view */}
            <div className="flex gap-2">
              <button
                onClick={() => setExpandedPatch(expandedPatch === p.patch_id ? null : p.patch_id)}
                className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1"
              >
                <Code2 className="w-3 h-3" />
                {expandedPatch === p.patch_id ? 'Hide Original Code' : 'Show Original Code'}
              </button>
            </div>

            {expandedPatch === p.patch_id && (
              <div className="bg-gray-950 rounded-xl border border-gray-800 overflow-hidden">
                <div className="bg-gray-900/80 px-4 py-2 text-xs font-mono text-gray-400 border-b border-gray-800">
                  Original Code
                </div>
                <pre className="p-4 text-xs font-mono overflow-x-auto text-gray-400 max-h-48">
                  {p.original_code}
                </pre>
              </div>
            )}

            {/* Git Diff */}
            <div className="bg-gray-950 rounded-xl border border-gray-800 overflow-hidden">
              <div className="bg-gray-900/80 px-4 py-2 text-xs font-mono text-gray-400 border-b border-gray-800 flex items-center gap-2">
                <FileDiff className="w-4 h-4 text-brand-400" /> Unified Git Diff
              </div>
              <pre className="p-4 text-xs font-mono overflow-x-auto leading-relaxed">
                {p.git_diff.split('\n').map((line, idx) => {
                  let colorClass = 'text-gray-300';
                  if (line.startsWith('+')) colorClass = 'text-emerald-400 bg-emerald-950/40';
                  else if (line.startsWith('-')) colorClass = 'text-red-400 bg-red-950/40';
                  else if (line.startsWith('@@')) colorClass = 'text-brand-400 font-bold';
                  return (
                    <div key={idx} className={colorClass}>
                      {line}
                    </div>
                  );
                })}
              </pre>
            </div>

            {/* Approval Controls */}
            {p.status === 'pending' && (
              <div className="flex gap-3 pt-2 flex-wrap">
                <button
                  onClick={() => handleStatusUpdate(p.patch_id, 'approved')}
                  className="px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded-lg text-xs flex items-center gap-1.5"
                >
                  <Check className="w-4 h-4" /> Approve
                </button>
                <button
                  onClick={() => handleStatusUpdate(p.patch_id, 'rejected')}
                  className="px-5 py-2 bg-red-600/80 hover:bg-red-700 text-white font-semibold rounded-lg text-xs flex items-center gap-1.5"
                >
                  <X className="w-4 h-4" /> Reject
                </button>
              </div>
            )}

            {p.status === 'approved' && (
              <button
                onClick={() => handleStatusUpdate(p.patch_id, 'applied')}
                className="px-5 py-2 bg-brand-600 hover:bg-brand-700 text-white font-semibold rounded-lg text-xs flex items-center gap-1.5"
              >
                <Play className="w-4 h-4" /> Apply Patch to Repository
              </button>
            )}
          </div>
        ))}

        {patches.length === 0 && (
          <p className="text-sm text-gray-500 py-6 text-center glass-card">
            No patches generated for this repository yet. Paste a stack trace above to get started.
          </p>
        )}
      </div>
    </div>
  );
};

export default PatchReviewPage;
