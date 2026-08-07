"use client";

import { FileText } from "lucide-react";
import { useMemo, useState } from "react";
import type { ChatSource } from "@/lib/types";

/** When several chunks come from the same document, every chip renders the
 * same filename and the row looks like the file was cited three times. Number
 * them per document — "report.pdf · passage 2" — so it's obvious they're
 * distinct passages. Only shown when a document actually contributes more than
 * one, to avoid a pointless "passage 1" on every single-hit citation. */
function usePassageLabels(sources: ChatSource[]): (string | null)[] {
  return useMemo(() => {
    const totalPerDoc = new Map<string, number>();
    for (const s of sources) {
      const key = s.document_id ?? s.filename;
      totalPerDoc.set(key, (totalPerDoc.get(key) ?? 0) + 1);
    }
    const seen = new Map<string, number>();
    return sources.map((s) => {
      const key = s.document_id ?? s.filename;
      const n = (seen.get(key) ?? 0) + 1;
      seen.set(key, n);
      return (totalPerDoc.get(key) ?? 0) > 1 ? `passage ${n}` : null;
    });
  }, [sources]);
}

export function SourceChips({ sources }: { sources: ChatSource[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const passageLabels = usePassageLabels(sources);
  if (!sources.length) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {sources.map((s, i) => (
        <div key={i} className="relative">
          <button
            onClick={() => setOpenIndex(openIndex === i ? null : i)}
            title={passageLabels[i] ? `${s.filename} — ${passageLabels[i]}` : s.filename}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1.5 text-xs text-muted hover:border-primary/50 hover:text-foreground hover:shadow-sm transition-all"
          >
            <FileText size={11} />
            <span className="font-semibold brand-text">[{i + 1}]</span>
            <span className="max-w-[10rem] truncate">{s.filename}</span>
            {passageLabels[i] && (
              <span className="shrink-0 rounded-full bg-surface-hover px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {passageLabels[i]}
              </span>
            )}
          </button>
          {openIndex === i && (
            <div className="absolute bottom-full left-0 mb-2 w-72 rounded-2xl border border-border bg-surface p-3.5 text-xs shadow-xl z-20 animate-scale-in">
              <p className="font-semibold text-foreground mb-1 truncate">{s.filename}</p>
              {passageLabels[i] && (
                <p className="mb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                  {passageLabels[i]}
                </p>
              )}
              <p className="text-muted-foreground line-clamp-6 whitespace-pre-wrap">{s.snippet}</p>
              <p className="mt-1.5 text-[10px] text-muted-foreground">relevance score: {s.score.toFixed(2)}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
