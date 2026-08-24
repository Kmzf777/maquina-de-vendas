"use client";

import { useState, useEffect } from "react";

/**
 * E-mail do usuario logado, com cache em memoria compartilhado.
 *
 * Existe porque quatro telas abrem o modal de venda e cada uma repetiria a
 * chamada de sessao. Ate 24/08/2026 so `contact-detail` buscava esse e-mail, e
 * as outras tres registravam venda sem vendedor — que, com o escopo por
 * vendedor ligado, faz a venda sumir da tela de quem acabou de registra-la.
 */
let cache: string | null = null;
let inflight: Promise<string> | null = null;

async function fetchEmail(): Promise<string> {
  if (cache !== null) return cache;
  if (!inflight) {
    inflight = import("@/lib/supabase/client")
      .then(({ createClient }) => createClient().auth.getSession())
      .then(({ data: { session } }) => {
        cache = session?.user?.email ?? "";
        return cache;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function useCurrentUserEmail(): string {
  const [email, setEmail] = useState<string>(cache ?? "");

  useEffect(() => {
    if (cache !== null) return;
    let vivo = true;
    fetchEmail().then((e) => vivo && setEmail(e));
    return () => {
      vivo = false;
    };
  }, []);

  return email;
}
