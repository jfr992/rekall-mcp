"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "sonner";

import { createQueryClient } from "@/lib/query-client";

export function Providers({ children }: { children: React.ReactNode }) {
  // Keep the client stable across re-renders within a single session.
  const [client] = useState(() => createQueryClient());

  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster
        position="bottom-right"
        theme="dark"
        toastOptions={{
          style: {
            background: "var(--bg-frost)",
            border: "1px solid var(--border)",
            color: "var(--fg)",
            backdropFilter: "blur(18px) saturate(1.2)",
          },
        }}
      />
    </QueryClientProvider>
  );
}
