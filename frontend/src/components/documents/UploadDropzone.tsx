"use client";

import { UploadCloud } from "lucide-react";
import { useCallback, useRef, useState } from "react";

interface UploadDropzoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

const ACCEPT = ".pdf,.docx,.txt,.md,.csv";

export function UploadDropzone({ onFiles, disabled }: UploadDropzoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (disabled) return;
      const files = Array.from(e.dataTransfer.files);
      if (files.length) onFiles(files);
    },
    [onFiles, disabled]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
      className={`flex flex-col items-center justify-center gap-3 rounded-3xl border-2 border-dashed px-6 py-14 text-center transition-all cursor-pointer ${
        dragging ? "border-primary bg-accent/60 scale-[1.01]" : "border-border bg-surface hover:bg-surface-hover hover:border-border-strong"
      } ${disabled ? "opacity-60 cursor-not-allowed" : ""}`}
    >
      <div className="brand-mark w-12 h-12 rounded-2xl text-white flex items-center justify-center shadow-sm">
        <UploadCloud size={22} />
      </div>
      <p className="text-sm font-medium text-foreground">
        <span className="brand-text font-semibold">Click to upload</span> or drag and drop
      </p>
      <p className="text-xs text-muted-foreground">PDF, DOCX, TXT, MD or CSV — up to 50MB</p>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        disabled={disabled}
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
