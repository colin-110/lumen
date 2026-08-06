"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, File, Trash2 } from "lucide-react";
import * as api from "@/lib/api-client";
import { useToast } from "@/lib/toast-context";
import { useDocumentUploads } from "@/lib/use-document-uploads";
import { UploadDropzone } from "./UploadDropzone";
import { StatusBadge } from "./StatusBadge";
import type { DocumentItem } from "@/lib/types";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentsView() {
  const queryClient = useQueryClient();
  const { push } = useToast();
  const { uploads, handleFiles } = useDocumentUploads();

  const { data: documents = [], isLoading } = useQuery({
    queryKey: ["documents"],
    queryFn: api.listDocuments,
    refetchInterval: (query) => {
      const docs = query.state.data as DocumentItem[] | undefined;
      const stillWorking = docs?.some((d) => d.status === "pending" || d.status === "processing");
      return stillWorking ? 2500 : false;
    },
  });

  const handleDelete = async (doc: DocumentItem) => {
    if (!confirm(`Delete "${doc.filename}"? This removes it from the knowledge base.`)) return;
    try {
      await api.deleteDocument(doc.id);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      push("Document deleted", "success");
    } catch {
      push("Could not delete document", "error");
    }
  };

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
        <div className="mb-7">
          <h1 className="text-2xl font-semibold tracking-tight brand-text">Document Repository</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Upload documents for Lumen to search and cite when answering questions.
          </p>
        </div>

        <UploadDropzone onFiles={handleFiles} />

        {uploads.length > 0 && (
          <div className="mt-4 space-y-2">
            {uploads.map((u) => (
              <div key={u.key} className="rounded-2xl border border-border bg-surface px-4 py-3.5 animate-fade-in-up">
                <div className="flex items-center justify-between text-sm">
                  <span className="truncate text-foreground">{u.filename}</span>
                  <span className="text-xs text-muted-foreground shrink-0 ml-2">
                    {u.error ? "Failed" : `${u.progress}%`}
                  </span>
                </div>
                <div className="mt-2 h-1.5 rounded-full bg-surface-hover overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${u.error ? "bg-danger" : "brand-mark"}`}
                    style={{ width: `${u.error ? 100 : u.progress}%` }}
                  />
                </div>
                {u.error && <p className="mt-1 text-xs text-danger">{u.error}</p>}
              </div>
            ))}
          </div>
        )}

        <div className="mt-8">
          <h2 className="text-sm font-semibold text-foreground mb-3">
            Your documents {documents.length > 0 && `(${documents.length})`}
          </h2>

          {isLoading ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-16 rounded-2xl animate-shimmer" />
              ))}
            </div>
          ) : documents.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
              No documents yet. Upload one above to get started.
            </div>
          ) : (
            <div className="space-y-2">
              {documents.map((doc) => (
                <div
                  key={doc.id}
                  className="flex items-center gap-3 rounded-2xl border border-border bg-surface px-4 py-3.5 hover:shadow-sm hover:border-border-strong transition-all animate-fade-in-up"
                >
                  <div className="w-9 h-9 rounded-xl bg-accent text-accent-foreground flex items-center justify-center shrink-0">
                    <File size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">{doc.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatBytes(doc.file_size)}
                      {doc.status === "completed" && ` · ${doc.chunk_count} chunks indexed`}
                    </p>
                    {doc.status === "failed" && doc.error_message && (
                      <p className="mt-1 flex items-center gap-1 text-xs text-danger">
                        <AlertTriangle size={11} />
                        {doc.error_message}
                      </p>
                    )}
                  </div>
                  <StatusBadge status={doc.status} />
                  <button
                    onClick={() => handleDelete(doc)}
                    className="p-2 rounded-lg text-muted-foreground hover:bg-danger-bg hover:text-danger transition-colors shrink-0"
                    aria-label={`Delete ${doc.filename}`}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
