"use client";

import { Square, ArrowUp, CornerDownLeft, MessagesSquare } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as api from "@/lib/api-client";
import { EXAMPLE_PROMPTS, type SuggestionPrompt } from "@/lib/suggestions";

interface ComposerProps {
  onSend: (message: string) => void;
  onStop: () => void;
  disabled: boolean;
  isStreaming: boolean;
}

const MAX_SUGGESTIONS = 6;

export function Composer({ onSend, onStop, disabled, isStreaming }: ComposerProps) {
  const [value, setValue] = useState("");
  const [dismissed, setDismissed] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Reuses the sidebar's cached conversation list (same query key) — no
  // extra network request in the common case.
  const { data: conversations = [] } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.listConversations,
  });

  const suggestions = useMemo<SuggestionPrompt[]>(() => {
    const query = value.trim().toLowerCase();
    if (!query) return [];

    const fromPrompts = EXAMPLE_PROMPTS.filter((p) => p.text.toLowerCase().includes(query));
    const fromHistory: SuggestionPrompt[] = conversations
      .filter((c) => c.title.toLowerCase().includes(query) && c.title.toLowerCase() !== query)
      .map((c) => ({ icon: MessagesSquare, text: c.title }));

    const seen = new Set<string>();
    const merged: SuggestionPrompt[] = [];
    for (const s of [...fromPrompts, ...fromHistory]) {
      const key = s.text.toLowerCase();
      if (seen.has(key) || key === query) continue;
      seen.add(key);
      merged.push(s);
      if (merged.length >= MAX_SUGGESTIONS) break;
    }
    return merged;
  }, [value, conversations]);

  const dropdownOpen = !dismissed && suggestions.length > 0;

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  // Close the dropdown on outside click.
  useEffect(() => {
    if (!dropdownOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setDismissed(true);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [dropdownOpen]);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    setDismissed(false);
    setActiveIndex(0);
  };

  const submit = (text?: string) => {
    const trimmed = (text ?? value).trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    setDismissed(true);
  };

  const selectSuggestion = (text: string) => {
    setValue(text);
    setDismissed(true);
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (dropdownOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % suggestions.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setDismissed(true);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        selectSuggestion(suggestions[activeIndex].text);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="bg-surface px-4 py-3 md:px-6 md:py-5">
      <div className="mx-auto max-w-3xl">
        <div ref={containerRef} className="relative">
          {dropdownOpen && (
            <div className="absolute bottom-full left-0 right-0 mb-2 rounded-2xl border border-border bg-surface shadow-xl overflow-hidden animate-scale-in origin-bottom z-20">
              {suggestions.map((s, i) => (
                <button
                  key={s.text}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => selectSuggestion(s.text)}
                  onMouseEnter={() => setActiveIndex(i)}
                  className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left text-sm transition-colors ${
                    i === activeIndex ? "bg-accent text-accent-foreground" : "text-foreground hover:bg-surface-hover"
                  }`}
                >
                  <s.icon size={14} className="shrink-0 opacity-70" />
                  <span className="flex-1 truncate">{s.text}</span>
                  {i === activeIndex && <CornerDownLeft size={12} className="shrink-0 opacity-50" />}
                </button>
              ))}
            </div>
          )}

          <div className="brand-ring rounded-[26px]">
            <div className="flex items-end gap-2 rounded-[26px] border border-border-strong bg-background shadow-sm focus-within:shadow-md transition-shadow px-4 py-2.5">
              <textarea
                ref={textareaRef}
                value={value}
                onChange={handleChange}
                onKeyDown={handleKeyDown}
                onFocus={() => setDismissed(false)}
                placeholder="Ask anything about your organization's documents…"
                rows={1}
                disabled={disabled}
                className="flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground disabled:opacity-60"
              />
              {isStreaming ? (
                <button
                  onClick={onStop}
                  className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full bg-foreground text-background hover:opacity-85 transition-opacity"
                  aria-label="Stop generating"
                  title="Stop generating"
                >
                  <Square size={14} fill="currentColor" />
                </button>
              ) : (
                <button
                  onClick={() => submit()}
                  disabled={disabled || !value.trim()}
                  className={`shrink-0 flex items-center justify-center w-9 h-9 rounded-full transition-all ${
                    value.trim()
                      ? "brand-mark text-white hover:brightness-110 active:scale-95"
                      : "bg-surface-hover text-muted-foreground"
                  }`}
                  aria-label="Send message"
                >
                  <ArrowUp size={17} strokeWidth={2.5} />
                </button>
              )}
            </div>
          </div>
        </div>
        <p className="mt-2 text-center text-[11px] text-muted-foreground">
          Enter to send · Shift+Enter for a new line. Lumen can make mistakes — verify important facts.
        </p>
      </div>
    </div>
  );
}
