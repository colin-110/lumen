"use client";

import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type ToastKind = "info" | "success" | "error";

interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastState {
  push: (message: string, kind?: ToastKind) => void;
}

const ToastContext = createContext<ToastState | null>(null);

let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((message: string, kind: ToastKind = "info") => {
    const id = ++counter;
    setToasts((prev) => [...prev, { id, kind, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const dismiss = (id: number) => setToasts((prev) => prev.filter((t) => t.id !== id));

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-[min(360px,calc(100vw-2rem))]">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`animate-fade-in-up flex items-start gap-2.5 rounded-xl border px-4 py-3 text-sm shadow-lg backdrop-blur ${
              t.kind === "error"
                ? "bg-danger-bg border-danger/30 text-danger"
                : t.kind === "success"
                ? "bg-success-bg border-success/30 text-success"
                : "bg-surface border-border text-foreground"
            }`}
          >
            {t.kind === "error" ? (
              <AlertCircle size={17} className="mt-0.5 shrink-0" />
            ) : t.kind === "success" ? (
              <CheckCircle2 size={17} className="mt-0.5 shrink-0" />
            ) : (
              <Info size={17} className="mt-0.5 shrink-0" />
            )}
            <p className="flex-1 leading-snug">{t.message}</p>
            <button
              onClick={() => dismiss(t.id)}
              className="opacity-60 hover:opacity-100 transition-opacity"
              aria-label="Dismiss"
            >
              <X size={15} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastState {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
