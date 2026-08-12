import type {
  ChatSource,
  LLMError,
  Conversation,
  ConversationDetail,
  DocumentItem,
  RetrievalDebug,
  StreamEvent,
  Tokens,
  User,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000/api/v1";

const ACCESS_KEY = "lumen_access_token";
const REFRESH_KEY = "lumen_refresh_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

const DEFAULT_TIMEOUT_MS = 20_000;

/** Plain `fetch` never times out on its own — if the server accepts the
 * connection but never responds (e.g. a container mid-restart), the request
 * hangs forever and the caller's loading state never clears. This wraps a
 * request in its own AbortController on a timer, distinct from any signal
 * the caller passes in for e.g. a user-initiated cancel. */
async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<Response> {
  const timeoutController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), timeoutMs);

  const callerSignal = init.signal;
  if (callerSignal) {
    if (callerSignal.aborted) timeoutController.abort();
    else callerSignal.addEventListener("abort", () => timeoutController.abort(), { once: true });
  }

  try {
    return await fetch(url, { ...init, signal: timeoutController.signal });
  } catch (err) {
    if (timeoutController.signal.aborted && !callerSignal?.aborted) {
      throw new ApiError(0, "The request timed out. Please check your connection and try again.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(tokens: Tokens): void {
  localStorage.setItem(ACCESS_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg).join(", ");
    }
  } catch {
    // fall through
  }
  return res.statusText || `Request failed (${res.status})`;
}

let refreshPromise: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const refresh_token = getRefreshToken();
    if (!refresh_token) return false;
    try {
      const res = await fetchWithTimeout(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token }),
      });
      if (!res.ok) {
        clearTokens();
        return false;
      }
      const tokens = (await res.json()) as Tokens;
      setTokens(tokens);
      return true;
    } catch {
      return false;
    }
  })();
  try {
    return await refreshPromise;
  } finally {
    // In a finally: if the refresh ever rejects rather than returning false,
    // leaving the settled promise cached would make every later call reuse
    // that same failure forever.
    refreshPromise = null;
  }
}

interface RequestOpts extends RequestInit {
  auth?: boolean;
  isRetry?: boolean;
  /** Overrides DEFAULT_TIMEOUT_MS for endpoints that legitimately run long. */
  timeoutMs?: number;
}

async function apiFetch(path: string, opts: RequestOpts = {}): Promise<Response> {
  const { auth = true, isRetry, headers, timeoutMs, ...rest } = opts;
  const finalHeaders = new Headers(headers);
  if (auth) {
    const token = getAccessToken();
    if (token) finalHeaders.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetchWithTimeout(`${API_BASE}${path}`, { ...rest, headers: finalHeaders }, timeoutMs);

  if (res.status === 401 && auth && !isRetry) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return apiFetch(path, { ...opts, isRetry: true });
    }
    clearTokens();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("lumen:unauthorized"));
    }
  }

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }
  return res;
}

async function apiJson<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const res = await apiFetch(path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------- auth

export async function login(email: string, password: string): Promise<Tokens> {
  const body = new URLSearchParams({ username: email, password });
  const res = await fetchWithTimeout(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) throw new ApiError(res.status, await parseErrorDetail(res));
  const tokens = (await res.json()) as Tokens;
  setTokens(tokens);
  return tokens;
}

export async function register(input: {
  email: string;
  password: string;
  full_name?: string;
  organization_name?: string;
}): Promise<User> {
  return apiJson<User>("/auth/register", {
    method: "POST",
    auth: false,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function fetchMe(): Promise<User> {
  return apiJson<User>("/auth/me");
}

export function logout(): void {
  clearTokens();
}

// ----------------------------------------------------------- documents

export async function listDocuments(): Promise<DocumentItem[]> {
  return apiJson<DocumentItem[]>("/documents/");
}

export async function getDocument(id: string): Promise<DocumentItem> {
  return apiJson<DocumentItem>(`/documents/${id}`);
}

export async function deleteDocument(id: string): Promise<void> {
  await apiFetch(`/documents/${id}`, { method: "DELETE" });
}

export function uploadDocument(
  file: File,
  onProgress?: (pct: number) => void
): Promise<DocumentItem> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/documents/upload`);
    xhr.timeout = 120_000; // large files legitimately take a while; a true stall shouldn't hang forever
    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        let detail = xhr.statusText;
        try {
          detail = JSON.parse(xhr.responseText)?.detail || detail;
        } catch {
          // ignore
        }
        reject(new ApiError(xhr.status, detail));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
    xhr.ontimeout = () => reject(new ApiError(0, "The upload timed out. Please try again."));

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

// -------------------------------------------------------- conversations

export async function listConversations(): Promise<Conversation[]> {
  return apiJson<Conversation[]>("/conversations/");
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return apiJson<ConversationDetail>(`/conversations/${id}`);
}

export async function createConversation(title?: string): Promise<Conversation> {
  return apiJson<Conversation>("/conversations/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export async function deleteConversation(id: string): Promise<void> {
  await apiFetch(`/conversations/${id}`, { method: "DELETE" });
}

// --------------------------------------------------------------- debug

/** Superuser-only. Retrieval stages are computed locally and cost nothing;
 * `generateAnswer` adds one LLM call. */
export async function debugRetrieval(
  message: string,
  opts: { conversationId?: string; generateAnswer?: boolean } = {}
): Promise<RetrievalDebug> {
  return apiJson<RetrievalDebug>("/debug/retrieval", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      conversation_id: opts.conversationId ?? null,
      generate_answer: opts.generateAnswer ?? false,
    }),
    // Five retrieval stages back-to-back on CPU (plus optional generation)
    // legitimately outlasts the default 20s budget.
    timeoutMs: 90_000,
  });
}

// ---------------------------------------------------------------- chat

export interface StreamHandlers {
  /** Restrict retrieval to these documents and split the context budget
   * across them. Empty/omitted searches everything (the default). */
  documentIds?: string[];
  onConversation?: (id: string) => void;
  onSources?: (sources: ChatSource[]) => void;
  onToken?: (token: string) => void;
  onDone?: (info: { cached: boolean; latency_ms: number }) => void;
  onError?: (error: LLMError | string) => void;
}

export async function streamChat(
  message: string,
  conversationId: string | undefined,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const body = JSON.stringify({
    message,
    conversation_id: conversationId ?? null,
    document_ids: handlers.documentIds?.length ? handlers.documentIds : null,
  });

  // Deliberately a bare `fetch` rather than `apiFetch`: the response is a
  // stream that must not be buffered or wrapped in a timeout. That meant it
  // also missed apiFetch's refresh-on-401 path, so once the 60-minute access
  // token expired chat was the one thing in the app that stopped working
  // while everything else silently recovered. The retry is reproduced here.
  const send = async (): Promise<Response> => {
    const token = getAccessToken();
    return fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body,
      signal,
    });
  };

  let res = await send();
  if (res.status === 401) {
    if (await tryRefresh()) {
      res = await send();
    } else {
      clearTokens();
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("lumen:unauthorized"));
      }
    }
  }

  if (!res.ok || !res.body) {
    throw new ApiError(res.status, await parseErrorDetail(res));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") continue;

      let event: StreamEvent;
      try {
        event = JSON.parse(payload);
      } catch {
        continue;
      }

      switch (event.type) {
        case "conversation":
          handlers.onConversation?.((event.data as { conversation_id: string }).conversation_id);
          break;
        case "sources":
          handlers.onSources?.(event.data as ChatSource[]);
          break;
        case "token":
          handlers.onToken?.(event.data as string);
          break;
        case "done":
          handlers.onDone?.(event.data as { cached: boolean; latency_ms: number });
          break;
        case "error":
          // Newer backends send a structured LLMError; older ones sent a bare
          // string. Accept both so a version skew degrades instead of breaking.
          handlers.onError?.(
            event.data && typeof event.data === "object"
              ? (event.data as LLMError)
              : String(event.data)
          );
          break;
      }
    }
  }
}
