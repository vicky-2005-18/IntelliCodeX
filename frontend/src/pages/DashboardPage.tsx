import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { AnalyticsMetrics } from '../types';
import { ShieldCheck, Bug, Code2, Network, Sparkles, Activity, FileCode, AlertCircle, RefreshCw, Download, Database } from 'lucide-react';

interface DashboardProps {
  currentRepo: string;
  onSelectRepo?: (repoId: string) => void;
}

const DashboardPage: React.FC<DashboardProps> = ({ currentRepo, onSelectRepo }) => {
  const [metrics, setMetrics] = useState<AnalyticsMetrics | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [notIngested, setNotIngested] = useState<boolean>(false);
  const [ingesting, setIngesting] = useState<boolean>(false);
  const [ingestStatus, setIngestStatus] = useState<string>('');
  const navigate = useNavigate();

  // Sanitize currentRepo to remove any accidental sample_repo prefixes before http
  const sanitizedRepo = currentRepo.includes('http')
    ? currentRepo.substring(currentRepo.indexOf('http'))
    : currentRepo;

  useEffect(() => {
    fetchMetrics();
  }, [sanitizedRepo]);

  const fetchMetrics = async () => {
    setLoading(true);
    setNotIngested(false);
    setIngestStatus('');
    try {
      const res = await api.get(`/analytics/${encodeURIComponent(sanitizedRepo)}`);
      setMetrics(res.data);
    } catch (err: any) {
      console.warn("Analytics not yet indexed for repo", sanitizedRepo);
      setMetrics(null);
      setNotIngested(true);
    } finally {
      setLoading(false);
    }
  };

  const handleQuickIngest = async () => {
    setIngesting(true);
    setIngestStatus('Parsing repository structure and indexing vectors...');
    try {
      const isGitUrl = sanitizedRepo.startsWith('http://') || sanitizedRepo.startsWith('https://') || sanitizedRepo.includes('github.com');
      if (isGitUrl) {
        // Derive clean repo_id from URL (e.g., https://github.com/vicky-2005-18/TB -> TB)
        const urlParts = sanitizedRepo.replace(/\/$/, '').split('/');
        let cleanRepoId = urlParts[urlParts.length - 1].replace(/\.git$/, '') || 'remote_repo';
        if (cleanRepoId.length < 2) {
          cleanRepoId = urlParts.slice(-2).join('_').replace(/\.git$/, '');
        }

        setIngestStatus(`Cloning remote GitHub repository '${cleanRepoId}'...`);
        const res = await api.post('/repos/clone', {
          repo_id: cleanRepoId,
          git_url: sanitizedRepo,
          backend: 'tfidf',
        });

        setIngestStatus(`Successfully cloned & indexed ${res.data.files_indexed} files into ${res.data.chunks_indexed} code chunks!`);
        
        // Auto select the new clean repo_id!
        if (onSelectRepo) {
          onSelectRepo(cleanRepoId);
        }
      } else {
        setIngestStatus(`Indexing local directory path '${sanitizedRepo}'...`);
        const res = await api.post('/repos/ingest', {
          repo_id: sanitizedRepo,
          repo_path: sanitizedRepo,
          backend: 'tfidf',
        });
        setIngestStatus(`Successfully indexed ${res.data.files_indexed} files!`);
        fetchMetrics();
      }
    } catch (err: any) {
      setIngestStatus(`Ingestion error: ${err.response?.data?.detail || err.message}`);
    } finally {
      setIngesting(false);
    }
  };

  const isGitUrl = sanitizedRepo.startsWith('http://') || sanitizedRepo.startsWith('https://') || sanitizedRepo.includes('github.com');

  return (
    <div className="space-y-8">
      {/* Top Banner */}
      <div className="glass-card p-8 relative overflow-hidden bg-gradient-to-r from-blue-900/30 to-indigo-900/20 border-brand-500/20">
        <div className="max-w-2xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-brand-500/10 border border-brand-500/30 text-brand-400 text-xs font-semibold mb-4">
            <Sparkles className="w-3.5 h-3.5" /> Autonomous AI Software Maintenance
          </div>
          <h1 className="text-3xl font-bold text-white mb-2">
            Repository Overview: <span className="text-brand-400 font-mono text-2xl">{sanitizedRepo}</span>
          </h1>
          <p className="text-gray-400 text-sm leading-relaxed">
            Real-time telemetry, semantic code chunking stats, AI bug localization, and automated git patch generation.
          </p>
        </div>
      </div>

      {/* Non-Ingested Alert Card */}
      {notIngested && !loading && (
        <div className="glass-card p-6 border-amber-500/30 bg-amber-900/10 space-y-4">
          <div className="flex items-start gap-4">
            <div className="p-3 bg-amber-500/20 text-amber-400 rounded-xl flex-shrink-0">
              <AlertCircle className="w-6 h-6" />
            </div>
            <div className="space-y-1 flex-1">
              <h3 className="text-lg font-semibold text-white">Repository Not Yet Ingested</h3>
              <p className="text-sm text-gray-300">
                The active repository <span className="font-mono text-brand-300 font-semibold">{sanitizedRepo}</span> has not been parsed into the IntelliCodeX FAISS vector store. Ingest it to unlock telemetry, dependency graphs, and AI assistant features.
              </p>
              {ingestStatus && (
                <div className="p-3 rounded-lg bg-gray-900/80 border border-gray-700 text-xs text-brand-300 font-mono mt-2">
                  {ingestStatus}
                </div>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-4 pt-2">
            <button
              onClick={handleQuickIngest}
              disabled={ingesting}
              className="px-5 py-2.5 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white font-semibold rounded-lg shadow-lg shadow-brand-500/20 transition flex items-center gap-2 text-sm"
            >
              {ingesting ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : isGitUrl ? (
                <Download className="w-4 h-4" />
              ) : (
                <Database className="w-4 h-4" />
              )}
              {isGitUrl ? 'Clone & Index Remote Repository' : 'Parse & Index Repository'}
            </button>

            <button
              onClick={() => navigate('/repos')}
              className="px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 font-semibold rounded-lg transition text-sm"
            >
              Open Repository Registry
            </button>
          </div>
        </div>
      )}

      {/* Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="glass-card p-6 glass-card-hover flex items-center gap-4">
          <div className="p-3 bg-blue-500/10 text-blue-400 rounded-xl">
            <FileCode className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-medium text-gray-400">Total Source Files</p>
            <p className="text-2xl font-bold text-white mt-1">
              {loading ? <RefreshCw className="w-5 h-5 animate-spin text-gray-500" /> : (metrics?.total_files ?? '-')}
            </p>
          </div>
        </div>

        <div className="glass-card p-6 glass-card-hover flex items-center gap-4">
          <div className="p-3 bg-indigo-500/10 text-indigo-400 rounded-xl">
            <Code2 className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-medium text-gray-400">Functions & Classes</p>
            <p className="text-2xl font-bold text-white mt-1">
              {loading ? (
                <RefreshCw className="w-5 h-5 animate-spin text-gray-500" />
              ) : metrics ? (
                (metrics.total_functions ?? 0) + (metrics.total_classes ?? 0)
              ) : (
                '-'
              )}
            </p>
          </div>
        </div>

        <div className="glass-card p-6 glass-card-hover flex items-center gap-4">
          <div className="p-3 bg-purple-500/10 text-purple-400 rounded-xl">
            <Network className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-medium text-gray-400">Graph Dependencies</p>
            <p className="text-2xl font-bold text-white mt-1">
              {loading ? <RefreshCw className="w-5 h-5 animate-spin text-gray-500" /> : (metrics?.total_dependencies ?? '-')}
            </p>
          </div>
        </div>

        <div className="glass-card p-6 glass-card-hover flex items-center gap-4">
          <div className="p-3 bg-emerald-500/10 text-emerald-400 rounded-xl">
            <ShieldCheck className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-medium text-gray-400">Health Score</p>
            <p className="text-2xl font-bold text-emerald-400 mt-1">
              {loading ? (
                <RefreshCw className="w-5 h-5 animate-spin text-gray-500" />
              ) : metrics?.health_score ? (
                `${metrics.health_score}/100`
              ) : (
                '-'
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Analytics Breakdown Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="glass-card p-6">
          <h3 className="font-semibold text-white mb-4 flex items-center gap-2">
            <Activity className="w-5 h-5 text-brand-400" /> Language Distribution
          </h3>
          {metrics?.language_distribution && Object.keys(metrics.language_distribution).length > 0 ? (
            <div className="space-y-3">
              {Object.entries(metrics.language_distribution).map(([lang, count]) => (
                <div key={lang} className="flex items-center justify-between p-3 bg-gray-900/50 rounded-lg">
                  <span className="text-sm font-medium capitalize text-gray-300">{lang}</span>
                  <span className="text-xs font-bold px-2.5 py-1 rounded bg-brand-500/20 text-brand-300">
                    {count} files
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500">Ingest repository to view language telemetry.</p>
          )}
        </div>

        <div className="glass-card p-6">
          <h3 className="font-semibold text-white mb-4 flex items-center gap-2">
            <Bug className="w-5 h-5 text-red-400" /> Largest Modules (Line Count)
          </h3>
          {metrics?.largest_modules && metrics.largest_modules.length > 0 ? (
            <div className="space-y-3">
              {metrics.largest_modules.map((m) => (
                <div key={m.file_path} className="flex items-center justify-between p-3 bg-gray-900/50 rounded-lg">
                  <span className="text-sm text-gray-300 font-mono truncate max-w-xs">{m.file_path}</span>
                  <span className="text-xs font-semibold text-gray-400">{m.lines} lines</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500">No file size telemetry available.</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default DashboardPage;

