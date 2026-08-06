"use client";

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api-client";
import { useToast } from "@/lib/toast-context";

export interface UploadTask {
  key: string;
  filename: string;
  progress: number;
  error?: string;
}

/** Shared by the Documents pane and the chat composer's attach button — both
 * upload through the same endpoint and both need the ["documents"] query
 * invalidated on success so the other surface picks up the new file. */
export function useDocumentUploads() {
  const queryClient = useQueryClient();
  const { push } = useToast();
  const [uploads, setUploads] = useState<UploadTask[]>([]);

  const handleFiles = useCallback(
    (files: File[]) => {
      for (const file of files) {
        const key = `${file.name}-${Date.now()}-${Math.random()}`;
        setUploads((prev) => [...prev, { key, filename: file.name, progress: 0 }]);

        api
          .uploadDocument(file, (pct) => {
            setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, progress: pct } : u)));
          })
          .then(() => {
            setUploads((prev) => prev.filter((u) => u.key !== key));
            queryClient.invalidateQueries({ queryKey: ["documents"] });
            push(`${file.name} uploaded — processing started`, "success");
          })
          .catch((err) => {
            const message = err instanceof Error ? err.message : "Upload failed";
            setUploads((prev) => prev.map((u) => (u.key === key ? { ...u, error: message } : u)));
            push(`${file.name}: ${message}`, "error");
            setTimeout(() => setUploads((prev) => prev.filter((u) => u.key !== key)), 4000);
          });
      }
    },
    [queryClient, push]
  );

  return { uploads, handleFiles };
}
