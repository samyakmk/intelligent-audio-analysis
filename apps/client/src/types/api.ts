export type Id = string;
export type IsoDate = string;

export type ReadinessKey =
  | 'original_ready'
  | 'transcript_ready'
  | 'intelligence_ready'
  | 'indexed_ready';

export type RecordingState =
  | 'uploading'
  | 'verifying'
  | 'sealed'
  | 'processing'
  | 'ready'
  | 'partial'
  | 'failed_retryable'
  | 'failed_final'
  | 'cancelled'
  | 'deleting'
  | 'deleted';

export type StageName =
  | 'uploading'
  | 'verifying'
  | 'transcribing'
  | 'extracting_intelligence'
  | 'indexing';

export interface Workspace {
  id: Id;
  name: string;
  role?: 'owner' | 'member' | 'viewer';
  retained_recordings?: number;
  retained_bytes?: number;
  recording_limit?: number;
  byte_limit?: number;
  monthly_spend_usd?: number;
  monthly_budget_usd?: number;
}

export interface Principal {
  id: Id;
  name: string;
  email?: string;
  initials?: string;
}

export interface Session {
  principal: Principal;
  workspace: Workspace;
  workspaces: Workspace[];
  csrf_token?: string;
  demo_mode?: boolean;
}

export interface Readiness {
  original_ready: boolean;
  transcript_ready: boolean;
  intelligence_ready: boolean;
  indexed_ready: boolean;
}

export interface StageStatus {
  stage: StageName;
  status: 'pending' | 'active' | 'complete' | 'failed' | 'skipped';
  message?: string;
  started_at?: IsoDate;
  completed_at?: IsoDate;
}

export interface ProcessingIssue {
  code: string;
  message: string;
  retryable: boolean;
  action?: string;
}

export interface Recording {
  id: Id;
  title: string;
  filename: string;
  content_type?: string;
  size_bytes: number;
  sha256?: string;
  duration_ms?: number;
  created_at: IsoDate;
  recorded_at?: IsoDate;
  expires_at?: IsoDate;
  language?: string;
  mode?: 'standard' | 'deep';
  state: RecordingState;
  readiness: Readiness;
  stages?: StageStatus[];
  issues?: ProcessingIssue[];
  tags?: string[];
  folder?: string;
  version?: number;
  is_fixture?: boolean;
  fixture_label?: string;
  experience?: 'recording' | 'day_demo';
  requested_batch_count?: number;
}

export interface UploadOptions {
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  language: string;
  vocabulary_hints: string[];
  mode: 'standard' | 'deep';
  provider_data_approved: boolean;
  experience?: 'recording' | 'day_demo';
  batch_count?: number;
}

export type DayStage = 'waiting' | 'transcribing' | 'reconciling' | 'indexing' | 'extracting' | 'published';

export interface DayTranscriptSegment {
  id: Id;
  start_ms: number;
  end_ms: number;
  speaker_id?: string;
  speaker_name?: string;
  text: string;
}

export interface DayChange {
  id: Id;
  operation: 'add' | 'supersede' | 'resolve';
  kind: 'decision' | 'action' | 'fact' | 'open_question';
  key: string;
  before?: string | null;
  after: string;
  owner_before?: string | null;
  owner_after?: string | null;
  batch_index: number;
  evidence?: Omit<Citation, 'recording_id' | 'transcript_version'>;
}

export interface DayMemoryItem {
  id: Id;
  key: string;
  kind: DayChange['kind'];
  text: string;
  status: 'current' | 'superseded' | 'resolved' | 'open' | 'done';
  owner?: string | null;
  due?: string | null;
  effective_batch: number;
  superseded_by?: string;
  evidence: Omit<Citation, 'recording_id' | 'transcript_version'>[];
}

export interface DayMemory {
  summary: string;
  decisions: DayMemoryItem[];
  actions: DayMemoryItem[];
  facts: DayMemoryItem[];
  open_questions: DayMemoryItem[];
}

export interface DayBatch {
  id: Id;
  index: number;
  number: number;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  size_bytes?: number | null;
  status: 'queued' | 'processing' | 'complete';
  stage: DayStage;
  transcript: DayTranscriptSegment[];
  reconciliation: {
    context_segments_used?: number;
    speaker_clusters_carried?: string[];
    boundary_revision?: string;
  };
  index_state: {
    transcript_segments?: number;
    selected_segments?: number;
    excluded_segments?: number;
    evidence_chunks?: number;
    lexical_terms?: number;
    vector_embeddings?: number;
    neighbor_links?: number;
    filter_decisions?: {
      segment_id: string;
      keep: boolean;
      category: string;
      reason: string;
      confidence: number;
    }[];
  };
  pending_changes: DayChange[];
  published_snapshot: Partial<DayMemory>;
  provider?: {
    speech?: { provider?: string; model_alias?: string; resolved_model?: string; usage?: Record<string, unknown> } | null;
    filter?: { provider?: string; model_alias?: string; resolved_model?: string; usage?: Record<string, unknown> } | null;
    intelligence?: { provider?: string; model_alias?: string; resolved_model?: string; usage?: Record<string, unknown> } | null;
  };
  audio_filter?: {
    decision?: 'skip_clear_silence' | 'pass_to_speech' | 'pass_uncertain';
    reason?: string;
    active_frame_ratio?: number | null;
    rms?: number | null;
    peak?: number | null;
  };
  started_at?: IsoDate | null;
  completed_at?: IsoDate | null;
}

export interface DayAskMessage {
  id: Id;
  question: string;
  answer: string;
  citations: Citation[];
  abstained: boolean;
  provisional: boolean;
  watermark_ms: number;
  processed_batch_count: number;
  batch_index?: number | null;
  strategy: string;
  created_at: IsoDate;
}

export interface DaySession {
  id: Id;
  recording_id: Id;
  title: string;
  description?: string | null;
  status: 'ready' | 'processing' | 'complete' | 'failed';
  batch_count: number;
  processed_batch_count: number;
  active_batch_index?: number | null;
  current_stage: string;
  watermark_ms: number;
  duration_ms: number;
  revision: number;
  memory: DayMemory;
  changes: DayChange[];
  ask_history: DayAskMessage[];
  suggested_questions: string[];
  batches: DayBatch[];
  mock: boolean;
  notice?: string | null;
  error?: { code: string; message: string } | null;
}

export interface UploadSession {
  id: Id;
  recording_id: Id;
  upload_url: string;
  upload_method?: 'PUT' | 'POST';
  upload_headers?: Record<string, string>;
  expires_at: IsoDate;
  max_bytes?: number;
}

export interface Citation {
  recording_id: Id;
  recording_title?: string;
  transcript_version: string | number;
  segment_id: Id;
  start_ms: number;
  end_ms: number;
  speaker_id?: Id;
  quote?: string;
}

export interface TimelineInterval {
  id: Id;
  start_ms: number;
  end_ms: number;
  state: 'speech' | 'silence' | 'unreadable';
}

export interface TranscriptSegment {
  id: Id;
  start_ms: number;
  end_ms: number;
  channel_id?: string;
  language_bcp47: string;
  speaker_cluster_id?: Id;
  speaker_name?: string;
  overlap_group_id?: Id;
  text: string;
  confidence?: number;
  version?: number;
}

export interface Speaker {
  id: Id;
  label: string;
  display_name?: string;
  segment_count?: number;
}

export interface Transcript {
  recording_id: Id;
  version: string | number;
  language: string;
  duration_ms: number;
  intervals: TimelineInterval[];
  segments: TranscriptSegment[];
  speakers: Speaker[];
}

export interface EvidenceItem {
  id: Id;
  text?: string;
  claim?: string;
  decision?: string;
  task?: string;
  question?: string;
  confidence?: number;
  status?: string;
  owner_text?: string;
  due_text?: string;
  due_at?: IsoDate;
  participants?: string[];
  ambiguities?: string[];
  evidence: Citation[];
}

export interface Topic {
  id?: Id;
  label: string;
  parent?: string;
  intervals?: { start_ms: number; end_ms: number }[];
  evidence: Citation[];
}

export interface RecordingIntelligence {
  recording_id: Id;
  version: string | number;
  title: { text: string; evidence: Citation[]; confidence?: number };
  summary: { short: string; detailed?: string; evidence: Citation[] };
  facts: EvidenceItem[];
  decisions: EvidenceItem[];
  actions: EvidenceItem[];
  topics: Topic[];
  open_questions: EvidenceItem[];
  warnings: string[];
  summary_style?: string;
  provenance?: Record<string, unknown>;
}

export interface SearchFilters {
  mode: 'mixed' | 'exact' | 'semantic';
  date_from?: string;
  date_to?: string;
  recording_id?: Id;
  speaker?: string;
  topic?: string;
  action_state?: string;
}

export interface SearchResult {
  id: Id;
  recording_id: Id;
  recording_title: string;
  kind: 'transcript' | 'action' | 'decision' | 'fact' | 'summary';
  snippet: string;
  start_ms: number;
  end_ms: number;
  speaker?: string;
  topic?: string;
  score?: number;
  citation: Citation;
}

export interface SearchResponse {
  items: SearchResult[];
  total: number;
  took_ms?: number;
  mode?: SearchFilters['mode'];
  requested_mode?: SearchFilters['mode'];
  effective_mode?: SearchFilters['mode'] | 'lexical';
  semantic_available?: boolean;
  retrieval_note?: string;
}

export type AskScope =
  | { type: 'library' }
  | { type: 'recording'; recording_id: Id }
  | { type: 'selection'; recording_id: Id; segment_ids: Id[] };

export interface AskSession {
  id: Id;
  scope: AskScope;
  created_at: IsoDate;
  max_spend_usd?: number;
}

export interface AskMessage {
  id: Id;
  role: 'user' | 'assistant';
  content: string;
  created_at: IsoDate;
  citations?: Citation[];
  status?: 'validating' | 'complete' | 'abstained' | 'failed';
  abstention_reason?: string;
  cost_usd?: number;
  provenance?: Record<string, unknown>;
}

export interface AskReply {
  session_id: Id;
  message: AskMessage;
}

export interface ActionTask {
  id: Id;
  recording_id: Id;
  recording_title?: string;
  task: string;
  owner_text?: string;
  due_text?: string;
  due_at?: IsoDate;
  status: 'open' | 'in_progress' | 'done' | 'dismissed' | 'unresolved';
  ambiguities?: string[];
  evidence: Citation[];
  version?: number;
}

export interface Recap {
  id: Id;
  title: string;
  period: string;
  summary: string;
  topics: Topic[];
  decisions: EvidenceItem[];
  actions: ActionTask[];
  citations: Citation[];
  generated_at: IsoDate;
}

export interface SummaryStyle {
  id: string;
  name: string;
  description: string;
}

export interface ProviderCapabilities {
  provider_mode: 'fixture' | 'gemini';
  remote_processing: boolean;
  data_policy: string;
  allowed_languages: string[];
  max_audio_duration_seconds: number;
  speech: {
    model_alias: string;
    max_duration_seconds: number;
    diarization: boolean;
    timestamps: boolean;
    vocabulary_hints: boolean;
  };
  intelligence: {
    cheap_model_alias: string;
    strong_model_alias: string | null;
    deep_available: boolean;
  };
  ask: {
    cheap_model_alias: string;
    strong_model_alias: string | null;
    deep_available: boolean;
  };
  features: {
    transcript: boolean;
    intelligence: boolean;
    mind_map: boolean;
    search: boolean;
    ask: boolean;
    tasks: boolean;
    exports: boolean;
  };
}

export interface CostEvent {
  id: Id;
  recording_id?: Id;
  recording_title?: string;
  stage: string;
  model_alias: string;
  resolved_model?: string;
  billed_units: string;
  estimated_cost_usd: number;
  reconciled_cost_usd?: number | null;
  reconciled_at?: IsoDate;
  cached?: boolean;
  reused?: boolean;
  retry?: number;
  escalation_reason?: string;
  created_at: IsoDate;
}

export interface CostSummary {
  period: string;
  estimated_incurred_usd: number;
  reconciled_usd?: number;
  budget_usd: number;
  baseline_estimate_usd: number;
  optimized_estimate_usd: number;
  modeled_delta_usd: number;
  avoided_audio_seconds?: number;
  avoided_calls?: number;
  avoided_tokens?: number;
  cache_hits?: number;
  events: CostEvent[];
  by_stage: { stage: string; amount_usd: number }[];
  baseline_version?: string;
  quality_gate_passed?: boolean;
}

export interface ExportRequest {
  format: 'markdown' | 'json' | 'csv' | 'ics';
  resource: 'recording' | 'tasks' | 'recap';
  recording_id?: Id;
  recap_id?: Id;
}

export interface ExportResult {
  filename: string;
  content_type: string;
  download_url?: string;
  content?: string;
}

export interface Page<T> {
  items: T[];
  total?: number;
  next_cursor?: string | null;
}
