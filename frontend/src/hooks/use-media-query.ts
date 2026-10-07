"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * `true` enquanto a media query casa. No servidor (e no primeiro render da
 * hidratação) devolve `false`: o layout nasce no modo conservador e se ajusta
 * no cliente.
 */
export function useMediaQuery(query: string): boolean {
  const assinar = useCallback(
    (avisar: () => void) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener("change", avisar);
      return () => mql.removeEventListener("change", avisar);
    },
    [query],
  );
  return useSyncExternalStore(
    assinar,
    () => (typeof window !== "undefined" && !!window.matchMedia ? window.matchMedia(query).matches : false),
    () => false,
  );
}
