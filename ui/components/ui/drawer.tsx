"use client";

import {
  useEffect,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

const FOCUSABLE_SEL = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex=\"-1\"])",
  "details > summary",
].join(",");

type Props = {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  initialFocusRef?: RefObject<HTMLElement | null>;
};

export function Drawer({
  open,
  onClose,
  title,
  children,
  ariaLabel,
  ariaLabelledBy,
  initialFocusRef,
}: Props) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<Element | null>(null);

  // Capture trigger on open; restore focus on close
  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement;
    } else {
      if (triggerRef.current) {
        (triggerRef.current as HTMLElement).focus?.();
        triggerRef.current = null;
      }
    }
  }, [open]);

  // Initial focus + focus trap + Escape
  useEffect(() => {
    if (!open) return;

    const el = initialFocusRef?.current ?? closeBtnRef.current;
    el?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;

      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SEL),
      ).filter((n) => n.tabIndex >= 0);
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, initialFocusRef]);

  // Scroll lock
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            role="presentation"
            onClick={onClose}
            className="fixed inset-0 bg-[var(--scrim)]"
            style={{ zIndex: "var(--z-drawer)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
          />
          <motion.aside
            ref={dialogRef as React.RefObject<HTMLElement>}
            role="dialog"
            aria-modal="true"
            aria-label={ariaLabel}
            aria-labelledby={ariaLabelledBy}
            className="fixed right-0 top-0 h-[100dvh] w-full overflow-y-auto border-l border-[var(--border)] bg-[var(--bg-frost)] p-6 pb-[calc(1.5rem+env(safe-area-inset-bottom))] backdrop-blur-[18px] backdrop-saturate-150 md:max-w-[480px]"
            style={{ zIndex: "var(--z-drawer)" }}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className="mb-4 flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">{title}</div>
              <button
                ref={closeBtnRef}
                onClick={onClose}
                aria-label="Close drawer"
                className="flex h-11 w-11 min-h-[44px] min-w-[44px] items-center justify-center rounded-md text-[var(--fg-muted)] hover:bg-[var(--surface-1)] hover:text-[var(--fg)]"
              >
                <X size={18} />
              </button>
            </div>
            {children}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
