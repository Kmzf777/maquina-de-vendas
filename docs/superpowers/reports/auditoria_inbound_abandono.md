# Auditoria Comportamental — Drop-off/Ghosting em Conversas INBOUND (pós-deploy 904e764)

**Data:** 11/07/2026 (janela UTC: 2026-07-11T01:50 → 13:07, ~11h desde o deploy)
**Objetivo:** entender por que leads inbound estão silenciando no meio do atendimento.
**Método:** script temporário read-only (`backend/scripts/temp_audit_dropoffs.py`, removido após o uso). Drop-off operacional = última mensagem da conversa é da IA/handoff, lead com ≥1 mensagem na janela e silêncio > 45 min. Métricas por conversa: latência da IA, tamanho/nº de perguntas do turno final, presença de preço, CTA, `delivery_status`, horário BRT, pós-handoff. Leitura integral dos 7 transcritos (volume permitiu 100% de cobertura, não amostra).

## Volumetria

145 mensagens / 12 conversas inbound ativas (0 outbound na janela) / **7 drop-offs** (58% das conversas ativas).

## Hipóteses ELIMINADAS pelos dados (importante: onde NÃO está o problema)

| Hipótese | Evidência contrária |
|---|---|
| Demora na resposta da IA | Latência 3–43s (p50 17s) em todos os drop-offs |
| Mensagem não entregue (falha silenciosa) | `delivery_status` da última msg da IA: 4 read, 3 delivered — 100% chegou; 4 foram LIDAS e ignoradas |
| Excesso de texto | Turno final com 130–444 chars (p50 131) — bolhas curtas, dentro do padrão |
| Interrogatório / multi-pergunta | 0–1 pergunta por turno final em todos os casos |
| Tom robótico / carimbo | Sem repetição de clichê nos turnos finais; persona consistente |

## Causas REAIS, por categoria (7 casos classificados)

### Categoria 1 — Vácuo pós-handoff (4/7 casos, 57% — a causa dominante)

`café caseiro` (181min), `927ff3d5` (145min), `Charleston` (121min), `ALEMÃO AGROINDÚSTRIA` (68min). Nos 4 casos o "silêncio do lead" é na verdade **lead parado na sala de espera do humano**: a IA encaminhou, o cartão do João foi enviado entre 10:05 e 11:19 BRT de uma sexta-feira útil, e não há resposta humana por 1–3h. Dois leads ainda responderam "Ok, Deus abençoe 🙏" / "OK obrigado" e ficaram aguardando. É o mesmo padrão do Douglas na auditoria de ontem (3h sem resposta). **O gargalo não é a IA — é o SLA humano pós-handoff.** O watchdog `handoff_sla_breach` já cobre a detecção; o problema é operacional (cobertura/resposta do vendedor na manhã).

### Categoria 2 — Handoff que ENGOLE a última pergunta do lead (3/7 casos, subconjunto da Cat. 1)

O padrão comportamental mais acionável da varredura:

- `927ff3d5` 10:42: lead engajado ("gostei bastante dessa") pergunta **"Qual o pedido mínimo? E posso pegar em embalagens diferentes?"** → handoff imediato, pergunta jamais respondida (a IA sabia a resposta: 100 unidades).
- `ALEMÃO` 11:19: lead pede **"detalhes da empresa e PREÇOS"** → recebe o cartão do João, zero preços.
- `café caseiro` 10:04: lead pergunta o custo da personalização da logomarca → a IA responde **"opa, me embolei aqui por um instante / quer que eu siga com o próximo passo?"** (fallback de reengage visível disparou sobre uma pergunta respondível) → "Sim" → handoff. A pergunta original morreu.

Mecânica provável: o critério novo de qualificação (deploy de hoje) trata pergunta de preço/pedido como "sinal ativo de avanço" — correto — mas o modelo está **encaminhando em vez de responder-e-encaminhar**. O lead faz a pergunta mais quente da conversa e recebe um cartão de contato como resposta. Combinado com a Cat. 1 (João demora horas), o lead mais quente é exatamente o que fica mais tempo sem resposta.
**Recomendação (não implementada — rodada diagnóstica):** instruir que, quando o gatilho do handoff for uma pergunta factual respondível (preço/lote/prazo), a `mensagem_despedida` deve conter a resposta ANTES do transbordo. Uma linha na descrição da tool/prompt; sem guarda hard.

### Categoria 3 — Preço entregue sem CTA, na madrugada (1/7)

`Sandro` 23:11 BRT: recebeu preço (R$26,70/100un) + fotos e o turno final **não termina com pergunta** (único caso com preço e sem CTA). Silêncio de 11h — iniciado às 23h de quinta. Duplo fator: falta de condução pós-preço + horário. Mitigação já existente: o gatilho pós-preço da cadência (Frente B3) deve fazer o rescue — verificar se o follow-up dele foi agendado é o teste real do mecanismo.

### Categoria 4 — Horário natural / ciclo de decisão (1/7)

`Antonio Tofani`: interação à 1h da madrugada BRT, IA respondeu bem (com CTA), lead dormiu. Silêncio esperado; caso para a cadência D+1, não para mudança de comportamento.

### Categoria 5 — Curiosidade fria (1/7)

`60ea360a`: lead enviou apenas o prefill do anúncio, recebeu a abertura (com CTA) e nunca engajou. Custo de aquisição, não falha de atendimento. Sinal fraco a observar: a pergunta de abertura "você já tem uma marca **registrada**?" pode intimidar quem não tem registro — os 2 casos sem resposta à abertura receberam exatamente essa pergunta (amostra pequena demais para conclusão).

## Saúde das correções deployadas (sob o volume da janela)

| Verificação | Resultado |
|---|---|
| Mídia do vendedor vazia | **0 ocorrências** (nenhuma mídia de vendedor na janela ainda — mecanismo sem exercício real, monitorar) |
| Lead preso em `pending` | **0** — 7 transições de stage na janela, todas corretas |
| Flapping de stage | 0 |
| Handoff verbalizado sem tool-call | 1 ocorrência, contida pela guarda determinística (a métrica nova `handoffs_verbalizados` do QA diário vai capturá-la) |
| Alucinação/incoerência de preço | 0 (R$25,70/R$26,70/100un conferem com `products`) |

## Síntese executiva

O ghosting NÃO é causado por lentidão, texto longo, tom robótico ou falha de entrega — essas hipóteses morreram nos dados. **57% dos abandonos são leads esperando o humano depois do handoff**, e em 3 desses casos a IA agravou entregando o cartão **no lugar da resposta** à pergunta mais quente da conversa (preço/pedido mínimo). O 1 caso restante acionável é preço sem pergunta de fechamento na madrugada. Prioridade sugerida: (1) operacional — SLA de resposta do João na janela da manhã; (2) comportamental — "responda, depois encaminhe" na despedida do handoff; (3) verificar se o rescue pós-preço agendou follow-up para o caso Sandro.
