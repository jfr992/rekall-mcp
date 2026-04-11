import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Memento — Memory Cockpit",
  description: "Brain Observatory for the Memento MCP memory system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
