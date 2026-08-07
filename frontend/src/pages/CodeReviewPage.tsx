import React, { useState } from 'react';
import api from '../services/api';
import { ShieldCheck, GitCommit, AlertTriangle, CheckCircle, Code } from 'lucide-react';

const CodeReviewPage: React.FC = () => {
  const [code, setCode] = useState<string>(
    `def verify_jwt_token(token):\n    password = "secret_hardcoded_key"\n    eval("import os; os.system('echo dangerous')")\n    return True`
  );
  const [reviewResult, setReviewResult] = useState<any>(null);

  const [diff, setDiff] = useState<string>(
    `+ def authenticate_user(token):\n+     if not validate_jwt(token):\n+         raise AuthError("Invalid token signature")`
  );
  const [commitMsg, setCommitMsg] = useState<string>('');

  const handleReview = async () => {
    try {
      const res = await api.post('/review/analyze', {
        code_content: code,
        file_path: 'auth_handler.py',
      });
      setReviewResult(res.data);
    } catch (e: any) {
      alert(e.message);
    }
  };

  const handleCommitGen = async () => {
    try {
      const res = await api.post('/review/commit_message', {
        git_diff: diff,
      });
      setCommitMsg(res.data.commit_message);
    } catch (e: any) {
      alert(e.message);
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <ShieldCheck className="w-7 h-7 text-emerald-400" /> Automated Code Review & Commit AI
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          Scan files for security flaws, cyclomatic complexity, code smells, and generate commit messages.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Code Review Box */}
        <div className="glass-card p-6 space-y-4">
          <h3 className="font-bold text-white text-lg flex items-center gap-2">
            <Code className="w-5 h-5 text-brand-400" /> Code Review Scan
          </h3>
          <textarea
            rows={8}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded-xl p-4 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500"
          />
          <button
            onClick={handleReview}
            className="w-full py-2.5 bg-brand-600 hover:bg-brand-700 text-white font-semibold rounded-xl transition text-sm shadow-md"
          >
            Run Static & Security Scan
          </button>

          {reviewResult && (
            <div className="space-y-3 pt-3 border-t border-gray-800">
              <div className="flex justify-between text-xs font-semibold">
                <span className="text-gray-400">Quality Rating: <span className="text-emerald-400 font-bold">{reviewResult.quality_rating}</span></span>
                <span className="text-red-400">{reviewResult.issues_found} issues flagged</span>
              </div>
              {reviewResult.issues.map((i: any, idx: number) => (
                <div key={idx} className="p-3 bg-red-950/30 border border-red-800/40 rounded-lg text-xs text-red-300">
                  Line {i.line}: [{i.category.toUpperCase()}] {i.message}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* AI Commit Generator */}
        <div className="glass-card p-6 space-y-4">
          <h3 className="font-bold text-white text-lg flex items-center gap-2">
            <GitCommit className="w-5 h-5 text-purple-400" /> AI Commit Message Generator
          </h3>
          <textarea
            rows={8}
            value={diff}
            onChange={(e) => setDiff(e.target.value)}
            className="w-full bg-gray-900 border border-gray-700 rounded-xl p-4 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500"
            placeholder="Paste Git Diff..."
          />
          <button
            onClick={handleCommitGen}
            className="w-full py-2.5 bg-purple-600 hover:bg-purple-700 text-white font-semibold rounded-xl transition text-sm shadow-md"
          >
            Generate Conventional Commit Message
          </button>

          {commitMsg && (
            <div className="p-4 bg-purple-950/40 border border-purple-800/50 rounded-xl">
              <span className="text-xs font-bold text-purple-300 uppercase">Suggested Commit Message:</span>
              <p className="text-sm font-semibold text-white mt-1 font-mono">{commitMsg}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CodeReviewPage;
