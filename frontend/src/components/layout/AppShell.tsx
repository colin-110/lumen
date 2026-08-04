"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2, Menu } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { Sidebar } from "./Sidebar";

const PUBLIC_ROUTES = ["/login", "/register"];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading } = useAuth();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const isPublicRoute = PUBLIC_ROUTES.includes(pathname);

  // Close the mobile nav when the route changes. Adjusted during render
  // (React's documented pattern for "reset state when a prop changes")
  // rather than in an effect, so it takes effect in the same commit instead
  // of causing an extra render pass.
  const [prevPathname, setPrevPathname] = useState(pathname);
  if (pathname !== prevPathname) {
    setPrevPathname(pathname);
    setMobileNavOpen(false);
  }

  useEffect(() => {
    if (!loading && !user && !isPublicRoute) {
      router.replace("/login");
    }
    if (!loading && user && isPublicRoute) {
      router.replace("/");
    }
  }, [loading, user, isPublicRoute, router]);

  if (isPublicRoute) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4">{children}</div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-background gap-3">
        <div className="brand-mark w-10 h-10 rounded-2xl animate-pulse" />
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 size={15} className="animate-spin" />
          <span className="text-sm">Loading your workspace…</span>
        </div>
      </div>
    );
  }

  if (!user) {
    // Redirect effect above will kick in; render nothing in the meantime.
    return null;
  }

  return (
    <div className="h-screen flex overflow-hidden bg-background">
      {/* Mobile overlay */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <div
        className={`fixed z-40 inset-y-0 left-0 w-72 shrink-0 transform transition-transform md:static md:translate-x-0 ${
          mobileNavOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <Sidebar onNavigate={() => setMobileNavOpen(false)} />
      </div>

      <div className="flex-1 min-w-0 flex flex-col">
        <div className="md:hidden flex items-center gap-3 border-b border-border px-4 py-3 bg-surface">
          <button
            onClick={() => setMobileNavOpen(true)}
            className="p-1.5 rounded-lg hover:bg-surface-hover text-foreground"
            aria-label="Open menu"
          >
            <Menu size={20} />
          </button>
          <div className="brand-mark w-6 h-6 rounded-lg shrink-0" />
          <span className="font-semibold text-sm">Lumen</span>
        </div>
        <div className="flex-1 min-h-0">{children}</div>
      </div>
    </div>
  );
}
