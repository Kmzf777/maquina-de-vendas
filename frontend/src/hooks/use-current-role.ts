"use client";

import { useState, useEffect } from "react";
import { createClient } from "@/lib/supabase/client";

/** Lê role e userId do usuário logado a partir da sessão (app_metadata.role). */
export function useCurrentRole() {
  const [state, setState] = useState<{
    role: "admin" | "vendedor";
    userId: string | null;
    loading: boolean;
  }>({ role: "vendedor", userId: null, loading: true });

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data: { session } }) => {
      const r = session?.user?.app_metadata?.role as "admin" | "vendedor" | undefined;
      setState({
        role: r === "admin" ? "admin" : "vendedor",
        userId: session?.user?.id ?? null,
        loading: false,
      });
    });
  }, []);

  return state;
}
