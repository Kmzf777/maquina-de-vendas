# Esteiras do João v2 — plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.

**Spec:** `docs/superpowers/specs/2026-09-23-esteiras-joao-v2-design.md`
**Branch:** `feat/esteiras-joao-v2`, a partir de `origin/master` (`b675bcaf`)

**Goal:** Três cadências por funil em Atacado e Private Label (Novo 3 toques, Em Conversa
4, Proposta Enviada 4 — nova), todos os toques sem template, com o card indo para "Em
Atenção" 24h depois do último toque, e a reentrada desbloqueada quando o lead responde.

---

## Disciplina

Disjunto **por arquivo**. Um agente só toca os arquivos da sua task.

**Proibido:** qualquer git que altere estado — checkout, restore, reset, stash, rebase,
merge, **add**, commit, push. O orquestrador commita.
**Suítes em PRIMEIRO PLANO**, aguardadas até o fim (backend ~8min). Não delegar.

**ORDEM:** o Lote 2 importa símbolos que o Lote 1 cria. O Lote 1 roda sozinho e é
verificado antes de abrir o Lote 2.

| Lote | Task | Dono do arquivo | Paralelo |
|---|---|---|---|
| 1 | **E1** cadências + migration | `cadence_joao.py`, migration, teste | — |
| 2 | **E2** agendador | `service.py`, teste | ✅ com E3, E4 |
| 2 | **E3** handler do move | `scheduler.py`, teste | ✅ com E2, E4 |
| 2 | **E4** API | `api.py`, teste | ✅ com E2, E3 |
| 3 | **E5** a tela | `followup-board.tsx`, teste | — |

```
backend:  cd backend && python -m pytest -q -p no:warnings
frontend: cd frontend && npx tsc --noEmit && npx vitest run
```

---

## O CONTRATO DO JOB DE MOVER — E2 e E3 dependem dele

Os dois agentes do Lote 2 implementam lados opostos disto **sem poder conversar**.
Siga ao pé da letra; divergir aqui produz um job que é criado e nunca executado.

O job criado por `service.py` e consumido por `scheduler.py`:

```python
{
  "job_type": cadencia.job_type,        # "joao_novo" | "joao_em_conversa" | "joao_proposta"
  "sequence": <sequence do último toque> + 1,
  "fire_at": <último toque + dias_ate_mover>,   # clampado na janela comercial
  "status": "pending",
  "metadata": {
      "acao": "mover_etapa",            # A MARCA. Ausente = job de toque normal.
      "etapa_final_key": "em_atencao",  # a key da etapa de destino
      "cadencia": <codigo>, "funil": <codigo do funil>,
      "matricula_id": <mesmo uuid dos toques da matrícula>,
      "deal_id": ..., "pipeline_id": ...,
      "template_name": None,            # explicitamente nulo
  },
}
```

Regra de leitura (E3): `metadata.get("acao") == "mover_etapa"` é a ÚNICA condição.
Nada de inferir pelo template nulo — job de toque sem template também existe.

---

# LOTE 1 (sozinho)

## Task E1: as três cadências e a migration

**Files:** `backend/app/follow_up/cadence_joao.py`,
`supabase/migrations/20260918_followup_joao_config.sql`,
`backend/tests/test_cadence_joao_2026_09_18.py` (adaptar, não recriar)

**LEIA ANTES:** o `cadence_joao.py` inteiro. Ele foi reescrito há dois dias para ser
funil-primeiro (`Funil{codigo, rotulo, pipeline_id, cadencias}`) — a forma atual é a
base, não a de antes.

- [ ] `Cadencia` ganha quatro campos, todos com default que preserva o comportamento
      das cadências de Reposição: `gatilho_silencio_dias: int = 0`,
      `etapa_final_key: str | None = None`, `etapa_final_rotulo: str | None = None`,
      `dias_ate_mover: int = 1`.
- [ ] `CadenciaResolvida` carrega os quatro (o agendador consome de lá).
- [ ] `novo`: 3 toques (dias 0, 2, 4), `gatilho_dias=2`, `gatilho_silencio_dias=2`.
- [ ] `em_conversa`: 4 toques (0, 2, 4, 9), `gatilho_dias=2`, `gatilho_silencio_dias=2`.
- [ ] `proposta` **(nova)**: 4 toques (0, 1, 4, 8), `gatilho_dias=1`,
      `gatilho_silencio_dias=0`, `gatilho_stage_key="proposta_enviada"`,
      `gatilho_stage_rotulo="Proposta Enviada"`, rótulo "Proposta Enviada".
- [ ] As TRÊS declaram `etapa_final_key="em_atencao"`,
      `etapa_final_rotulo="Em atenção"`, `dias_ate_mover=1`.
- [ ] **TODOS os toques das três cadências têm `template_name=None`** — inclusive os que
      hoje apontam para template aprovado. É decisão explícita do dono (spec §2), não
      esquecimento. Deixe um comentário dizendo isso, senão a próxima pessoa "conserta".
- [ ] `FUNIS`: Atacado e Private Label passam a ter 3 cadências cada. Os dois funis de
      Reposição e o de Recuperação **não mudam**.
- [ ] Migration: **antes de editar, confirme que ela nunca foi aplicada** — tente
      `SELECT count(*) FROM followup_joao_cadencia`. Se a tabela existir COM linhas,
      **pare e reporte**; editar no lugar deixaria de ser seguro. Esperado: a tabela não
      existe. Depois disso: `followup_joao_cadencia_par_valido` aceita `proposta` em
      atacado/private_label; `followup_joao_toque_dentro_da_cadencia` passa a `novo` 1-3,
      `em_conversa` 1-4, e ganha `proposta` 1-4. Reposição e em_atencao não mudam.
- [ ] Teste: os prazos de cada toque das três cadências nos dois funis (é o teste que
      protege os números da reunião); `toques_sem_template` devolve TODAS as sequences;
      as cadências de Reposição continuam com `gatilho_silencio_dias == 0` e
      `etapa_final_key is None`; texto do SQL cruzado contra `FUNIS` de verdade.
- [ ] Suíte verde no seu arquivo. Reporte quais outros testes quebraram (esperado — o
      Lote 2 herda).

---

# LOTE 2 — paralelo (só depois de E1 verificado)

## Task E2: agendador — silêncio, job de mover, cooldown por matrícula

**Files:** `backend/app/follow_up/service.py`,
`backend/tests/test_agendador_joao_2026_09_18.py`

**LEIA ANTES:** `_varrer_cadencia_joao`, `_montar_jobs_da_matricula`,
`motivo_para_pular_joao`, nessa ordem.

- [ ] `_varrer_cadencia_joao`: `p_silence_days` passa a vir de
      `cadencia.gatilho_silencio_dias` (hoje é fixo `0`). `p_last_speaker` continua
      `"qualquer"`. Não mexa em mais nenhum argumento da RPC.
- [ ] `_montar_jobs_da_matricula`: quando `etapa_final_key` está declarada **e**
      `repete_ultimo` é False, acrescenta o job de mover — exatamente no formato do
      CONTRATO no topo deste plano. Mesmo `matricula_id` dos toques.
- [ ] `motivo_para_pular_joao`: cooldown por MATRÍCULA (spec §4). Agrupe
      `jobs_do_card` por `metadata.matricula_id`; matrícula com algum job `cancelled` é
      INTERROMPIDA e não conta; matrícula sem nenhum cancelado conta, pela data de
      nascimento do job mais antigo dela. Job sem `matricula_id` = matrícula própria,
      conta (conservador). `JOAO_COOLDOWN_DIAS` continua 90.
- [ ] **Teste mais importante do lote:** lead responde no meio (jobs `cancelled` +
      alguns `sent` na mesma matrícula) → reentrada LIBERADA. Matrícula completa (todos
      `sent`) → `"cooldown"`. Mutação: volte a contar job `sent` de matrícula
      interrompida e exija vermelho.
- [ ] Teste: `p_silence_days` chega 2 em `novo`/`em_conversa`, 0 em `proposta` e nas de
      Reposição. E o job de mover é criado com `fire_at` = último toque + 1 dia, e NÃO
      é criado para `em_atencao` (que é `repete_ultimo`).

## Task E3: o handler que move o card

**Files:** `backend/app/follow_up/scheduler.py`,
`backend/tests/test_scheduler_joao_2026_09_18.py`

**LEIA ANTES:** `_process_joao_touch` inteiro, e
`backend/app/quotes/router.py::_move_deal_to_proposal` — este último é o padrão de
"mover card defensivamente" que já existe e que você vai espelhar.

**O caminho `standard` da ValerIA não pode mudar uma linha.**

- [ ] `JOAO_JOB_TYPES` ganha `"joao_proposta"`.
- [ ] `_process_joao_touch`: ramo NOVO no topo — `metadata.get("acao") == "mover_etapa"`
      → chama o move e retorna. Não resolve template, não resolve canal, não envia.
- [ ] `_mover_card_joao(deal_id, etapa_key)` nova, defensiva:
      só move se o card ainda estiver na etapa VIGIADA pela cadência (se já saiu, não
      desfaz o que o João fez à mão); etapa de destino inexistente no funil → registra e
      devolve False sem levantar; a `key` é procurada DENTRO do pipeline do próprio deal
      (a key se repete por funil — mesma armadilha citada em `_move_deal_to_proposal`).
- [ ] **Confirme com teste** (nada a implementar): `joao_proposta` já é isento de
      `ai_disabled` pelo prefixo `joao_` em `_stop_reason_applies` — não pela tabela
      `_STOP_REASON_EXEMPT_JOB_TYPES`. Se o teste falhar, PARE e reporte: significa que
      a cadência nova nasceria condenada, o bug do `handoff_rescue` de 27/07.
- [ ] Regressão: rode a suíte da ValerIA antes e depois, mesmo número.

## Task E4: a API expõe os campos novos

**Files:** `backend/app/follow_up/api.py`,
`backend/tests/test_api_definicao_joao_2026_09_18.py`

- [ ] O payload de cada cadência ganha `gatilho_silencio_dias`, `etapa_final_rotulo` e
      `dias_ate_mover` — **só leitura**, vindos do código. O PUT não os aceita; se o
      corpo trouxer, ignore em silêncio (não são campos de sobreposição).
- [ ] `proposta` entra sozinha no GET por ser mais uma cadência dentro do funil — mas
      confirme com teste que o funil Atacado devolve as TRÊS e que os de Reposição
      continuam com duas.
- [ ] A trava de ativação continua igual. Teste: ligar qualquer uma das três é
      RECUSADO hoje, nomeando todos os toques (todos estão sem template), e a recusa
      nomeia o toque certo.

---

# LOTE 3 (sozinho, depois do Lote 2)

## Task E5: a tela

**Files:** `frontend/src/components/campaigns/followup-board.tsx` + seu teste

**LEIA ANTES:** o componente inteiro. Isto NÃO é redesenho visual — é exibir três
campos a mais e uma terceira cadência que a tela já sabe renderizar sozinha.

- [ ] Os tipos ganham `gatilho_silencio_dias`, `etapa_final_rotulo`, `dias_ate_mover`.
- [ ] O cabeçalho da cadência diz o relógio completo e o destino, em português chão —
      algo como: *"Dispara com 2 dia(s) sem conversa na etapa Novo · depois do último
      toque, espera 1 dia e move o card para Em atenção"*. Quando
      `gatilho_silencio_dias` é 0, não invente a frase de silêncio (as de Reposição
      disparam por tempo de etapa). Quando `etapa_final_rotulo` é nulo, não invente a
      frase do move.
- [ ] Nada muda na navegação: Proposta Enviada aparece sozinha como terceira cadência.
- [ ] `tsc` + `vitest` verdes, cobrindo o funil com 3 cadências e as duas frases
      condicionais (com e sem silêncio; com e sem destino).

---

# FECHAMENTO (orquestrador)

- [ ] `git fetch origin` e merge de `origin/master` (andou 2× esta semana).
- [ ] `git diff --diff-filter=D --name-only origin/master..HEAD` — vazio.
- [ ] Backend, `tsc`, `vitest`, `next build` verdes.
- [ ] As três cadências nascem `ativa=False`; migration sem nenhum `INSERT`.
- [ ] Nenhuma das três pode ser ligada hoje (todos os toques sem template) — confirmar
      que a tela DIZ isso, em vez de só recusar em silêncio.
- [ ] **Não** pushar sem autorização.
