import type { Metadata } from "next";
import { Providers } from "@/components/providers";
import { CockpitShell } from "@/components/shell/cockpit-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Rekall — Memory Cockpit",
  description: "Brain Observatory for the Rekall MCP memory system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <Providers>
          <CockpitShell>{children}</CockpitShell>
        </Providers>
      </body>
    </html>
  );
}
