"use client";

import { useEffect, useRef } from "react";

/** True when the keyboard event originated in a text-entry element, so global shortcuts stay out of the way. */
export function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t.isContentEditable;
}

/**
 * Registers a document-level keydown handler. The handler is kept in a ref so callers
 * can pass an inline closure without re-binding the listener on every render.
 */
export function useKeydown(handler: (e: KeyboardEvent) => void, enabled = true) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!enabled) return;
    const fn = (e: KeyboardEvent) => ref.current(e);
    document.addEventListener("keydown", fn);
    return () => document.removeEventListener("keydown", fn);
  }, [enabled]);
}

/** Calls `onOutside` on a pointerdown outside the referenced element (or Escape). */
export function useDismiss<T extends HTMLElement>(open: boolean, onOutside: () => void) {
  const ref = useRef<T>(null);
  const cb = useRef(onOutside);
  cb.current = onOutside;
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) cb.current();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") cb.current();
    };
    document.addEventListener("pointerdown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  return ref;
}
