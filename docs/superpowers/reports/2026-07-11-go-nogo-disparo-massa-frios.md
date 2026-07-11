# GO/NO-GO — Disparo em massa Valéria Outbound (funil "Valeria - Importação Leads Frios")

**Data:** 11/07/2026 (sexta), ~19h BRT.
**Pergunta:** o projeto está pronto para um disparo em massa de HSM frio pela Valéria outbound, no regime **escalonado com canário (30–50 leads, seg 13/07 ou ter 14/07 de manhã → lotes de 200–500/dia)**?
**Método:** 100% read-only. (1) Transcritos integrais dos **26 respondentes reais dos disparos frios de 08–10/07** (292 mensagens) — evidência outbound pós-pacote-escuta-ativa que a auditoria geral de 11/07 não viu (a janela dela começava depois do último disparo); (2) mapa achado→fix da auditoria outbound de 08/07; (3) mapa do fluxo de disparo no código (arquivo:linha); (4) rehearsal runs; (5) consultas SQL em prod via Management API + GET de `quality_rating` na Meta.
**Decisões do usuário embutidas:** fila do João = bloqueador condicional; exclusões = conversa ativa/handoff, já recebeu disparo, cliente/ganho, número inválido (+ opt-out inegociável); template = `utilidade_22_04_2026_16_40`.

---

## VEREDITO: NO-GO hoje · GO CONDICIONAL para o canário de seg/ter (13–14/07)

O **software está pronto** — a Valéria outbound conversa bem e as guardas críticas funcionam em produção. O que bloqueia **não é a IA**: é (1) **não existe estoque para disparar** (líquido = **2 leads**), (2) a **fila humana já está transbordando** antes de qualquer disparo novo, e (3) três itens de higiene de 15 minutos cada. Resolvidas as 4 condições P0 abaixo, o canário está liberado do ponto de vista técnico.

### A pergunta central: "a Valéria outbound está otimizada para atender esses leads?"

**Sim — com evidência real, não simulada.** Ao contrário do que se supunha, houve 3 disparos frios pós-fixes (08, 09 e 10/07; lotes de 50). A leitura integral das 26 conversas resultantes mostra:

| Comportamento | Evidência nos transcritos 08–10/07 |
|---|---|
| ✅ Anti-carimbo / tom variado | Aberturas todas diferentes entre leads; zero repetição byte-a-byte (vs. 5 cópias idênticas em 08/07) |
| ✅ Escuta ativa / eventos de vida | Luciano ("fechei a cafeteria") → condolência adequada + `registrar_sem_interesse_atual` limpo |
| ✅ Cliente ativo detectado | Douglas Schutz ("João Reis me atende") → reconhecimento caloroso, sem pitch, mantido no funil |
| ✅ Número errado | Maria e João/Liax → `registrar_numero_errado` + pivô educado (job 72h→opt-out ativo) |
| ✅ Opt-out botão "Parar Mensagens" | Francine, Roberta, Flavio → `registrar_optout` **imediato, 3/3** |
| ✅ Autoresponder corporativo | RH Liax → sondagem única "consigo falar com o João?" (sem funil, sem handoff) |
| ✅ Cadência ressuscitada | Nudge D+1 12:00 + reopen HSM ao fechar janela, nos 4 leads mudos de 09/07; cancelamentos = `client_replied` (comportamento correto) |
| ✅ Qualificação B2B real | Café Julia (máquinas de café) → atacado, fotos, sondagem de volume; Wander → private label "Pitu Café" bem conduzido |
| ✅ Consumo → loja | Marisete e Tiago → cupom ESPECIAL10 + loja.cafecanastra.com, fechamento educado |

Os **15/15 achados da auditoria outbound de 08/07 estão corrigidos em master** (commits `d56d977`, `3d95648`, `54a734a`; 66 testes-âncora; deploy verde). Os fixes S1/S2 de hoje (`8d7d29f`) entraram em prod às 16:29 BRT.

**O padrão ruim que sobrou não é conversacional:** 6 dos 26 respondentes (23%) caíram em "IA temporariamente indisponível" (instabilidade LLM nas janelas de disparo de 08–09/07) e viraram **handoff cego** para o João — com "*Erro ao gerar resumo automático*" e rótulo "LEAD QUALIFICADO" para número errado (João/Liax), desinteressada (Stefani) e autoresponder (Letícia). Mitigação já em prod (T1/T2 parking: estaciona o turno + hold msg + drain, em vez de handoff imediato — deploy 10–11/07), **mas nunca observada sob disparo real** → é exatamente o que o canário valida.

---

## Os números que definem o dimensionamento

**Funil `a9487d77` (639 leads):** Frio 168 · Disparo feito 328 · Respondeu 89 · Qualificado 31 · Encerrado 23.

**Estoque disparável (aplicadas as exclusões acordadas): 2 leads.** Dos 168 do stage "Frio": 164 já receberam disparo, 166 estão com `ai_enabled=false`, 75 com `human_control=true` — o stage é um depósito de leftovers, não um pool virgem. **Sem novo CSV não há disparo em massa.**

**Histórico dos 11 lotes frios (467 alvos, 146 respostas):**

| Lote | Entregues | Responderam | % resp/entr. |
|---|---|---|---|
| 15/06 | 49 | 32 | 65% |
| 16/06 | 29 | 13 | 45% |
| 21/06 | 44 | 24 | 55% |
| 23/06 | 46 | 14 | 30% |
| 24/06 | 47 | 10 | 21% |
| 26/06 | 42 | 7 | 17% |
| 27/06 | 45 | 16 | 36% |
| 04/07 | 28 | 4 | 14% (billing outage) |
| 08/07 | 38 | 11 | 29% |
| 09/07 | 40 | 11 | 28% |
| 10/07 | 25 | 4 | 16% |

Tendência de queda = esgotamento da lista, não bloqueio Meta: das 30 "falhas" de 10/07, **19 eram a guarda de higiene** recusando lead quente (funcionando) e 6 `Message undeliverable` (números mortos — 12–24% nos lotes recentes). Nenhum erro de template/rating. **`quality_rating` GREEN nos 3 números** (Valéria/João/Arthur), throughput STANDARD, verificado hoje ao vivo.

**Template `utilidade_22_04_2026_16_40`:** approved, categoria UTILITY, registrado em **`en`** — todo broadcast DEVE usar `template_language_code='en'` (o disparo de 28/04 com `pt_BR` falhou 1/1; é a prova da armadilha de locale). 1 param posicional `{{1}}` = primeiro nome → **lista precisa de nome válido**: lead sem nome saiu como *"Falo com **querido** neste número?"* (caso real 10/07) e um lead com nome trocado recebeu "Falo com João" sendo Magda.

**Projeção por regime** (taxas recentes: ~85% entrega, ~25% resposta/entregue, ~20% dos respondentes → handoff, ~11% dos respondentes → opt-out):

| Regime | Entregues | Respostas | Handoffs p/ João | Opt-outs |
|---|---|---|---|---|
| Canário 50 | ~42 | ~9–12 | **2–4** | ~1 |
| 200/dia | ~170 | ~35–45 | **8–12/dia** | ~4 |
| 500/dia | ~425 | ~90–110 | **20–30/dia** | ~10 |

**Quota LLM:** hoje 357 chamadas/dia, US$2,54. Canário adiciona ~50–80 chamadas (irrelevante). 500/dia adicionaria ~300–500 chamadas — dentro do headroom do flash pago, com T1/T2 parking como rede. Custo não é gate; **estabilidade nas janelas de disparo é** (ver P0-2 e canário).

---

## Condições P0 — o que precisa acontecer ANTES do canário

1. **Importar lista nova (não existe o que disparar).** CSV com nome próprio válido e telefone BR normalizável; importar pelo modal (funil frio → stage "Frio") e montar o broadcast selecionando **só os recém-importados**. Não reaproveitar o stage Frio atual (164/168 já receberam disparo; o dedup automático NÃO protege — ver P1-1).
2. **Fila do João: zerar o backlog e declarar o plantão.** Agora: **34 conversas no vácuo** (mais antiga de ontem 21h) e **49 alertas `handoff_sla_breach` não resolvidos em 3 dias** — a detecção existe (Check 5, SLA 20min, janela 8–20h) mas nasce como `warning`, que **não vai ao WhatsApp do admin** (só Sentry/banner). Condição acordada: plantão nominal 8h–18h na seg/ter do canário. Recomendação forte (15 min de código, P1-2): elevar para `critical` ou escalonar quando acumular.
3. **Backfill do opt-out do Bruno** (`5511979689401`, lead `6c2539f3`): clicou "Parar Mensagens" em 27/06 (antes da tool existir), a Valéria prometeu "não te mando mais mensagem" e o `opt_out` segue `false` — ele é re-disparável hoje. Os outros 14 casos estão corretos; zero envio pós-opt-out no histórico.
4. **Checklist de configuração do broadcast** (o worker não impõe nada disso):
   - `agent_profile` = Valéria Outbound (é o que liga a guarda de lead quente e a persona sticky `valeria_outbound`);
   - `template_language_code='en'`;
   - `scheduled_at` para 9h–11h BRT (o worker **não tem clamp de horário comercial** — broadcast `running` dispara até de madrugada);
   - lote ≤50; `move_to_stage` = "Disparo feito".

## P1 — antes de escalar para 200–500/dia (mudanças de código, com autorização)

1. **Furo confirmado no dedup de template** (`broadcast/worker.py:1020`): filtra `status='sent'`, mas o webhook promove para `delivered/read` → lead com entrega confirmada **escapa do dedup de 14 dias**. Enquanto não corrigir, a exclusão "já recebeu" é responsabilidade da montagem da lista.
2. **`handoff_sla_breach` → `critical`/escalonamento** (hoje warning = invisível no WhatsApp).
3. **Clamp de janela comercial + cap diário de envio no worker** (hoje só sleep 3–8s/lead e 10/tick; broadcasts múltiplos somam).
4. **Circuit-breaker por taxa de falha do lote** (pausar se undeliverable >30%, análogo ao de template 132xxx) e reagir a `quality_rating≠GREEN` (hoje é só log no health check horário).
5. **Handoff de indisponibilidade não deve rotular "LEAD QUALIFICADO"** com resumo quebrado; suprimir para número-errado (autoresponder já não vira handoff desde `d56d977`).
6. **Guardas de opt-out/blacklist são fail-open** em erro de DB (`leads/service.py:284-298`; `worker.py:397`) — aceitável em 50/dia, arriscado em 500/dia.
7. **Rehearsal gate**: 4 secrets + 1ª execução (`rehearsal.yml` pronto; **nenhum run outbound jamais ficou verde** e o arquétipo O3 opt-out **nunca foi ensaiado** — hoje o botão funciona em prod, mas sem gate de regressão).
8. **Cadência/reopen não distinguem wrong_number**: Maria (negou ser a dona do número) recebeu reopen D+1 "não consegui te responder a tempo…". Suprimir touches para leads com `wrong_number_at`.

## P2 — observar no canário

- **Reação-como-consentimento**: o reaction-gate de 11/07 (`d56a081`) faz reação isolada não rodar a IA; no fluxo outbound "quer que eu te mostre fotos?" + 👍 (caso Wander) hoje ficaria **sem resposta** até o próximo texto. Vigiar no canário.
- Autoresponder "pessoal" (Luciana, "✨ Oiee… logo estarei de volta") ainda passa pelo gate (score<2) e consumiu nudge+reopen.
- Corrida texto×fotos (S4) viva no outbound (Café Julia: "enviei as fotos" segundos antes de `enviar_fotos` completar).
- Broadcast zumbi "Disparo teste kelwin" `running` desde 25/05 (limpar) e saneamento dos 166 `ai_enabled=false`/75 `human_control=true` do stage Frio.
- Categoria UTILITY com corpo de prospecção: aprovado e GREEN hoje, mas re-blast em escala aumenta o risco de reclassificação pela Meta — o histograma de opt-out por lote é o canário disso.

## Ressalvas

- O parking T1/T2 sob disparo real nunca foi observado (deploy posterior aos disparos auditados) — o canário é o teste.
- Os fixes S1/S2 de hoje (handoff duplicado / ponte engole pergunta) entraram às 16:29 BRT; zero handoffs outbound depois disso — validação fica para o canário.
- Sem rehearsal verde, a certificação outbound é 100% empírica (transcritos reais) — suficiente para canário de 50, não para 500/dia sem os P1.
