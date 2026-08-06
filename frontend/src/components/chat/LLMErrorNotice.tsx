"use client";

import { AlertTriangle, ChevronDown, ChevronRight, Clock, KeyRound, Gauge } from "lucide-react";
import { useState } from "react";
import type { LLMError } from "@/lib/types";

/** Quota exhaustion is the single most common way this app stops answering on a
 * free-tier key, and it used to surface as a generic "check your API key"
 * message — which sends you to fix something that isn't broken. This renders
 * the cause explicitly, and makes clear that retrieval still worked. */
export function LLMErrorNotice({ error }: { error: LLMError }) {
  const [open, setOpen] = useState(false);

  const style =
    error.kind === "quota" || error.kind === "rate_limit"
      ? { icon: Gauge, tone: "border-warning/40 bg-warning-bg text-warning" }
      : error.kind === "auth"
      ? { icon: KeyRound, tone: "border-danger/30 bg-danger-bg text-danger" }
      : { icon: AlertTriangle, tone: "border-danger/30 bg-danger-bg text-danger" };
  const Icon = style.icon;

  const heading =
    error.kind === "quota"
      ? "LLM provider quota exhausted"
      : error.kind === "rate_limit"
      ? "Rate limited by the LLM provider"
      : error.kind === "auth"
      ? "LLM provider rejected the API key"
      : error.kind === "timeout"
      ? "The model timed out"
      : error.kind === "context_length"
      ? "Context window exceeded"
      : "Couldn't reach the language model";

  return (
    <div className={`mt-2 rounded-2xl border px-4 py-3 text-sm ${style.tone}`} role="alert">
      <div className="flex items-start gap-2.5">
        <Icon size={17} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{heading}</p>
          <p className="mt-1 leading-relaxed opacity-90">{error.message}</p>

          {error.retry_after_seconds != null && (
            <p className="mt-1.5 inline-flex items-center gap-1.5 text-xs opacity-80">
              <Clock size={12} />
              Provider suggests retrying in ~{error.retry_after_seconds}s
            </p>
          )}

          {error.detail && (
            <>
              <button
                onClick={() => setOpen(!open)}
                className="mt-2 inline-flex items-center gap-1 text-xs underline underline-offset-2 opacity-70 hover:opacity-100"
              >
                {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                {open ? "Hide" : "Show"} provider response
              </button>
              {open && (
                <pre className="mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface-2 p-2.5 text-[11px] leading-relaxed text-foreground/80">
                  {error.detail}
                </pre>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
