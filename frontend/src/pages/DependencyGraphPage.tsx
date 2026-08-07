import React, { useEffect, useRef, useState } from 'react';
import api from '../services/api';
import cytoscape from 'cytoscape';
import { Network, RefreshCw, AlertTriangle, Search } from 'lucide-react';

interface GraphProps {
  currentRepo: string;
}

const DependencyGraphPage: React.FC<GraphProps> = ({ currentRepo }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [circular, setCircular] = useState<string[][]>([]);
  const [nodeCount, setNodeCount] = useState<number>(0);
  const [edgeCount, setEdgeCount] = useState<number>(0);

  useEffect(() => {
    fetchGraph();
  }, [currentRepo]);

  const fetchGraph = async () => {
    setLoading(true);
    try {
      const res = await api.get(`/graph/${encodeURIComponent(currentRepo)}`);
      setNodeCount(res.data.nodes_count);
      setEdgeCount(res.data.edges_count);
      setCircular(res.data.circular_dependencies || []);

      if (containerRef.current && res.data.cytoscape) {
        cytoscape({
          container: containerRef.current,
          elements: [
            ...res.data.cytoscape.nodes,
            ...res.data.cytoscape.edges,
          ],
          style: [
            {
              selector: 'node',
              style: {
                'background-color': '#3b82f6',
                label: 'data(label)',
                color: '#f3f4f6',
                'font-size': '11px',
                'text-valign': 'bottom',
                'text-margin-y': 4,
                width: 28,
                height: 28,
              },
            },
            {
              selector: 'node[type="external"]',
              style: {
                'background-color': '#8b5cf6',
                shape: 'ellipse',
              },
            },
            {
              selector: 'node[type="class"]',
              style: {
                'background-color': '#10b981',
                shape: 'rectangle',
              },
            },
            {
              selector: 'node[type="function"]',
              style: {
                'background-color': '#f59e0b',
                shape: 'diamond',
              },
            },
            {
              selector: 'edge',
              style: {
                width: 1.5,
                'line-color': '#4b5563',
                'target-arrow-color': '#4b5563',
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
              },
            },
          ],
          layout: {
            name: 'cose',
            animate: false,
          },
        });
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Network className="w-7 h-7 text-brand-400" /> Interactive Dependency Graph
          </h1>
          <p className="text-gray-400 text-xs mt-0.5">
            File relationships, class inheritance, method calls, external libraries & circular dependency audit.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400 bg-gray-900 px-3 py-1.5 rounded-lg border border-gray-800">
            Nodes: {nodeCount} | Edges: {edgeCount}
          </span>
          <button
            onClick={fetchGraph}
            className="p-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {circular.length > 0 && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
          <span>Warning: Detected {circular.length} circular import cycles in repository architecture.</span>
        </div>
      )}

      {/* Graph Visualizer Canvas */}
      <div className="glass-card relative h-[600px] overflow-hidden">
        {loading && (
          <div className="absolute inset-0 z-10 bg-dark-surface/80 flex items-center justify-center text-brand-400 text-sm gap-2">
            <RefreshCw className="w-5 h-5 animate-spin" /> Rendering cytoscape topology...
          </div>
        )}
        <div ref={containerRef} className="w-full h-full" />
      </div>
    </div>
  );
};

export default DependencyGraphPage;
