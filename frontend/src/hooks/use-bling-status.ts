"use client";

import { useState, useEffect } from "react";
import {
  interpretarStatus,
  type ContaBling,
  type BlingStatusPayload,
} from "@/lib/bling-accounts";

/**
 * Estado da integracao Bling, lido de `/api/bling/status`.
 *
 * Cache em memoria compartilhado entre chamadores: os quatro pontos que abrem o
 * modal de venda montam em telas diferentes, e sem isso cada abertura repetiria
 * a chamada. `enabled` fica `null` enquanto nao se sabe — quem decide o que
 * fazer com isso e `blingGate`, nao este hook.
 *
 * `accounts` e a lista de contas Bling (segunda conta / segundo CNPJ) exposta
 * pelo backend. Pode vir vazia — papel nao-admin (a rota Next omite `accounts`
 * nesse caso, ver `app/api/bling/status/route.ts`) ou backend sem nenhuma conta
 * configurada — e isso e proposital: `enabled` NUNCA depende de `accounts`
 * (ver `interpretarStatus` em `@/lib/bling-accounts`), exatamente para que a
 * ausencia de `accounts` nao derrube ninguem para o modo legado.
 */
export interface BlingStatusState {
  enabled: boolean | null;
  accounts: ContaBling[];
  loading: boolean;
  error: string | null;
}

let cache: { enabled: boolean; accounts: ContaBling[] } | null = null;
let inflight: Promise<{ enabled: boolean; accounts: ContaBling[] }> | null = null;

async function fetchStatus(): Promise<{ enabled: boolean; accounts: ContaBling[] }> {
  if (cache) return cache;
  if (!inflight) {
    inflight = fetch("/api/bling/status", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`status ${r.status}`);
        const body = (await r.json()) as BlingStatusPayload;
        // `enabled` e o toggle BLING_ENABLED; `connected` diz se a conta default
        // tem refresh_token. Modo Bling exige os dois: ligado mas sem OAuth so
        // produziria 401 na cara do vendedor no meio do registro. A traducao
        // completa (incluindo o fallback de `accounts` ausente) mora em
        // `interpretarStatus` para poder ser testada sem montar este hook.
        cache = interpretarStatus(body);
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
    cache
      ? { enabled: cache.enabled, accounts: cache.accounts, loading: false, error: null }
      : { enabled: null, accounts: [], loading: true, error: null }
  );

  useEffect(() => {
    if (cache) return;
    let vivo = true;
    fetchStatus()
      .then((s) => vivo && setState({ enabled: s.enabled, accounts: s.accounts, loading: false, error: null }))
      .catch((e) => vivo && setState({ enabled: null, accounts: [], loading: false, error: String(e) }));
    return () => {
      vivo = false;
    };
  }, []);

  return state;
}
