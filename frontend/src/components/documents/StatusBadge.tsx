import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";
import type { DocumentStatus } from "@/lib/types";

const CONFIG: Record<DocumentStatus, { label: string; className: string; icon: React.ElementType }> = {
  pending: { label: "Queued", className: "text-muted-foreground bg-surface-hover", icon: Clock },
  processing: { label: "Processing", className: "text-primary bg-accent", icon: Loader2 },
  completed: { label: "Ready", className: "text-success bg-success-bg", icon: CheckCircle2 },
  failed: { label: "Failed", className: "text-danger bg-danger-bg", icon: XCircle },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const cfg = CONFIG[status];
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${cfg.className}`}>
      <Icon size={12} className={status === "processing" ? "animate-spin" : ""} />
      {cfg.label}
    </span>
  );
}
