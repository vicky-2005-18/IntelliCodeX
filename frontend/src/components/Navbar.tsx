import React, { useEffect, useState } from 'react';
import { Bell, Terminal, FolderGit2, Plus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { Repository } from '../types';

interface NavbarProps {
  currentRepo: string;
  onRepoChange: (repoId: string) => void;
}

const Navbar: React.FC<NavbarProps> = ({ currentRepo, onRepoChange }) => {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [isCustom, setIsCustom] = useState<boolean>(false);
  const navigate = useNavigate();

  useEffect(() => {
    fetchRepos();
  }, [currentRepo]);

  const fetchRepos = async () => {
    try {
      const res = await api.get('/repos/');
      setRepos(res.data || []);
      // If currentRepo is in ingested list, ensure isCustom is false
      if (res.data && res.data.some((r: Repository) => r.repo_id === currentRepo)) {
        setIsCustom(false);
      }
    } catch (e) {
      console.warn("Failed to fetch repository registry in navbar");
    }
  };

  return (
    <header className="h-16 bg-dark-surface/80 backdrop-blur-md border-b border-gray-800 px-8 flex items-center justify-between sticky top-0 z-40">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 bg-gray-900 border border-gray-700 px-3 py-1.5 rounded-lg shadow-sm">
          <Terminal className="w-4 h-4 text-brand-400" />
          <span className="text-xs text-gray-400 font-medium">Active Repo:</span>
          
          {!isCustom ? (
            <select
              value={currentRepo}
              onChange={(e) => {
                if (e.target.value === '__CUSTOM__') {
                  setIsCustom(true);
                } else if (e.target.value === '__ADD_NEW__') {
                  navigate('/repos');
                } else {
                  onRepoChange(e.target.value);
                }
              }}
              className="bg-transparent text-sm text-white font-semibold focus:outline-none cursor-pointer max-w-xs"
            >
              {repos.length === 0 && <option value="sample_repo" className="bg-gray-900">sample_repo</option>}
              {repos.map((r) => (
                <option key={r.repo_id} value={r.repo_id} className="bg-gray-900 text-white">
                  {r.repo_id}
                </option>
              ))}
              {!repos.some(r => r.repo_id === currentRepo) && currentRepo && (
                <option value={currentRepo} className="bg-gray-900 text-white">
                  {currentRepo}
                </option>
              )}
              <option value="__CUSTOM__" className="bg-gray-900 text-brand-400 font-semibold">
                ✏️ Enter path / Git URL manually...
              </option>
              <option value="__ADD_NEW__" className="bg-gray-900 text-purple-400 font-semibold">
                ➕ Ingest / Clone new repo...
              </option>
            </select>
          ) : (
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={currentRepo.includes('http') ? currentRepo.substring(currentRepo.indexOf('http')) : currentRepo}
                onChange={(e) => {
                  let val = e.target.value;
                  if (val.includes('http://') || val.includes('https://')) {
                    val = val.substring(val.indexOf('http'));
                  }
                  onRepoChange(val);
                }}
                placeholder="e.g. https://github.com/user/repo"
                className="bg-gray-950 text-sm text-brand-300 font-mono font-semibold focus:outline-none w-72 border border-brand-500/40 rounded px-2 py-1"
                autoFocus
              />
              <button
                onClick={() => {
                  if (currentRepo.includes('http')) {
                    const clean = currentRepo.substring(currentRepo.indexOf('http'));
                    onRepoChange(clean);
                  }
                  setIsCustom(false);
                }}
                className="text-xs text-white px-2 py-1 rounded bg-brand-600 hover:bg-brand-700 font-semibold"
              >
                Set
              </button>
              <button
                onClick={() => {
                  onRepoChange('sample_repo');
                  setIsCustom(false);
                }}
                className="text-xs text-gray-400 hover:text-white px-1.5 py-1 rounded bg-gray-800"
                title="Reset to sample_repo"
              >
                Reset
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/repos')}
          className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-brand-600/20 text-brand-300 border border-brand-500/30 hover:bg-brand-600/30 transition"
        >
          <FolderGit2 className="w-3.5 h-3.5" /> Manage Repos
        </button>

        <button className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-gray-800 transition">
          <Bell className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 pl-4 border-l border-gray-800">
          <div className="w-8 h-8 rounded-full bg-brand-600 flex items-center justify-center text-white font-bold text-sm shadow-md">
            DV
          </div>
          <div className="hidden sm:block">
            <p className="text-sm font-semibold text-white">Developer</p>
            <p className="text-xs text-gray-400">Admin Role</p>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Navbar;

