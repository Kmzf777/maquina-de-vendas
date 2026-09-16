"use client";

import { useEffect } from "react";
import { createClient } from "@/lib/supabase/client";

/**
 * Rede de segurança do socket do Realtime: se a conexão está de fato caída
 * (suspensão do SO, queda de Wi-Fi, aba longamente em segundo plano), pede para
 * voltar. Só isso.
 *
 * O QUE ESTE HOOK DEIXOU DE FAZER — e por quê (medido em produção, 16/09/2026):
 *
 * 1. NÃO chama mais `realtime.setAuth(token)` com token explícito.
 *    O supabase-js já entrega ao realtime um callback de token
 *    (`accessToken: this._getAccessToken`) e o renova a cada heartbeat. Passar
 *    um token à mão marca o cliente como "token manual" e DESLIGA essa
 *    renovação automática — o socket fica preso a um JWT que expira em 1h e o
 *    canal morre em silêncio. Evidência: uma aba aberta às 14:49 perdeu TODAS
 *    as inscrições entre 15:49:00 e 15:49:31, com o token expirando 15:49:06.
 *    A versão anterior deste hook (jun/2026) reintroduzia exatamente o bug que
 *    tinha sido escrito para consertar.
 *
 * 2. NÃO força mais `disconnect()` + `connect()` num socket saudável.
 *    Derrubar a conexão abre um buraco de ~1,3s, e `postgres_changes` não tem
 *    replay: todo evento nesse intervalo é perdido para sempre. Fazer isso a
 *    cada volta de aba era, por si só, uma fonte de mensagens sumidas.
 *
 * 3. NÃO duplica o tratamento de visibilidade da biblioteca.
 *    O @supabase/phoenix já escuta `visibilitychange`, `pagehide` e `pageshow`
 *    e reconecta sozinho. Aqui ficou só o reforço idempotente.
 *
 * Reconciliar os dados perdidos durante uma queda NÃO é trabalho deste hook:
 * isso é `onResubscribe` (@/lib/realtime-resync), ligado em cada hook que
 * assina realtime.
 *
 * Deve ser montado UMA vez, alto na árvore autenticada (AuthenticatedShell).
 */
export function useRealtimeKeepAlive() {
  useEffect(() => {
    const supabase = createClient();

    // Reconecta apenas o que está caído. Nunca derruba um socket vivo — é a
    // diferença entre fechar um buraco e abrir um novo.
    const reviveSeCaido = () => {
      if (supabase.realtime.isConnected()) return;
      supabase.realtime.connect();
    };

    window.addEventListener("online", reviveSeCaido);
    document.addEventListener("visibilitychange", reviveSeCaido);

    return () => {
      window.removeEventListener("online", reviveSeCaido);
      document.removeEventListener("visibilitychange", reviveSeCaido);
    };
  }, []);
}
