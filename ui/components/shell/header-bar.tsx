"use client";

import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { MonoLabel } from "@/components/ui/mono-label";

const titles: Record<string, string> = {
  "/brain": "Neural Graph",
  "/kb": "Knowledge Base",
  "/continuity": "Continuity Console",
  "/hygiene": "Memory Hygiene",
};

export function HeaderBar() {
  const pathname = usePathname() ?? "";
  const title = Object.entries(titles).find(([k]) => pathname.startsWith(k))?.[1] ?? "Cockpit";
  const [now, setNow] = useState<string>("");
  const qc = useQueryClient();

  useEffect(() => {
    const tick = () => setNow(new Date().toLocaleTimeString());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="sticky top-0 flex h-14 items-center justify-between border-b border-[var(--border)] bg-[var(--bg-base)]/80 px-6 backdrop-blur-[12px]">
      <h1 className="font-serif text-xl">{title}</h1>
      <div className="flex items-center gap-3">
        <MonoLabel>now {now}</MonoLabel>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => qc.invalidateQueries()}
          aria-label="Refresh all data"
        >
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>
    </header>
  );
}
