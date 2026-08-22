"use client";

import { useState, useEffect } from "react";

/**
 * Estado da integracao Bling, lido de `/api/bling/status`.
 *
 * Cache em memoria compartilhado entre chamadores: os quatro pontos que abrem o
 * modal de venda montam em telas diferentes, e sem isso cada abertura repetiria
 * a chamada. `enabled` fica `null` enquanto nao se sabe — quem decide o que
 * fazer com isso e `blingGate`, nao este hook.
 */
export interface BlingStatusState {
  enabled: boolean | null;
  loading: boolean;
  error: string | null;
}

let cache: { enabled: boolean } | null = null;
let inflight: Promise<{ enabled: boolean }> | null = null;

async function fetchStatus(): Promise<{ enabled: boolean }> {
  if (cache) return cache;
  if (!inflight) {
    inflight = fetch("/api/bling/status", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`status ${r.status}`);
        const body = (await r.json()) as { enabled?: boolean; connected?: boolean };
        // `enabled` e o toggle BLING_ENABLED; `connected` diz se ha refresh_token.
        // Modo Bling exige os dois: ligado mas sem OAuth so produziria 401 na cara
        // do vendedor no meio do registro.
        const ok = !!body.enabled && !!body.connected;
        cache = { enabled: ok };
        return cache;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function useBlingStatus(): BlingStatusState {
  const [state, setState] = useState<BlingStatusState>(
    cache ? { enabled: cache.enabled, loading: false, error: null }
          : { enabled: null, loading: true, error: null }
  );

  useEffect(() => {
    if (cache) return;
    let vivo = true;
    fetchStatus()
      .then((s) => vivo && setState({ enabled: s.enabled, loading: false, error: null }))
      .catch((e) => vivo && setState({ enabled: null, loading: false, error: String(e) }));
    return () => {
      vivo = false;
    };
  }, []);

  return state;
}
