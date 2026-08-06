"use client";

import {
  AlertTriangle,
  ArrowDown,
  ChevronDown,
  ChevronRight,
  CornerDownRight,
  Database,
  Minus,
  Play,
  Sparkles,
  Terminal,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useState } from "react";
import * as api from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type { DebugChunk, DebugStage, RetrievalDebug } from "@/lib/types";

const EXAMPLES = [
  "What port does the VPN listen on?",
  "How long did the checkout outage last?",
  "What is the reimbursement limit for meals?",
];

export function RetrievalDebugger() {
  const { user } = useAuth();
  const [query, setQuery] = useState("");
  const [generateAnswer, setGenerateAnswer] = useState(false);
  const [result, setResult] = useState<RetrievalDebug | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (text?: string) => {
    const q = (text ?? query).trim();
    if (!q || loading) return;
    setQuery(q);
    setLoading(true);
    setError(null);
    try {
      setResult(await api.debugRetrieval(q, { generateAnswer }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Trace failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  if (user && !user.is_superuser) {
    return (
      <div className="h-full overflow-y-auto scrollbar-thin">
        <div className="mx-auto max-w-2xl px-4 py-16 text-center">
          <div className="w-12 h-12 rounded-2xl bg-danger-bg text-danger flex items-center justify-center mx-auto">
            <AlertTriangle size={22} />
          </div>
          <h1 className="mt-4 text-xl font-semibold">Superuser only</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            The retrieval debugger exposes the system prompt and raw indexed chunks, so it&apos;s
            restricted to superuser accounts.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
        <header className="mb-7">
          <div className="flex items-center gap-2.5">
            <div className="brand-mark w-9 h-9 rounded-xl text-white flex items-center justify-center shadow-sm">
              <Terminal size={17} />
            </div>
            <h1 className="text-2xl font-semibold tracking-tight brand-text">Retrieval Debugger</h1>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            Traces one question through every stage of the RAG pipeline — rewrite, cache probe, dense and
            sparse search, fusion, reranking, and the exact prompt the model receives.
          </p>
        </header>

        <div className="rounded-2xl border border-border bg-surface p-4">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                run();
              }
            }}
            rows={2}
            placeholder="Ask something your documents should answer…"
            className="w-full resize-none bg-transparent text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground"
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
            <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={generateAnswer}
                onChange={(e) => setGenerateAnswer(e.target.checked)}
                className="rounded border-border-strong accent-[var(--primary,#6366f1)]"
              />
              Also generate the answer
              <span className="rounded-full bg-surface-hover px-1.5 py-0.5 text-[10px]">costs 1 LLM call</span>
            </label>
            <button
              onClick={() => run()}
              disabled={loading || !query.trim()}
              className={`inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-medium transition-all ${
                loading || !query.trim()
                  ? "bg-surface-hover text-muted-foreground"
                  : "brand-mark text-white hover:brightness-110 active:scale-95"
              }`}
            >
              <Play size={14} />
              {loading ? "Tracing…" : "Trace"}
            </button>
          </div>
        </div>

        {!result && !loading && (
          <div className="mt-4 flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => run(ex)}
                className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-muted-foreground hover:border-primary/40 hover:text-foreground transition-colors"
              >
                {ex}
              </button>
            ))}
          </div>
        )}

        {error && (
          <div className="mt-4 flex items-start gap-2 rounded-2xl border border-danger/30 bg-danger-bg px-4 py-3 text-sm text-danger">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            {error}
          </div>
        )}

        {loading && (
          <div className="mt-6 space-y-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-24 rounded-2xl animate-shimmer" />
            ))}
          </div>
        )}

        {result && !loading && <Trace result={result} />}
      </div>
    </div>
  );
}

function Trace({ result }: { result: RetrievalDebug }) {
  const dropped = droppedBetween(result);

  return (
    <div className="mt-6 space-y-3 animate-fade-in-up">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="rounded-full bg-surface-hover px-2.5 py-1">
          total <span className="font-semibold text-foreground">{result.total_ms.toFixed(0)}ms</span>
        </span>
        {result.stages.map((s) => (
          <span key={s.key} className="rounded-full bg-surface-hover px-2.5 py-1">
            {s.label.split(" ")[0].toLowerCase()} {s.duration_ms.toFixed(0)}ms
          </span>
        ))}
      </div>

      <StepCard icon={<CornerDownRight size={15} />} title="1 · Query rewrite">
        {result.rewrite_applied ? (
          <>
            <Field label="Asked">{result.question}</Field>
            <Field label="Rewritten for search">{result.rewritten_query}</Field>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            Not applied — the question is already standalone (rewriting only runs with conversation
            history to resolve against).
          </p>
        )}
      </StepCard>

      <StepCard icon={<Zap size={15} />} title="2 · Semantic cache probe">
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
              result.cache_hit ? "bg-success-bg text-success" : "bg-surface-hover text-muted-foreground"
            }`}
          >
            {result.cache_hit ? "HIT" : "MISS"}
          </span>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">{result.cache_note}</p>
      </StepCard>

      {result.stages.map((stage, i) => (
        <StageCard
          key={stage.key}
          index={i + 3}
          stage={stage}
          showsMovement={stage.key === "reranked" || stage.key === "selected"}
          dropped={stage.key === "selected" ? dropped : []}
        />
      ))}

      <StepCard icon={<Terminal size={15} />} title={`${result.stages.length + 3} · Final prompt`} collapsible>
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-surface-2 p-3 text-xs leading-relaxed text-foreground/90">
          {result.final_prompt}
        </pre>
      </StepCard>

      {result.answer !== null && (
        <StepCard icon={<Sparkles size={15} />} title={`${result.stages.length + 4} · Generated answer`}>
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{result.answer}</p>
        </StepCard>
      )}
    </div>
  );
}

/** Chunks the reranker kept but the production score-floor/top-k cut removed.
 * Surfacing these is the point of the last stage — it's where the pipeline
 * silently discards a candidate that looked fine two steps earlier. */
function droppedBetween(result: RetrievalDebug): DebugChunk[] {
  const reranked = result.stages.find((s) => s.key === "reranked");
  const selected = result.stages.find((s) => s.key === "selected");
  if (!reranked || !selected) return [];
  const kept = new Set(selected.chunks.map((c) => c.chunk_id));
  return reranked.chunks.filter((c) => !kept.has(c.chunk_id));
}

function StageCard({
  index,
  stage,
  showsMovement,
  dropped,
}: {
  index: number;
  stage: DebugStage;
  showsMovement: boolean;
  dropped: DebugChunk[];
}) {
  const icon = stage.key === "selected" ? <ArrowDown size={15} /> : <Database size={15} />;
  return (
    <StepCard
      icon={icon}
      title={`${index} · ${stage.label}`}
      meta={`${stage.duration_ms.toFixed(0)}ms · ${stage.chunks.length} chunk${stage.chunks.length === 1 ? "" : "s"}`}
    >
      <p className="mb-3 text-xs leading-relaxed text-muted-foreground">{stage.description}</p>
      {stage.chunks.length === 0 ? (
        <p className="text-sm text-muted-foreground">No chunks returned at this stage.</p>
      ) : (
        <div className="space-y-1.5">
          {stage.chunks.map((c) => (
            <ChunkRow key={c.chunk_id} chunk={c} showMovement={showsMovement} />
          ))}
        </div>
      )}
      {dropped.length > 0 && (
        <div className="mt-3 border-t border-border pt-3">
          <p className="mb-1.5 text-xs font-medium text-danger">
            Dropped here ({dropped.length}) — below the score floor or past the top-k cut
          </p>
          <div className="space-y-1.5 opacity-60">
            {dropped.map((c) => (
              <ChunkRow key={c.chunk_id} chunk={c} showMovement={false} dropped />
            ))}
          </div>
        </div>
      )}
    </StepCard>
  );
}

function ChunkRow({
  chunk,
  showMovement,
  dropped,
}: {
  chunk: DebugChunk;
  showMovement: boolean;
  dropped?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className={`rounded-xl border bg-surface-2 transition-colors ${
        dropped ? "border-danger/25" : "border-border"
      }`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left"
      >
        <span className="shrink-0 text-xs font-semibold text-muted-foreground w-6">#{chunk.rank}</span>
        <span className="flex-1 truncate text-sm">{chunk.filename}</span>
        {showMovement && <Movement chunk={chunk} />}
        <span className="shrink-0 font-mono text-xs text-muted-foreground">{chunk.score.toFixed(3)}</span>
        {open ? (
          <ChevronDown size={13} className="shrink-0 opacity-50" />
        ) : (
          <ChevronRight size={13} className="shrink-0 opacity-50" />
        )}
      </button>
      {open && (
        <p className="whitespace-pre-wrap border-t border-border px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
          {chunk.snippet}
        </p>
      )}
    </div>
  );
}

function Movement({ chunk }: { chunk: DebugChunk }) {
  if (chunk.previous_rank === null) {
    return (
      <span className="shrink-0 rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-medium text-accent-foreground">
        new
      </span>
    );
  }
  const delta = chunk.previous_rank - chunk.rank;
  if (delta === 0) {
    return <Minus size={12} className="shrink-0 opacity-30" />;
  }
  const up = delta > 0;
  // The arrow is an icon, so the direction has to be stated for assistive tech —
  // otherwise this reads as a bare number with no meaning.
  const label = `moved ${up ? "up" : "down"} ${Math.abs(delta)} from rank ${chunk.previous_rank}`;
  return (
    <span
      className={`shrink-0 inline-flex items-center gap-0.5 text-[10px] font-medium ${
        up ? "text-success" : "text-danger"
      }`}
      title={label}
      aria-label={label}
    >
      {up ? <TrendingUp size={11} aria-hidden /> : <TrendingDown size={11} aria-hidden />}
      {Math.abs(delta)}
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2 last:mb-0">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm">{children}</p>
    </div>
  );
}

function StepCard({
  icon,
  title,
  meta,
  children,
  collapsible,
}: {
  icon: React.ReactNode;
  title: string;
  meta?: string;
  children: React.ReactNode;
  collapsible?: boolean;
}) {
  const [open, setOpen] = useState(!collapsible);
  return (
    <section className="rounded-2xl border border-border bg-surface">
      <div
        className={`flex items-center gap-2.5 px-4 py-3 ${collapsible ? "cursor-pointer" : ""}`}
        onClick={collapsible ? () => setOpen(!open) : undefined}
      >
        <span className="w-7 h-7 shrink-0 rounded-lg bg-accent text-accent-foreground flex items-center justify-center">
          {icon}
        </span>
        <h2 className="flex-1 text-sm font-semibold">{title}</h2>
        {meta && <span className="text-xs text-muted-foreground">{meta}</span>}
        {collapsible &&
          (open ? (
            <ChevronDown size={14} className="opacity-50" />
          ) : (
            <ChevronRight size={14} className="opacity-50" />
          ))}
      </div>
      {open && <div className="border-t border-border px-4 py-3.5">{children}</div>}
    </section>
  );
}
