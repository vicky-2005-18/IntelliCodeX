import React from 'react';
import DashboardPage from './DashboardPage';

interface AnalyticsProps {
  currentRepo: string;
  onSelectRepo?: (repoId: string) => void;
}

const AnalyticsPage: React.FC<AnalyticsProps> = ({ currentRepo, onSelectRepo }) => {
  return <DashboardPage currentRepo={currentRepo} onSelectRepo={onSelectRepo} />;
};

export default AnalyticsPage;
