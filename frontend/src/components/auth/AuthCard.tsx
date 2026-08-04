import type { ReactNode } from "react";
import { Sparkles } from "lucide-react";

export function AuthCard({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="relative w-full max-w-sm">
      <div className="brand-glow -z-10" />
      <div className="mb-7 flex flex-col items-center text-center gap-3">
        <div className="brand-mark w-12 h-12 rounded-2xl flex items-center justify-center text-white shadow-lg">
          <Sparkles size={22} strokeWidth={2.25} />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        </div>
      </div>
      <div className="rounded-3xl border border-border bg-surface p-6 shadow-lg animate-scale-in">
        {children}
      </div>
      {footer && <div className="mt-5 text-center text-sm text-muted-foreground">{footer}</div>}
    </div>
  );
}

export function FormField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

export const inputClassName =
  "w-full rounded-xl border border-border bg-background px-3.5 py-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-ring/40 focus:border-ring transition-all disabled:opacity-60";

export const submitButtonClassName =
  "flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-medium text-white brand-mark hover:brightness-110 active:scale-[0.99] disabled:opacity-60 disabled:hover:brightness-100 transition-all shadow-sm";
