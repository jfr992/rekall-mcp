import type { Metadata } from "next";
import localFont from "next/font/local";
import { Providers } from "@/components/providers";
import { CockpitShell } from "@/components/shell/cockpit-shell";
import "./globals.css";

// ponytail: vendored latin subsets so builds need no network; add subsets here if non-latin text appears.
const newsreader = localFont({
  src: [
    { path: "./fonts/newsreader.woff2", weight: "200 800", style: "normal" },
    { path: "./fonts/newsreader-italic.woff2", weight: "200 800", style: "italic" },
  ],
  display: "swap",
  variable: "--font-serif",
});

const spaceGrotesk = localFont({
  src: "./fonts/space-grotesk.woff2",
  weight: "300 700",
  display: "swap",
  variable: "--font-sans",
});

const jetbrainsMono = localFont({
  src: "./fonts/jetbrains-mono.woff2",
  weight: "100 800",
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Rekall — Memory Cockpit",
  description: "Brain Observatory for the Rekall MCP memory system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`dark ${newsreader.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}
    >
      <body>
        <Providers>
          <CockpitShell>{children}</CockpitShell>
        </Providers>
      </body>
    </html>
  );
}
