export interface User {
  id: string;
  username: string;
  email: string;
  role: string;
}

export interface Repository {
  repo_id: string;
  repo_path: string;
  backend: string;
  owner_id: string;
  num_files: number;
  num_chunks: number;
  created_at: number;
}

export interface BugCandidate {
  file_path: string;
  function: string;
  line_number: number;
  confidence_score: number;
  semantic_similarity: number;
  explanation: string;
  snippet: string;
  kind: string;
  graph_context?: {
    callers: string[];
    callees: string[];
    in_degree: number;
  };
}

export interface BugLocalizationResult {
  repo_id: string;
  error_type: string;
  error_message: string;
  parsed_frames_count: number;
  parsed_frames?: Array<{
    file_path: string;
    line_number: number;
    function: string;
    language: string;
  }>;
  candidates: BugCandidate[];
  recommended_focus?: BugCandidate;
  root_cause_explanation?: string;
}

export interface PatchValidation {
  syntax_valid: boolean;
  syntax_error?: string | null;
  git_apply_valid: boolean;
  git_apply_error?: string | null;
  git_apply_skipped?: boolean;
  has_changes: boolean;
}

export interface GeneratedPatch {
  patch_id: string;
  repo_id: string;
  target_file: string;
  original_code: string;
  suggested_patch: string;
  git_diff: string;
  explanation: string;
  confidence_score: number;
  localization_confidence?: number;
  localization?: {
    candidates: BugCandidate[];
    root_cause_explanation: string;
    parsed_frames: Array<{ file_path: string; line_number: number; function: string; language: string }>;
  };
  rag_context_chunks?: Array<{ file: string; name: string; lines: string; score: number }>;
  validation?: PatchValidation;
  llm_generated?: boolean;
  error_type?: string;
  status: 'pending' | 'approved' | 'rejected' | 'applied' | 'failed';
  manually_edited?: boolean;
  apply_result?: { success: boolean; error?: string; backup_path?: string };
}

export interface ChatResponse {
  answer: string;
  intent?: string;
  confidence_score: number;
  retrieved_chunks: Array<{ file: string; name: string; lines: string; score: number }>;
  relevant_files?: string[];
  functions?: Array<{ file: string; name: string; lines: string; kind: string }>;
  code_snippets?: Array<{ file: string; name: string; lines: string; code: string; score: number }>;
  dependency_relationships?: Array<{ source: string; target: string; relationship: string }>;
  unused_files_detected?: string[];
  architecture_summary?: string;
}

export interface AnalyticsMetrics {
  repo_id: string;
  total_files: number;
  total_classes: number;
  total_functions: number;
  total_dependencies: number;
  total_bugs_detected: number;
  ai_queries_count: number;
  circular_dependencies_count: number;
  health_score: number;
  language_distribution: Record<string, number>;
  largest_modules: Array<{
    file_path: string;
    lines: number;
    chars: number;
    language: string;
  }>;
}

export interface CytoscapeElement {
  data: {
    id: string;
    label?: string;
    source?: string;
    target?: string;
    type?: string;
    relationship?: string;
    external?: boolean;
    internal?: boolean;
  };
}

export interface GraphResponse {
  repo_id: string;
  nodes_count: number;
  edges_count: number;
  circular_dependencies: string[][];
  cytoscape: {
    nodes: CytoscapeElement[];
    edges: CytoscapeElement[];
  };
}
