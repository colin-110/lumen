import { ClipboardList, FileSearch, ListChecks, Sparkles, type LucideIcon } from "lucide-react";

export interface SuggestionPrompt {
  icon: LucideIcon;
  text: string;
}

export const EXAMPLE_PROMPTS: SuggestionPrompt[] = [
  { icon: ListChecks, text: "Summarize the key points across our uploaded documents" },
  { icon: ClipboardList, text: "What does our policy say about refunds?" },
  { icon: FileSearch, text: "Find any mentions of Project Zeta and its timeline" },
  { icon: Sparkles, text: "Draft a short FAQ based on the documents I've uploaded" },
];
