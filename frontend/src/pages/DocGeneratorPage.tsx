import React, { useState } from 'react';
import api from '../services/api';
import { FileText, Download, Sparkles, Printer } from 'lucide-react';

interface DocProps {
  currentRepo: string;
}

const DocGeneratorPage: React.FC<DocProps> = ({ currentRepo }) => {
  const [docData, setDocData] = useState<{ readme: string; api_docs: string } | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const handleGenerate = async () => {
    setLoading(true);
    try {
      const res = await api.post('/docs/generate', {
        repo_id: currentRepo,
        format: 'markdown',
      });
      setDocData(res.data);
    } catch (err: any) {
      alert(`Doc generation failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleExportHTML = async () => {
    try {
      const res = await api.post(
        '/docs/generate',
        { repo_id: currentRepo, format: 'html' },
        { responseType: 'blob' }
      );
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/html' }));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${currentRepo}_documentation.html`);
      document.body.appendChild(link);
      link.click();
    } catch (err: any) {
      alert('HTML Export failed');
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <FileText className="w-7 h-7 text-brand-400" /> Automated Documentation Generator
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            Auto-generate production READMEs, API method documentation, folder trees, and PDF/HTML exports.
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleGenerate}
            disabled={loading}
            className="px-5 py-2.5 bg-brand-600 hover:bg-brand-700 text-white font-semibold rounded-xl transition flex items-center gap-2 text-sm shadow-lg shadow-brand-500/20"
          >
            <Sparkles className="w-4 h-4" /> {loading ? 'Building Docs...' : 'Generate Repository Docs'}
          </button>
          {docData && (
            <button
              onClick={handleExportHTML}
              className="px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-200 font-semibold rounded-xl transition flex items-center gap-2 text-sm border border-gray-700"
            >
              <Printer className="w-4 h-4 text-emerald-400" /> Export HTML/PDF
            </button>
          )}
        </div>
      </div>

      {docData && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div className="glass-card p-6 space-y-4">
            <h3 className="font-bold text-white text-lg">Generated README.md</h3>
            <pre className="p-4 bg-gray-950 rounded-xl text-xs font-mono text-gray-300 overflow-x-auto h-[500px] border border-gray-800 leading-relaxed">
              {docData.readme}
            </pre>
          </div>

          <div className="glass-card p-6 space-y-4">
            <h3 className="font-bold text-white text-lg">API Endpoint Reference</h3>
            <pre className="p-4 bg-gray-950 rounded-xl text-xs font-mono text-gray-300 overflow-x-auto h-[500px] border border-gray-800 leading-relaxed">
              {docData.api_docs}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
};

export default DocGeneratorPage;
