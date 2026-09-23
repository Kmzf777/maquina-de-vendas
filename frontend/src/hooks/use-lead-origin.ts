"use client";

import { useEffect, useState } from "react";
import type { LeadOrigin } from "@/lib/lead-origin";

interface State {
  leadId: string | null;
  origin: LeadOrigin | null;
  error: boolean;
}

const IDLE: State = { leadId: null, origin: null, error: false };

/** Origem detalhada do lead (GET /api/leads/[id]/origin). `error` = fetch falhou. */
export function useLeadOrigin(leadId: string | null | undefined) {
  const [state, setState] = useState<State>(IDLE);

  useEffect(() => {
    if (!leadId) return;
    let cancelled = false;
    fetch(`/api/leads/${encodeURIComponent(leadId)}/origin`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((body: LeadOrigin) => {
        if (!cancelled) setState({ leadId, origin: body, error: false });
      })
      .catch(() => {
        if (!cancelled) setState({ leadId, origin: null, error: true });
      });
    return () => {
      cancelled = true;
    };
  }, [leadId]);

  const current = leadId != null && state.leadId === leadId;
  return {
    origin: current ? state.origin : null,
    error: current ? state.error : false,
    loading: !!leadId && state.leadId !== leadId,
  };
}
