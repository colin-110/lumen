"use client";

import { Sparkles, Zap } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { SourceChips } from "./SourceChips";
import { LLMErrorNotice } from "./LLMErrorNotice";
import type { ChatSource, LLMError, MessageRole } from "@/lib/types";

export interface DisplayMessage {
  id: string;
  role: MessageRole;
  content: string;
  sources?: ChatSource[];
  cached?: boolean;
  latency_ms?: number | null;
  /** Set when generation failed with a classified provider error. */
  llmError?: LLMError | null;
}

export function MessageBubble({ message }: { message: DisplayMessage }) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end animate-fade-in-up">
        <div className="max-w-[min(38rem,80%)] rounded-2xl rounded-tr-md bg-primary text-primary-foreground px-4 py-2.5 shadow-sm">
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{message.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 animate-fade-in-up">
      <div className="brand-mark w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-white mt-0.5">
        <Sparkles size={13} strokeWidth={2.25} />
      </div>

      <div className="flex flex-col min-w-0 flex-1 max-w-[min(42rem,90%)] items-start">
        {message.content ? (
          <div className="prose-chat text-foreground">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        ) : (
          <TypingIndicator />
        )}

        {message.sources && message.sources.length > 0 && <SourceChips sources={message.sources} />}

        {message.llmError && <LLMErrorNotice error={message.llmError} />}

        {(message.cached || typeof message.latency_ms === "number") && message.content && (
          <div className="mt-2 flex items-center gap-1 text-[11px] text-muted-foreground">
            {message.cached && (
              <span className="inline-flex items-center gap-0.5">
                <Zap size={10} /> cached
              </span>
            )}
            {message.cached && typeof message.latency_ms === "number" && <span>·</span>}
            {typeof message.latency_ms === "number" && <span>{message.latency_ms}ms</span>}
          </div>
        )}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1.5 py-1.5">
      <span className="w-2 h-2 rounded-full brand-mark animate-pulse-dot" />
      <span className="w-2 h-2 rounded-full brand-mark animate-pulse-dot [animation-delay:0.15s]" />
      <span className="w-2 h-2 rounded-full brand-mark animate-pulse-dot [animation-delay:0.3s]" />
    </div>
  );
}
