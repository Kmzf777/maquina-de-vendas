# Rehearsal Run Summary

**Started:** 2026-04-21T19:42:18.627066+00:00
**Finished:** 2026-04-21T20:10:11.831331+00:00

| Arquétipo | Status | Turnos | Terminated_by | Bot score | Veredito |
|---|---|---|---|---|---|
| A1 - cafeteria-atacado | failed | 3 | stage_reached | 4 | O agente foi repetitivo, demorou a responder perguntas diretas sobre preço e soou robótico ao enviar múltiplas mensagens curtas e duplicadas. |
| A2 - private-label | passed | 3 | encaminhar_humano | 3 | O agente demonstrou grave falta de memória e contexto, ignorando as solicitações do lead e pedindo repetidamente informações que já haviam sido fornecidas. |
| A3 - multi-intent | failed | 20 | max_turns | 3 | O agente falhou em atender à solicitação principal do lead por uma comparação direta de preços, gerando confusão com informações contraditórias e entrando em loops repetitivos. |
| A4 - objetor-preco | failed | 20 | max_turns | 2 | O agente não soube lidar com as objeções do lead, ficou preso em um loop repetitivo sobre o pedido mínimo e, no final, ignorou o encerramento da conversa pelo cliente para enviar uma lista de produtos irrelevante. |
| A5 - exportacao | passed | 2 | encaminhar_humano | 3 | O agente identificou o tema e encaminhou para um humano, mas falhou gravemente ao perguntar o país que já havia sido claramente informado no início da conversa. |