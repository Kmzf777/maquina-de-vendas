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
    let vivo = true;
    if (cache === null) fetchEmail().then((e) => vivo && setEmail(e));

    // Invalida o cache quando a sessao muda. O app navega com router.push e
    // nunca recarrega o modulo (ver `handleSignOut` em sidebar.tsx), entao sem
    // isto um logout seguido de login com outra conta na MESMA aba deixaria o
    // e-mail antigo aqui — e a venda seguinte seria atribuida a pessoa errada,
    // em silencio. Cache velho em `use-bling-status` erra um estado de UI;
    // aqui erraria dado de negocio.
    const assinatura = import("@/lib/supabase/client").then(({ createClient }) =>
      createClient().auth.onAuthStateChange((_evento, session) => {
        cache = session?.user?.email ?? "";
        inflight = null;
        if (vivo) setEmail(cache);
      }),
    );

    return () => {
      vivo = false;
      assinatura.then(({ data }) => data.subscription.unsubscribe());
    };
  }, []);

  return email;
}
