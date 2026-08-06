"use client";

import { Check, FileText, Scale, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as api from "@/lib/api-client";
import type { DocumentItem } from "@/lib/types";

interface Props {
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}

/** Pins a question to specific documents. With nothing selected the chat
 * searches everything (the default); with two or more selected the backend
 * splits the context budget across them so a long document can't crowd a
 * short one out of the comparison. */
export function DocumentScopePicker({ selectedIds, onChange, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const { data: documents = [] } = useQuery({
    queryKey: ["documents"],
    queryFn: api.listDocuments,
  });

  const ready = documents.filter((d: DocumentItem) => d.status === "completed");
  const selected = ready.filter((d) => selectedIds.includes(d.id));

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  // Drop pins whose document has since been deleted, so a stale id can't be
  // sent to the API forever.
  useEffect(() => {
    if (!documents.length || !selectedIds.length) return;
    const live = new Set(ready.map((d) => d.id));
    const pruned = selectedIds.filter((id) => live.has(id));
    if (pruned.length !== selectedIds.length) onChange(pruned);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documents]);

  const toggle = (id: string) => {
    onChange(selectedIds.includes(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]);
  };

  if (!ready.length) return null;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        disabled={disabled}
        title="Limit this question to specific documents"
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors disabled:opacity-60 ${
          selectedIds.length
            ? "border-primary/40 bg-accent text-accent-foreground"
            : "border-border bg-surface text-muted-foreground hover:text-foreground"
        }`}
      >
        <Scale size={12} />
        {selectedIds.length ? `Comparing ${selectedIds.length}` : "All documents"}
      </button>

      {open && (
        <div className="absolute bottom-full left-0 mb-2 w-72 max-h-72 overflow-y-auto scrollbar-thin rounded-2xl border border-border bg-surface shadow-xl z-30 animate-scale-in">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Scope
            </span>
            {selectedIds.length > 0 && (
              <button
                onClick={() => onChange([])}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                Clear
              </button>
            )}
          </div>
          {ready.map((doc) => {
            const on = selectedIds.includes(doc.id);
            return (
              <button
                key={doc.id}
                onClick={() => toggle(doc.id)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-hover transition-colors"
              >
                <span
                  className={`w-4 h-4 shrink-0 rounded border flex items-center justify-center ${
                    on ? "brand-mark border-transparent text-white" : "border-border-strong"
                  }`}
                >
                  {on && <Check size={11} strokeWidth={3} />}
                </span>
                <FileText size={12} className="shrink-0 opacity-50" />
                <span className="flex-1 truncate">{doc.filename}</span>
              </button>
            );
          })}
          <p className="px-3 py-2 text-[11px] leading-relaxed text-muted-foreground border-t border-border">
            Pick two or more to compare them. Each pinned document is guaranteed a share of the
            context, so a long one can&apos;t crowd out a short one.
          </p>
        </div>
      )}

      {selected.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {selected.map((doc) => (
            <span
              key={doc.id}
              className="inline-flex items-center gap-1 rounded-full bg-surface-hover px-2 py-0.5 text-[11px] text-foreground"
            >
              <span className="max-w-[9rem] truncate">{doc.filename}</span>
              <button
                onClick={() => toggle(doc.id)}
                aria-label={`Remove ${doc.filename} from scope`}
                className="opacity-50 hover:opacity-100"
              >
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
