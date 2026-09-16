/**
 * Re-sincronização depois de um buraco no Realtime.
 *
 * CAUSA RAIZ que isto corrige:
 * `postgres_changes` não tem replay. Todo evento que acontece enquanto o socket
 * está fora é perdido para sempre — e o CRM aplica os eventos como patches sobre
 * o estado que já está na tela. Sem uma busca nova na volta, o buraco nunca
 * fecha: a lista/thread fica mentindo até alguém dar F5. Medido em produção
 * (16/09/2026): depois de 120s sem socket, a conversa que recebeu mensagem
 * durante a queda nunca subiu na lista, mesmo com o canal já reconectado.
 *
 * O callback de `channel.subscribe(...)` recebe `SUBSCRIBED` a cada entrada no
 * canal, inclusive nas re-entradas automáticas após queda (modelo Phoenix). É o
 * gancho certo para reconciliar.
 *
 * A PRIMEIRA inscrição é deliberadamente ignorada: ela acontece junto da busca
 * de montagem do próprio hook, então re-sincronizar ali só duplicaria o tráfego
 * de toda carga de página — exatamente o egress que o corte de 07/07 eliminou.
 * Da segunda em diante, houve queda e volta: aí sim há um buraco para fechar.
 */
export function onResubscribe(resync: () => void): (status: string) => void {
  let entradas = 0;
  return (status: string) => {
    if (status !== "SUBSCRIBED") return;
    entradas += 1;
    if (entradas > 1) resync();
  };
}
