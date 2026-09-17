# Motor de follow-up do João — plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.

**Spec:** `docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md`
**Branch:** `feat/motor-followup-joao`, a partir de `origin/master`

**Goal:** As três cadências do João rodando no scheduler que já existe, com dias e
templates editáveis na aba Follow-up, tudo **desligado** por padrão.

**Architecture:** Novos `job_type` em `follow_up_jobs`. Handler novo em
`follow_up/scheduler.py`; **nenhuma linha do caminho `standard` muda**. Definição
config-as-code em `follow_up/cadence_joao.py`, sobreposta por uma tabela editável.

---

## Disciplina

Disjunto **por arquivo**. Um agente só toca os arquivos da sua task.

**Proibido:** qualquer git que altere estado — checkout, restore, reset, stash, rebase,
merge, **add**, commit, push. O orquestrador commita.
**Suítes em PRIMEIRO PLANO**, aguardadas até o fim (backend ~7min). Não delegar.

| Lote | Task | Dono do arquivo | Paralelo |
|---|---|---|---|
| 0 | **J0** rollback e limpeza | `esteiras_joao.py`, `main.py`, SQL | — |
| 1 | **J1** cadência + tabela | `cadence_joao.py`, migration | ✅ com J2 |
| 1 | **J2** handler no scheduler | `scheduler.py` | ✅ com J1 |
| 2 | **J3** agendador | `service.py`, `automation/triggers.py` | ✅ com J4 |
| 2 | **J4** API de definição | `follow_up/api.py`, `router.py` | ✅ com J3 |
| 3 | **J5** a tela | `followup-board.tsx` + rotas Next | — |

```
backend:  cd backend && python -m pytest -q -p no:warnings
frontend: cd frontend && npx tsc --noEmit && npx vitest run
```

---

# LOTE 0

## Task J0: rollback do rumo e limpeza

**Files:** apagar `backend/app/campaigns/esteiras_joao.py` e
`backend/tests/test_esteiras_joao_seed.py` · modificar `backend/app/main.py` (ou onde o
seed é chamado no startup) · criar `scripts/apaga_esteiras_joao.sql`

- [ ] Achar **todos** os chamadores do seed antes de apagar (`grep -rn esteiras_joao`).
      Se aparecer consumidor não previsto, **parar e reportar**.
- [ ] Remover o seed e a chamada de startup. Só apagar as linhas do banco não basta: o
      seed as recria a cada start da API.
- [ ] SQL apagando as 6 campanhas `Esteira Joao —` por nome exato, com guarda de
      `status='draft'` e zero matrículas, em transação, com SELECT de conferência.
      **Não aplicar.**
- [ ] `esteiras.py` (as 4 genéricas) **fica**.
- [ ] Suíte verde. Reportar quantos testes morreram junto e por quê.

---

# LOTE 1 — paralelo

## Task J1: a cadência do João e a tabela de sobreposição

**Files:** criar `backend/app/follow_up/cadence_joao.py`,
`supabase/migrations/20260918_followup_joao_config.sql`,
`backend/tests/test_cadence_joao_2026_09_18.py`

Espelhe a forma de `follow_up/cadence.py` (leia-o): dataclass congelada + tupla de
toques. A diferença é que o `Touch` do João carrega **`template_name`**, não
`objective_prompt` — o lead está em silêncio, a janela está fechada, só template aprovado
sai.

- [ ] Quatro cadências, com os números da ata (spec §4): **novo** (1 toque, gatilho 2
      dias), **em_conversa** (7 toques em ~30 dias, gatilho 2 dias), **reposicao**
      (gatilho **45 dias**, toque e depois de 15 em 15), **em_atencao** (gatilho 90 dias,
      **1 toque a cada 3 dias**).
- [ ] Cada cadência declara os dois funis (Atacado / Private Label) e o template por
      linha — os 24 templates aprovados já existem
      (`scripts/create_templates_esteiras_joao.py`).
- [ ] Migration: tabela de sobreposição com `(cadencia, linha, toque) → dias,
      template_name`, mais `gatilho_dias` e `ativa` por cadência. **Nasce vazia**, e vazio
      = vale o código. Cabeçalho avisando que **não é aplicada pelo deploy**.
- [ ] Função pura `resolver_cadencia(codigo, linha, overrides) -> tuple[Touch,...]`, com
      teste: sem override vale o código; com override vale o banco; override parcial
      mistura na chave certa.
- [ ] Teste sobre o TEXTO do SQL (a suíte não tem banco), no padrão de
      `test_sql_cards_extraviados_2026_09_16.py`.

## Task J2: o handler no scheduler

**Files:** `backend/app/follow_up/scheduler.py` ·
`backend/tests/test_scheduler_joao_2026_09_18.py`

**LEIA ANTES:** `_process_lp_welcome`, `_process_ai_reengage` e `_process_handoff_rescue`
— são os três handlers autocontidos que você vai imitar. E `_stop_reason_applies`, que
**já varia as guardas por `job_type`**.

**O caminho `standard` da ValerIA é o único follow-up que funciona em produção (8.140
jobs). Nenhuma linha dele pode mudar.** Seu ponto de contato é só o despacho por
`job_type`.

- [ ] `_process_joao_touch(job, now)`: resolve a linha do funil pelo deal, monta os
      componentes do template (reusa `broadcast/worker.py::_build_template_components`),
      resolve o canal do vendedor, envia, marca. **Sem LLM.**
- [ ] Registrar os `job_type` novos no despacho de `process_due_followups` e em
      `_stop_reason_applies` (as mesmas paradas da ValerIA: blacklist, número errado,
      conversa finalizada).
- [ ] **Teste de regressão do caminho da ValerIA**: rode a cadência `standard` e compare
      o resultado antes e depois do ramo novo. É o teste mais importante desta task.
- [ ] Mutação: faça o handler do João cair no caminho `standard` e exija vermelho.

---

# LOTE 2 — paralelo

## Task J3: quem cria os jobs

**Files:** `backend/app/follow_up/service.py`,
`backend/app/automation/triggers.py` · `backend/tests/test_agendador_joao_2026_09_18.py`

- [ ] Varredura por cadência **ativa**, reusando a RPC `get_deals_stage_stagnant` que já
      existe e já tem as guardas (blacklist, número errado, conversa finalizada) — **não
      escreva consulta nova**.
- [ ] Cria os jobs da cadência com os offsets resolvidos. Idempotente: card que já tem
      job aberto daquela cadência **não** ganha outro.
- [ ] **Teto por passagem** (o "cards por vez"), para não disparar para a base inteira no
      primeiro tick. Medido em 16/09: 888 cards ficariam elegíveis no instante em que a
      cadência for ligada.
- [ ] Resposta do lead: botão "ainda tenho estoque" **adia 60 dias sem recomeçar**; botão
      de saída grava opt-out real. Reuse `campaigns/worker.py::is_optout_reply` e
      `handle_optout_reply` — **não reimplemente**.
- [ ] Cadência desligada não cria job nenhum. Teste dedicado.

## Task J4: a API da definição

**Files:** `backend/app/follow_up/api.py`, `backend/app/follow_up/router.py` ·
`backend/tests/test_api_definicao_joao_2026_09_18.py`

- [ ] `GET /api/cadence/definition` passa a devolver **as duas** definições (ValerIA e
      João), sem quebrar o consumidor atual (`followup-board.tsx` lê o formato de hoje —
      leia antes de mudar).
- [ ] `PUT` gravando a sobreposição: dias por toque, template por toque, prazo do gatilho,
      liga/desliga.
- [ ] **Ligar exige template aprovado em todo toque** — recusa nomeando o template e o
      status real (`PENDING`/`REJECTED`/ausente). Mesma trava que a aba Esteiras tinha, e
      que impede a cadência que inscreve, não envia, e caminha até o fim.
- [ ] Não deixa adicionar nem remover toque: o corpo só altera o que o spec §5 permite.

---

# LOTE 3

## Task J5: a tela

**Files:** `frontend/src/components/campaigns/followup-board.tsx` + rota Next de proxy se
precisar · testes

- [ ] `DefinitionStrip` vira editor, com seletor ValerIA / João.
- [ ] Por toque: dias e (no João) template, escolhido entre os **aprovados**.
- [ ] Prazo do gatilho e liga/desliga por cadência.
- [ ] A recusa de ligar **aparece**, listando os templates que faltam — não repita o erro
      de 16/09, em que a validação recusava e a tela não dizia nada.
- [ ] `tsc` + `vitest` verdes.

---

# FECHAMENTO (orquestrador)

- [ ] `git fetch origin` e **merge de `origin/master`** — ele andou 4× nesta semana.
- [ ] `git diff --diff-filter=D --name-only origin/master..HEAD`: só os arquivos da J0.
- [ ] Backend, `tsc`, `vitest`, `next build` verdes.
- [ ] Tudo nasce **desligado**; migration e SQL **não aplicados**.
- [ ] **Não** pushar sem autorização.
