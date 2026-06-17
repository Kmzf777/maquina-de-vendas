"use client";

import { useEffect } from "react";
import { createClient } from "@/lib/supabase/client";

/**
 * Mantém a conexão Supabase Realtime viva ao longo da sessão — elimina a
 * necessidade de dar F5 para voltar a receber mensagens em tempo real.
 *
 * CAUSA RAIZ que isto corrige:
 * O socket do Realtime autentica com o JWT do usuário no momento da conexão, e
 * esse token expira (~1h). Em abas em segundo plano o `autoRefreshToken` é
 * "throttled" pelo navegador (timers congelam) e o token expira sem renovar;
 * após suspensão do SO ou queda de Wi-Fi o socket cai. Sem re-autenticar e
 * reconectar, TODOS os canais postgres_changes (mensagens do chat aberto,
 * re-ordenação da lista, alerta sonoro de notificação) param de entregar em
 * silêncio. As chamadas REST continuam funcionando (o auth renova o token para
 * HTTP, e as rotas usam service role), por isso só o F5 — que cria um client
 * novo com token novo — ressuscitava o tempo real.
 *
 * Como o client do browser é singleton (@supabase/ssr), existe UM socket
 * compartilhado por toda a aplicação; revivê-lo aqui conserta todos os hooks de
 * realtime de uma só vez (chat, lista, notificações, presença, kanban, etc.).
 *
 * Deve ser montado UMA vez, alto na árvore autenticada (AuthenticatedShell).
 */
export function useRealtimeKeepAlive() {
  useEffect(() => {
    const supabase = createClient();
    let hiddenSince = 0;

    async function revive(force: boolean) {
      try {
        // getSession renova o token se estiver expirado (inclusive após o
        // throttle de aba em segundo plano), deixando o auth client com um JWT válido.
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token;
        if (!token) return; // sem sessão → nada a reconectar (logout/expiração total)

        // Empurra o token fresco para o socket e canais já vivos (re-autoriza).
        await supabase.realtime.setAuth(token);

        // Se o socket caiu (sleep/rede) ou ficou ocioso o bastante para o
        // servidor ter derrubado a sessão, força um ciclo limpo: os canais
        // re-entram automaticamente na reconexão (modelo Phoenix) com o token novo.
        const isOpen = supabase.realtime.connectionState() === "open";
        if (force || !isOpen) {
          await supabase.realtime.disconnect();
          supabase.realtime.connect();
        }
      } catch (err) {
        console.warn("[realtime-keepalive] falha ao reviver a conexão:", err);
      }
    }

    // Caminho normal (aba ativa): quando o auth renova o token, repassa ao socket.
    const { data: authSub } = supabase.auth.onAuthStateChange((event, session) => {
      if (session?.access_token && (event === "TOKEN_REFRESHED" || event === "SIGNED_IN")) {
        supabase.realtime.setAuth(session.access_token);
      }
    });

    // Aba volta ao foco: principal gatilho do bug (token expirou em background).
    // Força reconexão só se ficou oculta tempo suficiente para o socket/token
    // degradarem — evita churn em alt-tabs rápidos.
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        hiddenSince = Date.now();
        return;
      }
      const hiddenMs = hiddenSince ? Date.now() - hiddenSince : 0;
      hiddenSince = 0;
      revive(hiddenMs > 5_000);
    };

    // Rede voltou (sleep/queda de Wi-Fi): força reconexão.
    const onOnline = () => revive(true);

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onOnline);

    return () => {
      authSub.subscription.unsubscribe();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onOnline);
    };
  }, []);
}
