import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FolderGit2,
  MessageSquareCode,
  Network,
  Bug,
  GitPullRequest,
  BarChart3,
  FileText,
  ShieldCheck,
  Cpu
} from 'lucide-react';

const Sidebar: React.FC = () => {
  const navItems = [
    { to: '/', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/repos', label: 'Repositories', icon: FolderGit2 },
    { to: '/chat', label: 'AI Assistant', icon: MessageSquareCode },
    { to: '/graph', label: 'Dependency Graph', icon: Network },
    { to: '/bugs', label: 'Bug Localizer', icon: Bug },
    { to: '/patches', label: 'Patch Reviewer', icon: GitPullRequest },
    { to: '/analytics', label: 'Analytics', icon: BarChart3 },
    { to: '/docs', label: 'Doc Generator', icon: FileText },
    { to: '/review', label: 'Code Review', icon: ShieldCheck },
  ];

  return (
    <aside className="w-64 bg-dark-surface border-r border-gray-800 flex flex-col h-screen sticky top-0">
      {/* Brand Header */}
      <div className="p-6 border-b border-gray-800 flex items-center gap-3">
        <div className="p-2 bg-brand-600 rounded-lg text-white shadow-lg shadow-brand-500/20">
          <Cpu className="w-6 h-6 animate-pulse" />
        </div>
        <div>
          <h1 className="font-bold text-lg text-white tracking-wide">IntelliCodeX</h1>
          <p className="text-xs text-blue-400 font-medium">Enterprise AI Platform</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-150 ${
                  isActive
                    ? 'bg-brand-600/20 text-brand-400 border border-brand-500/30 shadow-md'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/60'
                }`
              }
            >
              <Icon className="w-5 h-5" />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      {/* Status Footer */}
      <div className="p-4 border-t border-gray-800 text-xs text-gray-500 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
          <span>AI Engine: Active</span>
        </div>
        <span className="text-gray-600">v1.0.0</span>
      </div>
    </aside>
  );
};

export default Sidebar;
