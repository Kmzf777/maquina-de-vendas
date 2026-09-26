# Esteira de Reposição + teto diário — plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: `superpowers:subagent-driven-development`.

**Spec:** `docs/superpowers/specs/2026-09-26-esteira-reposicao-design.md`
**Branch:** `feat/reposicao-esteira`, a partir de `origin/master` (`17b5586c`)

**Goal:** A esteira de Reposição move o card para "Já chamado" no 1º toque e para "Em
atenção" no fim, sem se matar no caminho; o botão "Preciso repor" encerra a esteira; e
existe um teto diário de disparos, editável na tela.

---

## Disciplina

Disjunto **por arquivo**. Um agente só toca os arquivos da sua task.

**Proibido:** qualquer git que altere estado — checkout, restore, reset, stash, rebase,
merge, **add**, commit, push. O orquestrador commita.
**Suítes em PRIMEIRO PLANO**, aguardadas até o fim (backend ~8min). Não delegar.

**ORDEM — há duas dependências reais de import:**
- Lote 2 importa símbolos novos de `cadence_joao.py` (Lote 1).
- Lote 3 importa os helpers de orçamento de `service.py` (Lote 2).

| Lote | Task | Dono do arquivo | Paralelo |
|---|---|---|---|
| 1 | **H1** definições + SQL | `cadence_joao.py`, 2 SQL, 1 teste | — |
| 2 | **H2** service | `service.py`, 1 teste | — |
| 3 | **H3** scheduler | `scheduler.py`, 1 teste | ✅ com H4 |
| 3 | **H4** API + tela | `api.py`, `followup-board.tsx`, 2 testes | ✅ com H3 |

```
backend:  cd backend && python -m pytest -q -p no:warnings
frontend: cd frontend && npx tsc --noEmit && npx vitest run
```

---

## CONTRATO H2 → H3 e H4 (o orçamento diário)

`service.py` expõe, e os outros dois consomem. Nomes exatos:

```python
AJUSTES_PADRAO = {"teto_diario_disparos": 100, "adiamento_estoque_dias": 30}

def carregar_ajustes_joao() -> dict[str, int]:
    """Lê followup_joao_ajustes. FAIL-CLOSED para AJUSTES_PADRAO."""

def disparos_de_hoje(sb) -> int:
    """Jobs do João com sent_at dentro do dia corrente em America/Sao_Paulo."""

def adiar_job_para_amanha(job_id: str, sb) -> None:
    """Empurra fire_at para o início da janela comercial de amanhã. NUNCA cancela."""
```

---

# LOTE 1 (sozinho)

## Task H1: as definições, a tabela de ajustes e o backfill

**Files:** `backend/app/follow_up/cadence_joao.py`,
`supabase/migrations/20260926_followup_joao_ajustes.sql` (novo),
`scripts/backfill_reposicao_ja_chamado.sql` (novo),
`backend/tests/test_cadence_joao_2026_09_18.py`

**LEIA ANTES:** o `cadence_joao.py` inteiro. Ele mudou 4 vezes em 8 dias — a forma atual
é a base.

- [ ] `Cadencia` e `CadenciaResolvida` ganham `etapas_vivas: tuple[str, ...] = ()`, com
      propriedade efetiva que cai em `(gatilho_stage_key,)` quando vazia. O default vazio
      é o que mantém as 4 cadências existentes com o comportamento de hoje.
- [ ] `Touch` ganha `move_para: str | None = None`.
- [ ] Reposição (nos DOIS funis): `etapas_vivas=("novo","chamado_reposicao")`; toque 1
      com `move_para="chamado_reposicao"`; `etapa_final_key="em_atencao"` (hoje é None).
      Prazos NÃO mudam: gatilho 45, toques 0/15/30/45.
- [ ] `ROTULOS_INTERESSE = frozenset({"preciso repor","quero a tabela","quero repor agora"})`
      e `RESPOSTA_INTERESSE = "interesse"`. `classificar_resposta` ganha o ramo, com
      precedência **saída → interesse → adiamento → None**. Igualdade normalizada, NUNCA
      substring (é a regra que impediu `"atacado" in "reposicao_atacado"` de voltar).
- [ ] **Teste que cruza `ROTULOS_INTERESSE` com os botões REAIS** dos templates de
      Reposição em `scripts/create_templates_esteiras_joao.py`, no mesmo espírito do teste
      de `aceita_adiamento`. Rótulo que não casa é botão morto — já aconteceu 2× aqui.
- [ ] `ADIAMENTO_ESTOQUE` passa de 60 para **30** dias (vira default; o banco sobrepõe).
- [ ] Migration NOVA `followup_joao_ajustes` (chave text PK, valor integer,
      atualizado_por, updated_at), CHECK nas duas chaves válidas e valor ≥ 1, RLS e
      trigger de `updated_at` no padrão de `20260918`. **Independente** da `20260918` —
      não referencia nem depende dela. Cabeçalho com o aviso de sempre: não é aplicada
      pelo deploy.
- [ ] `scripts/backfill_reposicao_ja_chamado.sql`: DUAS instruções em transação (spec §5)
      — a primeira move `stage_id` **e** a coluna legada `stage`; a segunda devolve
      `entered_stage_at` ao valor capturado (e NÃO toca em etapa, que é o que impede o
      trigger de zerar de novo). Escopo guardado: só Reposição Atacado, só
      `chamado_reposicao`, só 45+ dias. `SELECT` de conferência antes e depois.
      **Não aplicar.**
- [ ] Teste sobre o TEXTO dos dois SQL, no padrão já usado no arquivo.

---

# LOTE 2 (sozinho, depois de H1 verificado)

## Task H2: service — interesse, ajustes e o orçamento diário

**Files:** `backend/app/follow_up/service.py`,
`backend/tests/test_agendador_joao_2026_09_18.py`

**LEIA ANTES:** `processar_resposta_joao`, `_adiar_matriculas_joao`,
`carregar_overrides_joao`, `_varrer_cadencia_joao`, `agendar_cadencias_joao`.

- [ ] Os três helpers do CONTRATO acima. `carregar_ajustes_joao` é fail-closed para
      `AJUSTES_PADRAO`, com aviso uma vez por processo — mesma disciplina de
      `carregar_overrides_joao`.
- [ ] `processar_resposta_joao` ganha o ramo `RESPOSTA_INTERESSE`: cancela os `pending`
      da matrícula (toques restantes **e** o job de mover) com
      `cancel_reason="lead_demonstrou_interesse"`. Precedência: saída → interesse →
      adiamento → comum.
- [ ] O adiamento do botão passa a vir de `carregar_ajustes_joao()["adiamento_estoque_dias"]`
      em vez da constante fixa.
- [ ] `agendar_cadencias_joao` respeita o orçamento do dia: para de matricular quando o
      saldo acabou. O teto POR PASSAGEM (20) continua existindo — são coisas diferentes.
- [ ] Teste: o ramo de interesse cancela o move junto; o orçamento zera a matrícula do
      dia; a leitura fail-closed devolve os defaults sem a tabela; e `disparos_de_hoje`
      conta pelo dia de `America/Sao_Paulo`, não UTC (vire a data às 21h BRT num teste e
      prove).

---

# LOTE 3 — paralelo (depois de H2 verificado)

## Task H3: scheduler — conjunto de etapas, toque que move, teto no envio

**Files:** `backend/app/follow_up/scheduler.py`,
`backend/tests/test_scheduler_joao_2026_09_18.py`

**LEIA ANTES:** a guarda de etapa que entrou em 25/09 em `_process_joao_touch`, e
`_mover_card_joao`.

**O caminho `standard` da ValerIA não pode mudar uma linha.** Rode a suíte dela antes e
depois e reporte os dois números.

- [ ] A guarda de etapa e o `etapa_vigiada` do move passam a testar PERTENCIMENTO ao
      conjunto `etapas_vivas` em vez de igualdade.
- [ ] Toque com `move_para`: **envia → marca `sent` → move**, nessa ordem. Falha no move
      NÃO reenvia (a mensagem já saiu) — loga `error` e segue.
- [ ] `_mover_card_joao` passa a escrever **as duas** colunas de etapa (`stage_id` e a
      legada `stage`) — spec §6.
- [ ] Teto diário no ENVIO, usando os helpers do CONTRATO: estourou → `adiar_job_para_amanha`,
      **nunca** `_cancel_job`. UMA contagem por tick, não uma por job.
- [ ] Os `job_type` da ValerIA **não** entram na contagem nem são barrados.
- [ ] **Mutação obrigatória:** trocar o adiamento por cancelamento e exigir vermelho —
      cancelar faria o cooldown por matrícula ler "o lead respondeu" e liberar
      rematrícula, virando laço. Relate o resultado.

## Task H4: a API e a tela

**Files:** `backend/app/follow_up/api.py`,
`backend/tests/test_api_definicao_joao_2026_09_18.py`,
`frontend/src/components/campaigns/followup-board.tsx`,
`frontend/src/components/campaigns/followup-board.test.tsx`

- [ ] `api.py`: GET passa a devolver um bloco `ajustes` com os dois valores efetivos e
      os defaults de código (`*_codigo`, mesmo padrão de `gatilho_dias_codigo`). PUT novo
      para gravá-los, com a mesma forma de recusa dos outros (400 com `problemas[]`).
      Valor < 1 é recusado.
- [ ] O payload da cadência ganha `etapas_vivas_rotulos: string[]` e, por toque,
      `move_para_rotulo: string | null` — **rótulos**, nunca chaves cruas (é a regra da
      entrega de 21/09).
- [ ] A tela: cabeçalho conta a jornada quando há move intermediário (spec §7); e dois
      campos globais editáveis, FORA do bloco por-cadência, porque valem para o motor
      inteiro.
- [ ] Números nunca hardcoded no frontend — vêm do payload. **Mutação:** trocar o valor
      do payload e provar que a tela mostra o novo. Relate.
- [ ] NOTA DE AMBIENTE: se faltar `node_modules`, rode `npm ci` de verdade. **Não** crie
      symlink para o `node_modules` do repo principal — o Turbopack recusa e o
      `next build` quebra.

---

# FECHAMENTO (orquestrador)

- [ ] `git fetch origin` e merge de `origin/master`.
- [ ] `git diff --diff-filter=D --name-only origin/master..HEAD` — vazio.
- [ ] Backend, `tsc`, `vitest`, `next build` verdes.
- [ ] Simular a jornada inteira de Reposição com o código novo: 45 dias → toque 1 + move
      → toques 2-4 sobrevivem → fim move para Em atenção.
- [ ] Confirmar que as duas migrations e o backfill **não** foram aplicados.
- [ ] Tudo continua nascendo desligado.
- [ ] **Não** pushar sem autorização.
