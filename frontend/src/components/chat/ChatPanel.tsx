"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import * as api from "@/lib/api-client";
import { useToast } from "@/lib/toast-context";
import { EXAMPLE_PROMPTS } from "@/lib/suggestions";
import { MessageBubble, type DisplayMessage } from "./MessageBubble";
import { Composer } from "./Composer";
import type { ChatSource } from "@/lib/types";

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

      try {
        await api.streamChat(
          text,
          conversationId,
          {
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
            onError: () => {
              sawError = true;
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
          sources: finalSources,
          cached: finalCached,
          latency_ms: finalLatency || null,
        },
      ]);
      setStreaming(null);
      setSending(false);
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    [conversationId, push, queryClient, router]
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
            <EmptyState onPick={handleSend} />
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
      <Composer onSend={handleSend} onStop={handleStop} disabled={sending} isStreaming={sending} />
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="relative flex flex-col items-center justify-center gap-7 py-16 text-center overflow-hidden">
      <div className="brand-glow" />
      <div className="relative brand-mark w-14 h-14 rounded-2xl flex items-center justify-center text-white shadow-lg animate-scale-in">
        <Sparkles size={24} strokeWidth={2.25} />
      </div>
      <div className="relative">
        <h2 className="text-2xl font-semibold tracking-tight brand-text">How can I help you today?</h2>
        <p className="mt-2 text-sm text-muted-foreground max-w-sm mx-auto">
          Ask a question and I&apos;ll search your organization&apos;s documents for grounded, cited answers.
        </p>
      </div>
      <div className="relative grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-lg">
        {EXAMPLE_PROMPTS.map(({ icon: Icon, text }) => (
          <button
            key={text}
            onClick={() => onPick(text)}
            className="group flex items-start gap-3 text-left text-sm rounded-2xl border border-border bg-surface px-4 py-3.5 hover:border-primary/40 hover:shadow-md hover:-translate-y-0.5 transition-all text-foreground/90"
          >
            <span className="mt-0.5 w-7 h-7 rounded-lg bg-accent text-accent-foreground flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <Icon size={14} />
            </span>
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}
