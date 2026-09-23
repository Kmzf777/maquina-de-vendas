"use client";

import { useEffect, useState } from "react";
import type { LeadOrigin } from "@/lib/lead-origin";

/** Origem detalhada do lead (GET /api/leads/[id]/origin). `error` = fetch falhou. */
export function useLeadOrigin(leadId: string | null | undefined) {
  const [origin, setOrigin] = useState<LeadOrigin | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!leadId) {
      setOrigin(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(false);
    fetch(`/api/leads/${encodeURIComponent(leadId)}/origin`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((body: LeadOrigin) => {
        if (!cancelled) setOrigin(body);
      })
      .catch(() => {
        if (!cancelled) {
          setOrigin(null);
          setError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [leadId]);

  return { origin, loading, error };
}
