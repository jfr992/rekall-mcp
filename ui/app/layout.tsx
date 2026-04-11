import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Memento Brain UI',
  description: 'Dynamic memory cockpit for Memento MCP',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
