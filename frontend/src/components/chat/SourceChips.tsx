"use client";

import { FileText } from "lucide-react";
import { useState } from "react";
import type { ChatSource } from "@/lib/types";

export function SourceChips({ sources }: { sources: ChatSource[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  if (!sources.length) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {sources.map((s, i) => (
        <div key={i} className="relative">
          <button
            onClick={() => setOpenIndex(openIndex === i ? null : i)}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1.5 text-xs text-muted hover:border-primary/50 hover:text-foreground hover:shadow-sm transition-all"
          >
            <FileText size={11} />
            <span className="font-semibold brand-text">[{i + 1}]</span>
            <span className="max-w-[10rem] truncate">{s.filename}</span>
          </button>
          {openIndex === i && (
            <div className="absolute bottom-full left-0 mb-2 w-72 rounded-2xl border border-border bg-surface p-3.5 text-xs shadow-xl z-20 animate-scale-in">
              <p className="font-semibold text-foreground mb-1 truncate">{s.filename}</p>
              <p className="text-muted-foreground line-clamp-6 whitespace-pre-wrap">{s.snippet}</p>
              <p className="mt-1.5 text-[10px] text-muted-foreground">relevance score: {s.score.toFixed(2)}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
