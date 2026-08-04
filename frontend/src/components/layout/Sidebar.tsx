"use client";

import Link from "next/link";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FileText,
  LogOut,
  MessageSquarePlus,
  MessagesSquare,
  Moon,
  Sparkles,
  Sun,
  Trash2,
} from "lucide-react";
import * as api from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { useTheme } from "@/lib/use-theme";
import { useToast } from "@/lib/toast-context";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeConversationId = pathname === "/" ? searchParams.get("c") : null;
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const { push } = useToast();
  const queryClient = useQueryClient();

  const { data: conversations = [] } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.listConversations,
  });

  const handleNewChat = () => {
    router.push("/");
    onNavigate?.();
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await api.deleteConversation(id);
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (activeConversationId === id) router.push("/");
      push("Conversation deleted", "success");
    } catch {
      push("Could not delete conversation", "error");
    }
  };

  return (
    <aside className="h-full w-72 flex flex-col bg-surface-2 border-r border-border">
      <div className="p-4 flex items-center gap-2.5">
        <div className="relative w-8 h-8 shrink-0">
          <div className="brand-mark absolute inset-0 rounded-[10px]" />
          <div className="absolute inset-0 flex items-center justify-center text-white">
            <Sparkles size={15} strokeWidth={2.25} />
          </div>
        </div>
        <span className="font-semibold text-[15px] tracking-tight truncate">Lumen</span>
      </div>

      <div className="px-3 pb-3 space-y-1.5">
        <button
          onClick={handleNewChat}
          className="w-full flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-sm font-medium bg-primary text-primary-foreground hover:bg-primary-hover active:scale-[0.99] transition-all shadow-sm"
        >
          <MessageSquarePlus size={16} />
          New chat
        </button>
        <Link
          href="/documents"
          onClick={onNavigate}
          className={`w-full flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-colors ${
            pathname === "/documents"
              ? "bg-accent text-accent-foreground"
              : "text-foreground hover:bg-surface-hover"
          }`}
        >
          <FileText size={16} />
          Documents
        </Link>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-2.5 pb-2">
        <p className="px-2.5 pt-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Recent
        </p>
        <div className="space-y-0.5">
          {conversations.length === 0 && (
            <p className="px-2.5 py-3 text-xs text-muted-foreground">No conversations yet.</p>
          )}
          {conversations.map((c) => {
            const active = activeConversationId === c.id;
            return (
              <Link
                key={c.id}
                href={`/?c=${c.id}`}
                onClick={onNavigate}
                className={`group flex items-center gap-2 rounded-xl px-2.5 py-2 text-sm transition-colors ${
                  active ? "bg-accent text-accent-foreground" : "text-foreground hover:bg-surface-hover"
                }`}
              >
                <MessagesSquare size={14} className="shrink-0 opacity-70" />
                <span className="flex-1 truncate">{c.title}</span>
                <button
                  onClick={(e) => handleDelete(c.id, e)}
                  className="opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity shrink-0"
                  aria-label="Delete conversation"
                >
                  <Trash2 size={13} />
                </button>
              </Link>
            );
          })}
        </div>
      </div>

      <div className="border-t border-border p-3 space-y-1">
        <button
          onClick={toggle}
          className="w-full flex items-center gap-2 rounded-xl px-2.5 py-2 text-sm text-foreground hover:bg-surface-hover transition-colors"
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          {theme === "dark" ? "Light mode" : "Dark mode"}
        </button>
        <div className="flex items-center gap-2 px-1 pt-1">
          <div className="brand-mark w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-semibold text-white shrink-0">
            {user?.email?.[0]?.toUpperCase() ?? "?"}
          </div>
          <span className="flex-1 truncate text-xs text-muted-foreground">{user?.email}</span>
          <button
            onClick={logout}
            className="p-1.5 rounded-lg hover:bg-surface-hover text-muted-foreground hover:text-danger transition-colors"
            aria-label="Log out"
            title="Log out"
          >
            <LogOut size={15} />
          </button>
        </div>
      </div>
    </aside>
  );
}
