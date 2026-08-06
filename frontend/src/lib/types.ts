export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  organization_id: string | null;
  created_at: string;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export type DocumentStatus = "pending" | "processing" | "completed" | "failed";

export interface DocumentItem {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: DocumentStatus;
  error_message: string | null;
  chunk_count: number;
  owner_id: string;
  organization_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatSource {
  filename: string;
  document_id: string | null;
  chunk_id: string | null;
  score: number;
  snippet: string;
}

export type MessageRole = "user" | "assistant" | "system";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  sources: ChatSource[];
  cached: boolean;
  latency_ms: number | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface StreamEvent {
  type: "conversation" | "sources" | "token" | "done" | "error";
  data: unknown;
}

export type LLMErrorKind =
  | "quota"
  | "rate_limit"
  | "auth"
  | "timeout"
  | "unavailable"
  | "context_length"
  | "unknown";

/** Structured failure from the generation step, so the UI can distinguish
 * "your provider quota is spent" from a generic outage. */
export interface LLMError {
  kind: LLMErrorKind;
  message: string;
  retry_after_seconds: number | null;
  retryable: boolean;
  detail: string | null;
}

export interface DebugChunk {
  rank: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  snippet: string;
  score: number;
  /** Rank in the preceding stage, or null if it wasn't present there. */
  previous_rank: number | null;
}

export interface DebugStage {
  key: string;
  label: string;
  description: string;
  duration_ms: number;
  chunks: DebugChunk[];
}

export interface RetrievalDebug {
  question: string;
  rewritten_query: string;
  rewrite_applied: boolean;
  cache_hit: boolean;
  cache_note: string;
  stages: DebugStage[];
  final_prompt: string;
  answer: string | null;
  total_ms: number;
}
