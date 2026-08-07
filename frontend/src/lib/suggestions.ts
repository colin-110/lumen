import {
  ClipboardList,
  FileSearch,
  GitCompare,
  ListChecks,
  Sparkles,
  Upload,
  type LucideIcon,
} from "lucide-react";
import type { DocumentItem } from "./types";

export interface SuggestionPrompt {
  icon: LucideIcon;
  text: string;
}

/** Shown only when the user has no indexed documents yet. Anything referencing
 * document content would be a dead end at this point. */
export const EMPTY_STATE_PROMPTS: SuggestionPrompt[] = [
  { icon: Upload, text: "Upload a document to get started — use the paperclip below" },
];

/** Fallback for the composer's type-ahead, which needs *something* to match
 * against before documents load. Deliberately generic rather than inventing
 * specifics like a refund policy or a "Project Zeta" that no real corpus has. */
export const EXAMPLE_PROMPTS: SuggestionPrompt[] = [
  { icon: ListChecks, text: "Summarise the key points across my documents" },
  { icon: FileSearch, text: "What are the important dates and deadlines?" },
  { icon: ClipboardList, text: "What amounts or figures are mentioned?" },
  { icon: Sparkles, text: "What should I know that I probably haven't asked about?" },
];

/**
 * Turn a filename into something that reads inside a sentence.
 *
 * Separators become spaces, so "master_services_agreement.pdf" reads as
 * "master services agreement". The extension is only dropped when doing so
 * still leaves a recognisable phrase: stripping it from a single short word
 * ("ftier.txt" -> "ftier") produces gibberish, where keeping the filename
 * intact at least reads as a file reference.
 */
function readableName(filename: string): string {
  const base = filename.replace(/\.[^.]+$/, "");
  const spaced = base.replace(/[_-]+/g, " ").trim();
  if (!spaced) return filename;
  const looksLikeAPhrase = spaced.includes(" ") || spaced.length > 12;
  return looksLikeAPhrase ? spaced : filename;
}

/**
 * Build prompts from the documents the user actually has.
 *
 * The previous static list asked about a refund policy and a "Project Zeta"
 * that exist in nobody's corpus, so every suggestion returned nothing and the
 * app looked broken on first use. Naming real files makes the suggestions
 * answerable, and the comparison prompt surfaces multi-document reasoning,
 * which is otherwise easy to miss.
 */
export function suggestionsForDocuments(documents: DocumentItem[]): SuggestionPrompt[] {
  const ready = documents.filter((d) => d.status === "completed");
  if (ready.length === 0) return EMPTY_STATE_PROMPTS;

  // Most recent first — that's what the user was just working on.
  const recent = [...ready].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const [first, second] = recent;

  const prompts: SuggestionPrompt[] = [
    { icon: ListChecks, text: `Summarise ${readableName(first.filename)}` },
    { icon: FileSearch, text: `What are the key dates and figures in ${readableName(first.filename)}?` },
  ];

  if (second) {
    prompts.push({
      icon: GitCompare,
      text: `Compare ${readableName(first.filename)} and ${readableName(second.filename)} — do they agree?`,
    });
  }

  prompts.push({
    icon: Sparkles,
    text:
      ready.length > 2
        ? `What do my ${ready.length} documents have in common?`
        : "What should I know that I probably haven't asked about?",
  });

  return prompts;
}
