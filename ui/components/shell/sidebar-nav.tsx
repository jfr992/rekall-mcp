"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brain, BookOpen, Clock, Sparkles } from "lucide-react";

const navItems = [
  { href: "/brain", label: "Brain", icon: Brain },
  { href: "/kb", label: "Knowledge", icon: BookOpen },
  { href: "/continuity", label: "Continuity", icon: Clock },
  { href: "/hygiene", label: "Hygiene", icon: Sparkles },
] as const;

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Primary" className="flex flex-col gap-1">
      {navItems.map((item) => {
        const active = pathname?.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors duration-[150ms] ${
              active
                ? "bg-[var(--surface-1)] text-[var(--fg)] shadow-[inset_2px_0_0_var(--accent-primary)]"
                : "text-[var(--fg-muted)] hover:bg-[var(--surface-0)] hover:text-[var(--fg)]"
            }`}
          >
            <Icon size={16} />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

/** Compact icon-only nav row for mobile top bar. */
export function MobileNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Primary" className="flex gap-1">
      {navItems.map((item) => {
        const active = pathname?.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-label={item.label}
            className={`flex h-10 w-10 items-center justify-center rounded-md transition-colors duration-[150ms] ${
              active
                ? "bg-[var(--surface-1)] text-[var(--fg)]"
                : "text-[var(--fg-muted)] hover:bg-[var(--surface-0)] hover:text-[var(--fg)]"
            }`}
          >
            <Icon size={20} />
          </Link>
        );
      })}
    </nav>
  );
}
