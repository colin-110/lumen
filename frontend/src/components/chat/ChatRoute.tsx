"use client";

import { useSearchParams } from "next/navigation";
import { ChatPanel } from "./ChatPanel";

export function ChatRoute() {
  const searchParams = useSearchParams();
  const conversationId = searchParams.get("c") ?? undefined;
  return <ChatPanel initialConversationId={conversationId} />;
}
