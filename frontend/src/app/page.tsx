import { Suspense } from "react";
import { ChatRoute } from "@/components/chat/ChatRoute";

export default function Home() {
  return (
    <Suspense fallback={null}>
      <ChatRoute />
    </Suspense>
  );
}
