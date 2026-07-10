"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

/**
 * Provider LOCAL da página de conversas (P5 — adoção incremental do React Query).
 * Deliberadamente não montado no shell: o resto do app segue com fetch manual até
 * ser migrado página a página.
 *
 * refetchOnWindowFocus fica DESLIGADO: o payload de /api/conversations é pesado e
 * o corte de egress de 07/07 depende de não refazer a lista a cada foco de aba
 * (o realtime já mantém a lista viva via patches).
 */
export function ConversasQueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
