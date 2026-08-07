import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { Repository } from '../types';
import { FolderGit2, GitBranch, Download, RefreshCw, CheckCircle, Database } from 'lucide-react';

interface RepoProps {
  currentRepo: string;
  onSelectRepo: (repoId: string) => void;
}

const RepositoryListPage: React.FC<RepoProps> = ({ currentRepo, onSelectRepo }) => {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [repoPath, setRepoPath] = useState<string>('sample_repo');
  const [repoId, setRepoId] = useState<string>('sample_repo');
  const [gitUrl, setGitUrl] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [message, setMessage] = useState<string>('');

  useEffect(() => {
    fetchRepos();
  }, []);

  const fetchRepos = async () => {
    try {
      const res = await api.get('/repos/');
      setRepos(res.data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setMessage('');
    try {
      const res = await api.post('/repos/ingest', {
        repo_id: repoId,
        repo_path: repoPath,
        backend: 'tfidf',
      });
      setMessage(`Success! Indexed ${res.data.files_indexed} files into ${res.data.chunks_indexed} chunks.`);
      onSelectRepo(repoId);
      fetchRepos();
    } catch (err: any) {
      setMessage(`Ingestion failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleGitClone = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!gitUrl) return;
    setLoading(true);
    setMessage('');
    try {
      const targetId = repoId || 'cloned_repo';
      const res = await api.post('/repos/clone', {
        repo_id: targetId,
        git_url: gitUrl,
        backend: 'tfidf',
      });
      setMessage(`Cloned & Ingested! Indexed ${res.data.files_indexed} files.`);
      onSelectRepo(targetId);
      fetchRepos();
    } catch (err: any) {
      setMessage(`Git clone failed: ${err.response?.data?.detail || err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <FolderGit2 className="w-7 h-7 text-brand-400" /> Repository Management & Indexing
        </h1>
        <p className="text-gray-400 text-sm mt-1">
          Ingest local source repositories or clone GitHub/GitLab repos with incremental vector indexing.
        </p>
      </div>

      {message && (
        <div className="p-4 rounded-lg bg-brand-500/10 border border-brand-500/30 text-brand-300 text-sm flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-brand-400" /> {message}
        </div>
      )}

      {/* Ingestion Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <form onSubmit={handleIngest} className="glass-card p-6 space-y-4">
          <h3 className="text-lg font-semibold text-white flex items-center gap-2">
            <Database className="w-5 h-5 text-brand-400" /> Ingest Local Directory
          </h3>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Repository Identifier ID</label>
            <input
              type="text"
              value={repoId}
              onChange={(e) => setRepoId(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Local Relative or Absolute Path</label>
            <input
              type="text"
              value={repoPath}
              onChange={(e) => setRepoPath(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              required
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-brand-600 hover:bg-brand-700 text-white font-semibold rounded-lg shadow-lg shadow-brand-500/20 transition flex items-center justify-center gap-2 text-sm"
          >
            {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Database className="w-4 h-4" />}
            Parse & Index Repository
          </button>
        </form>

        <form onSubmit={handleGitClone} className="glass-card p-6 space-y-4">
          <h3 className="text-lg font-semibold text-white flex items-center gap-2">
            <GitBranch className="w-5 h-5 text-purple-400" /> Clone Remote GitHub Repo
          </h3>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Repository Identifier ID</label>
            <input
              type="text"
              value={repoId}
              onChange={(e) => setRepoId(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              placeholder="e.g. my_remote_repo"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1">Git HTTPS Clone URL</label>
            <input
              type="url"
              value={gitUrl}
              onChange={(e) => setGitUrl(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-sm text-white focus:outline-none focus:border-brand-500"
              placeholder="https://github.com/user/repo.git"
            />
          </div>
          <button
            type="submit"
            disabled={loading || !gitUrl}
            className="w-full py-2.5 bg-purple-600 hover:bg-purple-700 text-white font-semibold rounded-lg shadow-lg shadow-purple-500/20 transition flex items-center justify-center gap-2 text-sm"
          >
            {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            Clone & Build Vector Store
          </button>
        </form>
      </div>

      {/* Ingested Repositories List */}
      <div className="glass-card p-6 space-y-4">
        <h3 className="font-semibold text-white">Ingested Repositories Registry</h3>
        <div className="divide-y divide-gray-800">
          {repos.map((r) => (
            <div key={r.repo_id} className="py-4 flex items-center justify-between">
              <div>
                <p className="font-semibold text-white">{r.repo_id}</p>
                <p className="text-xs text-gray-400 font-mono mt-0.5">{r.repo_path}</p>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-xs text-gray-400">{r.num_files} files ({r.num_chunks} chunks)</span>
                <button
                  onClick={() => onSelectRepo(r.repo_id)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                    currentRepo === r.repo_id
                      ? 'bg-brand-600 text-white'
                      : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                  }`}
                >
                  {currentRepo === r.repo_id ? 'Active' : 'Select'}
                </button>
              </div>
            </div>
          ))}
          {repos.length === 0 && (
            <p className="text-sm text-gray-500 py-4">No repositories ingested yet.</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default RepositoryListPage;
