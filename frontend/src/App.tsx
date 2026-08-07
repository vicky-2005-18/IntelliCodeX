import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Navbar from './components/Navbar';
import DashboardPage from './pages/DashboardPage';
import RepositoryListPage from './pages/RepositoryListPage';
import ChatPage from './pages/ChatPage';
import DependencyGraphPage from './pages/DependencyGraphPage';
import BugLocalizationPage from './pages/BugLocalizationPage';
import PatchReviewPage from './pages/PatchReviewPage';
import AnalyticsPage from './pages/AnalyticsPage';
import DocGeneratorPage from './pages/DocGeneratorPage';
import CodeReviewPage from './pages/CodeReviewPage';

const App: React.FC = () => {
  const [currentRepo, setCurrentRepo] = useState<string>('sample_repo');

  return (
    <Router>
      <div className="flex h-screen bg-dark-base overflow-hidden">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <Navbar currentRepo={currentRepo} onRepoChange={setCurrentRepo} />
          <main className="flex-1 overflow-y-auto p-8">
            <Routes>
              <Route path="/" element={<DashboardPage currentRepo={currentRepo} onSelectRepo={setCurrentRepo} />} />
              <Route path="/repos" element={<RepositoryListPage currentRepo={currentRepo} onSelectRepo={setCurrentRepo} />} />
              <Route path="/chat" element={<ChatPage currentRepo={currentRepo} />} />
              <Route path="/graph" element={<DependencyGraphPage currentRepo={currentRepo} />} />
              <Route path="/bugs" element={<BugLocalizationPage currentRepo={currentRepo} />} />
              <Route path="/patches" element={<PatchReviewPage currentRepo={currentRepo} />} />
              <Route path="/analytics" element={<AnalyticsPage currentRepo={currentRepo} onSelectRepo={setCurrentRepo} />} />
              <Route path="/docs" element={<DocGeneratorPage currentRepo={currentRepo} />} />
              <Route path="/review" element={<CodeReviewPage />} />
            </Routes>
          </main>
        </div>
      </div>
    </Router>
  );
};

export default App;
