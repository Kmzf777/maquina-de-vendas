# A esteira vive na etapa — plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.

**Spec:** `docs/superpowers/specs/2026-09-25-esteira-vive-na-etapa-design.md`
**Branch:** `feat/esteira-vive-na-etapa`, a partir de `origin/master` (`bf93b962`)

**Goal:** Mudança de etapa encerra a esteira; resposta do lead adia. Corrige os três
defeitos da spec §1 (toque para card já movido, resposta que mata em vez de adiar, e o
adiamento de 60 dias inalcançável).

---

## Disciplina

Disjunto **por arquivo**. Um agente só toca os arquivos da sua task.

**Proibido:** qualquer git que altere estado — checkout, restore, reset, stash, rebase,
merge, **add**, commit, push. O orquestrador commita.
**Suítes em PRIMEIRO PLANO**, aguardadas até o fim (backend ~8min). Não delegar.

| Lote | Task | Dono do arquivo | Paralelo |
|---|---|---|---|
| 1 | **G1** o que a RESPOSTA faz | `cadence_joao.py`, `service.py`, 2 testes | ✅ com G2 |
| 1 | **G2** o que a ETAPA faz | `scheduler.py`, 1 teste | ✅ com G1 |
| 2 | **G3** a tela conta isso | `api.py`, `followup-board.tsx`, 2 testes | — (depois de G1) |

```
backend:  cd backend && python -m pytest -q -p no:warnings
frontend: cd frontend && npx tsc --noEmit && npx vitest run
```

**Contrato G1 → G3:** G1 cria `cadence_joao.ADIAMENTO_RESPOSTA = timedelta(days=3)`.
G3 o expõe no payload da cadência como `adiamento_resposta_dias: int`. O número nunca é
escrito à mão no frontend — duplicar a fonte é o defeito que esta base já corrigiu duas
vezes este mês.

---

# LOTE 1 — paralelo

## Task G1: a resposta do lead adia, e deixa de ser ignorada

**Files:** `backend/app/follow_up/cadence_joao.py`,
`backend/app/follow_up/service.py`,
`backend/tests/test_cadence_joao_2026_09_18.py`,
`backend/tests/test_agendador_joao_2026_09_18.py`

**LEIA ANTES:** `processar_resposta_joao`, `_adiar_matriculas_joao`,
`_optout_da_cadencia_joao`, `cancel_followups_by_phone`, `_preserved_job_types` — nessa
ordem. E `cadence_joao.adiar_toques`, que é a função pura que os três ramos usam.

### 1. `ADIAMENTO_RESPOSTA`

Constante nova em `cadence_joao.py`, irmã de `ADIAMENTO_ESTOQUE`:
`ADIAMENTO_RESPOSTA = timedelta(days=3)`. Comentário explicando que é o adiamento da
resposta COMUM (a do botão continua 60 dias) e que o número é de código, não da tela.

### 2. O recorte do `client_replied` — a parte mais delicada do lote

`cancel_followups_by_phone` passa a preservar os `job_type` do João **SOMENTE quando
`reason == "client_replied"`**.

**Não transforme isso em "preserva sempre".** A mesma função é chamada com motivos
TERMINAIS — `handoff`, `sem_interesse_atual`, `cliente_ativo_sem_demanda`,
`lead_already_served`, e o caminho de blacklist/opt-out em `leads/service.py:1726`. Em
todos esses os jobs do João **devem continuar sendo cancelados**. Preservar sempre
reabriria o caso de 15/07 (cliente pediu ao humano para a IA parar, os toques seguiram)
que este backstop existe para cobrir.

`_preserved_job_types` hoje recebe só `preserve_scheduled_return: bool`. Estenda do jeito
que ficar mais legível (parâmetro a mais, ou a decisão em `cancel_followups_by_phone`),
mas o critério é o `reason`.

### 3. O terceiro ramo de `processar_resposta_joao`

Hoje a função sai cedo quando `classificar_resposta` não classifica. Esse `return None`
sai. Precedência final:

| Resposta | Ação |
|---|---|
| botão de saída | opt-out + blacklist + cancela (**intocado**) |
| "ainda tenho estoque" | adia 60 dias (**intocado, mas agora alcançável**) |
| qualquer outra | adia `ADIAMENTO_RESPOSTA` (**novo**) |

Reuse `_adiar_matriculas_joao` nos dois adiamentos — ela já preserva o espaçamento e já
arrasta o job de `mover_etapa` junto.

- [ ] **Teste da corrida (defeito C):** prove que depois de
      `cancel_followups_by_phone(reason="client_replied")` ainda existem jobs `pending`
      do João para `processar_resposta_joao` encontrar. Hoje seriam zero. É o teste que
      demonstra que o botão "ainda tenho estoque" voltou a existir.
- [ ] **Teste do recorte:** `client_replied` preserva o job do João e cancela o
      `standard` da ValerIA; `handoff` / `sem_interesse_atual` / opt-out cancelam o do
      João também. **Mutação obrigatória:** preservar em todos os motivos → exigir
      vermelho.
- [ ] **Teste de continuidade:** lead responde no toque 2 → toques 3 e 4 continuam
      existindo (mesma matrícula, não uma nova) e vencem 3 dias mais tarde.
- [ ] Procure testes existentes que afirmem "responder cancela tudo" e ajuste-os — eles
      codificam o comportamento antigo.

## Task G2: a guarda de etapa no envio

**Files:** `backend/app/follow_up/scheduler.py`,
`backend/tests/test_scheduler_joao_2026_09_18.py`

**LEIA ANTES:** `_process_joao_touch` inteiro, `_mover_card_joao` (de onde vem o padrão
do `etapa_vigiada`) e `automation/engine.py::_guard_broken` (a guarda equivalente do
motor de campanhas, que é o que estamos trazendo para cá).

**O caminho `standard` da ValerIA não pode mudar uma linha.** Rode a suíte dela antes e
depois e reporte os dois números.

Guarda nova no caminho do TOQUE — depois do ramo `mover_etapa`, antes de resolver
template e canal. A etapa vigiada vem de `cadence_joao.cadencia_do_funil(funil, cadencia)`,
**não** de `metadata.stage_id`: a config é a fonte, e duas fontes divergem no dia em que
alguém mudar o gatilho pela tela.

| Situação | Ação |
|---|---|
| card na etapa vigiada | envia |
| card em outra etapa | `_cancel_job(..., "card_mudou_de_etapa")` |
| deal não existe | `_cancel_job(..., "card_mudou_de_etapa")` |
| cadência não resolvida | não envia, `_mark_sent` (fail-closed, igual ao ramo do move) |
| `metadata.deal_id` ausente | `_cancel_job(..., "toque_sem_deal_para_verificar")` |
| erro de banco | **return sem marcar nada** — retry no próximo tick |

- [ ] O erro de banco é o ponto de atenção: `_guard_broken` é fail-OPEN, e aqui
      **não** copiamos isso. Lá o custo de errar é um toque a mais; aqui é mensagem de
      marketing para quem acabou de comprar. Adiar a decisão é melhor que os dois
      extremos. Deixe isso escrito no código.
- [ ] Reuse a leitura de etapa do `_mover_card_joao` se der (a `key` é procurada DENTRO
      do pipeline do deal — `key` só é única por pipeline).
- [ ] **Mutação obrigatória:** remover a guarda e exigir que o teste do card em
      "Fechado Ganho" fique vermelho.
- [ ] Teste também o caminho feliz: card ainda na etapa → envia, sem leitura extra
      atrapalhando.

---

# LOTE 2 (depois de G1 verificado)

## Task G3: a tela diz o que a resposta faz

**Files:** `backend/app/follow_up/api.py`,
`frontend/src/components/campaigns/followup-board.tsx`, os dois testes

**LEIA ANTES:** como `gatilho_silencio_dias` / `etapa_final_rotulo` / `dias_ate_mover`
foram expostos na entrega de 23/09 — este campo segue exatamente o mesmo caminho.

- [ ] `api.py`: o payload de cada cadência ganha `adiamento_resposta_dias: int`, vindo
      de `cadence_joao.ADIAMENTO_RESPOSTA.days`. **Só leitura** — o PUT não aceita.
- [ ] `followup-board.tsx`: o tipo ganha o campo, e o cabeçalho da cadência ganha uma
      frase dizendo o que a resposta do lead faz — algo como *"se o lead responder, os
      toques restantes esperam 3 dias"*. Vale para todas as cinco esteiras.
- [ ] **O número nunca é escrito à mão no frontend.** Ele vem do payload.
- [ ] Guarda defensiva: campo ausente/0 (backend antigo) → não renderiza a frase, em vez
      de escrever "esperam undefined dias".
- [ ] `tsc` + `vitest` verdes. NOTA DE AMBIENTE: se faltar `node_modules` no worktree,
      rode `npm ci` de verdade — **não** crie symlink para o `node_modules` do repo
      principal (o Turbopack recusa e o `next build` quebra).

---

# FECHAMENTO (orquestrador)

- [ ] `git fetch origin` e merge de `origin/master` (andou várias vezes esta semana).
- [ ] `git diff --diff-filter=D --name-only origin/master..HEAD` — vazio.
- [ ] Backend, `tsc`, `vitest`, `next build` verdes.
- [ ] Reproduzir os três defeitos da spec §1 com o código NOVO e mostrar que sumiram.
- [ ] Tudo continua nascendo desligado; nenhuma migration nesta entrega.
- [ ] **Não** pushar sem autorização.
