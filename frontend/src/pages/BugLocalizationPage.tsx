import React, { useState } from 'react';
import api from '../services/api';
import { BugLocalizationResult, BugCandidate } from '../types';
import { Bug, Search, FileCode, CheckCircle2, AlertCircle, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

interface BugProps {
  currentRepo: string;
}

const BugLocalizationPage: React.FC<BugProps> = ({ currentRepo }) => {
  const [errorReport, setErrorReport] = useState<string>(
    `Traceback (most recent call last):\n  File "core/dependency_graph.py", line 45, in _module_to_relpath\n    return all_modules[candidate]\nKeyError: 'pkg/db.py'`
  );
  const [result, setResult] = useState<BugLocalizationResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const navigate = useNavigate();

  const handleLocalize = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!errorReport.trim()) return;
    setLoading(true);

    try {
      const res = await api.post('/bugs/localize', {
        repo_id: currentRepo,
        error_report: errorReport,
        top_k: 5,
      });
      setResult(res.data);
    } catch (err: any) {
      alert(`Bug localization error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <Bug className="w-7 h-7 text-red-400" /> Advanced Bug Localization Engine
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          Paste error logs or stack traces to isolate candidate files, line numbers, and root cause explanations.
        </p>
      </div>

      <form onSubmit={handleLocalize} className="glass-card p-6 space-y-4">
        <label className="block text-xs font-semibold text-gray-300">Stack Trace / Bug Description</label>
        <textarea
          rows={5}
          value={errorReport}
          onChange={(e) => setErrorReport(e.target.value)}
          className="w-full bg-gray-900 border border-gray-700 rounded-xl p-4 text-sm font-mono text-gray-200 focus:outline-none focus:border-brand-500"
          placeholder="Paste error output..."
        />
        <button
          type="submit"
          disabled={loading || !errorReport.trim()}
          className="px-6 py-3 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white font-semibold rounded-xl shadow-lg shadow-red-500/20 transition flex items-center gap-2 text-sm"
        >
          <Search className="w-4 h-4" /> {loading ? 'Analyzing Stack Frames...' : 'Localize Bug Root Cause'}
        </button>
      </form>

      {/* Diagnostic Candidates */}
      {result && (
        <div className="space-y-6">
          <div className="flex items-center justify-between p-4 bg-gray-900 rounded-xl border border-gray-800">
            <div>
              <span className="text-xs text-gray-400">Error Exception Type:</span>
              <p className="text-lg font-bold text-red-400">{result.error_type}</p>
            </div>
            <div>
              <span className="text-xs text-gray-400">Parsed Stack Frames:</span>
              <p className="text-lg font-bold text-white text-right">{result.parsed_frames_count}</p>
            </div>
          </div>

          <div className="space-y-4">
            <h3 className="font-semibold text-white">Ranked Candidate Root Causes</h3>
            {result.candidates.map((c, idx) => (
              <div key={idx} className="glass-card p-6 glass-card-hover space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <FileCode className="w-5 h-5 text-brand-400" />
                    <div>
                      <h4 className="font-bold text-white font-mono">{c.file_path}</h4>
                      <p className="text-xs text-gray-400">
                        Function: <span className="text-brand-300 font-semibold">{c.function}</span> (Line {c.line_number})
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="px-3 py-1 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 rounded-full text-xs font-bold">
                      Confidence: {Math.round(c.confidence_score * 100)}%
                    </span>
                    <button
                      onClick={() => navigate('/patches')}
                      className="px-3 py-1.5 bg-brand-600 hover:bg-brand-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1"
                    >
                      Generate Patch <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                <p className="text-xs text-gray-300 bg-gray-900/60 p-3 rounded-lg border border-gray-800">
                  {c.explanation}
                </p>

                <div className="bg-gray-950 p-4 rounded-lg overflow-x-auto text-xs font-mono text-gray-300 border border-gray-800">
                  <pre>{c.snippet}</pre>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default BugLocalizationPage;
