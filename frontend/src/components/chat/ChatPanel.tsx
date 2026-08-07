"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import * as api from "@/lib/api-client";
import { useToast } from "@/lib/toast-context";
import { useDocumentUploads } from "@/lib/use-document-uploads";
import { suggestionsForDocuments } from "@/lib/suggestions";
import { MessageBubble, type DisplayMessage } from "./MessageBubble";
import { Composer } from "./Composer";
import type { ChatSource, DocumentItem, LLMError } from "@/lib/types";

interface StreamingState {
  text: string;
  sources: ChatSource[];
}

let tempIdCounter = 0;
const nextTempId = () => `tmp-${Date.now()}-${++tempIdCounter}`;

export function ChatPanel({ initialConversationId }: { initialConversationId?: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { push } = useToast();
  const { uploads, handleFiles } = useDocumentUploads();
  // Same query key the scope picker and documents page use, so this is served
  // from cache rather than costing another request.
  const { data: documents = [] } = useQuery({
    queryKey: ["documents"],
    queryFn: api.listDocuments,
  });

  // Deliberately NOT seeded with initialConversationId: the guard effect
  // below compares this ref against the prop to decide whether history
  // needs (re)loading, and if we seeded it with the same value the prop
  // already has, that comparison is a no-op on the very first render —
  // exactly the case where a conversation is opened directly (e.g. the
  // URL already has ?c=<id> on mount, such as reopening a saved chat) and
  // history actually does need to load. Leaving it undefined guarantees a
  // mismatch on mount whenever there's a real id to load.
  const conversationIdRef = useRef<string | undefined>(undefined);
  const [conversationId, setConversationId] = useState<string | undefined>(initialConversationId);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [historyLoading, setHistoryLoading] = useState(!!initialConversationId);
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [sending, setSending] = useState(false);
  // Pinned document scope for the next message. Kept in the panel (not the
  // composer) so it survives the composer clearing itself after a send —
  // a follow-up comparison shouldn't silently widen back to every document.
  const [scopedDocumentIds, setScopedDocumentIds] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const scrollAnchorRef = useRef<HTMLDivElement>(null);

  const loadHistory = useCallback(async (id: string | undefined) => {
    if (!id) {
      setMessages([]);
      setHistoryLoading(false);
      return;
    }
    setHistoryLoading(true);
    try {
      const detail = await api.getConversation(id);
      setMessages(
        detail.messages.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          sources: m.sources,
          cached: m.cached,
          latency_ms: m.latency_ms,
        }))
      );
    } catch {
      push("Could not load that conversation", "error");
      setMessages([]);
    } finally {
      setHistoryLoading(false);
    }
  }, [push]);

  // Detect *external* changes to the conversation id (sidebar navigation,
  // "New chat") vs. the id we just assigned ourselves after streaming the
  // first message of a brand-new chat. Only the former should reset state —
  // the latter must not interrupt an in-flight stream.
  useEffect(() => {
    if (initialConversationId !== conversationIdRef.current) {
      conversationIdRef.current = initialConversationId;
      setConversationId(initialConversationId);
      abortRef.current?.abort();
      setStreaming(null);
      setSending(false);
      // The pinned scope belongs to the conversation you're in, not to the app.
      // Carrying it across a switch meant opening an old chat showed whichever
      // documents you last picked somewhere else — implying that conversation
      // had been scoped to them when it hadn't. Clear it on every switch.
      setScopedDocumentIds([]);
      loadHistory(initialConversationId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialConversationId]);

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streaming?.text]);

  const handleSend = useCallback(
    async (text: string) => {
      const userMsg: DisplayMessage = { id: nextTempId(), role: "user", content: text };
      setMessages((prev) => [...prev, userMsg]);
      setStreaming({ text: "", sources: [] });
      setSending(true);

      const controller = new AbortController();
      abortRef.current = controller;

      let finalText = "";
      let finalSources: ChatSource[] = [];
      let finalCached = false;
      let finalLatency = 0;
      let sawError = false;
      let llmError: LLMError | null = null;

      try {
        await api.streamChat(
          text,
          conversationId,
          {
            documentIds: scopedDocumentIds,
            onConversation: (id) => {
              if (!conversationIdRef.current) {
                conversationIdRef.current = id;
                setConversationId(id);
                router.replace(`/?c=${id}`, { scroll: false });
              }
            },
            onSources: (sources) => {
              finalSources = sources;
              setStreaming((prev) => (prev ? { ...prev, sources } : prev));
            },
            onToken: (token) => {
              finalText += token;
              setStreaming((prev) => (prev ? { ...prev, text: prev.text + token } : prev));
            },
            onDone: (info) => {
              finalCached = info.cached;
              finalLatency = info.latency_ms;
            },
            onError: (err) => {
              sawError = true;
              // Structured errors (quota, rate limit, auth) get their own
              // notice under the message; bare strings stay generic.
              if (err && typeof err === "object") llmError = err;
            },
          },
          controller.signal
        );
      } catch (err) {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          push(err instanceof Error ? err.message : "Something went wrong", "error");
          sawError = true;
        }
      }

      setMessages((prev) => [
        ...prev,
        {
          id: nextTempId(),
          role: "assistant",
          content: finalText || (sawError ? "Sorry, I couldn't generate a response. Please try again." : ""),
          llmError,
          sources: finalSources,
          cached: finalCached,
          latency_ms: finalLatency || null,
        },
      ]);
      setStreaming(null);
      setSending(false);
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    [conversationId, push, queryClient, router, scopedDocumentIds]
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const showEmptyState = !historyLoading && messages.length === 0 && !streaming;

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
        <div className="mx-auto max-w-3xl px-4 py-6 md:px-6">
          {historyLoading ? (
            <div className="space-y-4">
              {[0, 1].map((i) => (
                <div key={i} className="h-16 rounded-2xl bg-surface-hover animate-pulse" />
              ))}
            </div>
          ) : showEmptyState ? (
            <EmptyState onPick={handleSend} documents={documents} />
          ) : (
            <div className="space-y-5">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
              {streaming && (
                <MessageBubble
                  message={{
                    id: "streaming",
                    role: "assistant",
                    content: streaming.text,
                    sources: streaming.sources,
                  }}
                />
              )}
              <div ref={scrollAnchorRef} />
            </div>
          )}
        </div>
      </div>
      <Composer
        onSend={handleSend}
        onStop={handleStop}
        disabled={sending}
        isStreaming={sending}
        uploads={uploads}
        onAttachFiles={handleFiles}
        scopedDocumentIds={scopedDocumentIds}
        onScopeChange={setScopedDocumentIds}
      />
    </div>
  );
}

function EmptyState({
  onPick,
  documents,
}: {
  onPick: (text: string) => void;
  documents: DocumentItem[];
}) {
  // Built from the user's real files. A static list asking about a refund
  // policy or a "Project Zeta" returns nothing on every corpus, which makes
  // the app look broken the first time anyone tries a suggestion.
  const prompts = suggestionsForDocuments(documents);
  const ready = documents.filter((d) => d.status === "completed");

  return (
    <>
      {/* Sits outside the centred column so the light isn't clipped to it. */}
      <div className="brand-glow" />

      <div className="relative z-10 flex min-h-[62vh] flex-col items-center justify-center gap-8 py-10 text-center">
        <div className="brand-mark flex h-16 w-16 items-center justify-center rounded-[22px] text-white shadow-xl shadow-primary/20 animate-scale-in">
          <Sparkles size={28} strokeWidth={2.1} />
        </div>

        <div className="max-w-xl">
          <h2 className="text-3xl font-semibold tracking-tight brand-text sm:text-4xl">
            What do your documents say?
          </h2>
          <p className="mx-auto mt-3 max-w-md text-[15px] leading-relaxed text-muted-foreground">
            Every answer is retrieved from your own files and cited back to the exact passage — so
            you can check it, not just trust it.
          </p>

          {/* Grounds the promise in the actual corpus rather than leaving it abstract. */}
          <p className="mt-4 inline-flex items-center gap-2 rounded-full border border-border bg-surface/70 px-3 py-1 text-xs text-muted-foreground backdrop-blur">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-success" />
            </span>
            {ready.length > 0
              ? `${ready.length} document${ready.length === 1 ? "" : "s"} indexed and searchable`
              : "No documents yet — attach one to begin"}
          </p>
        </div>

        <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
          {prompts.map(({ icon: Icon, text }) => (
            <button
              key={text}
              onClick={() => onPick(text)}
              className="group relative flex items-start gap-3 overflow-hidden rounded-2xl border border-border bg-surface/80 px-4 py-4 text-left text-sm text-foreground/90 backdrop-blur transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-surface hover:shadow-lg hover:shadow-primary/5"
            >
              {/* Gradient wash on hover, so the cards feel part of the brand
                  rather than plain bordered boxes. */}
              <span className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100 bg-[var(--gradient-brand-soft)]" />
              <span className="relative mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground transition-transform group-hover:scale-110">
                <Icon size={15} />
              </span>
              <span className="relative leading-snug">{text}</span>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
