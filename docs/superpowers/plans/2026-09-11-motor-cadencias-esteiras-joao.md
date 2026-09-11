# Motor de Cadências — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o motor de cadências executar pela primeira vez, e deixar as esteiras do João montadas nele — visíveis e editáveis na tela.

**Architecture:** Consertos localizados no interpretador de grafo (`automation/engine.py`) e no contrato tela↔motor, mais um primitivo novo (`reset_enrollment`) que a decisão central da reunião exige. As duas garantias do dono (orçamento→Proposta Enviada, Fechado Ganho→Cliente Ativo) passam a resolver funil e etapa por **key** e por **funil de origem**, nunca por nome literal. Nada é ativado: tudo nasce `draft` e a prova é um ensaio com provider mock.

**Tech Stack:** Python 3.12 + pytest, Next.js App Router (TypeScript) + vitest, PostgreSQL (Supabase).

---

## Contexto obrigatório

Leia `docs/superpowers/specs/2026-09-11-motor-cadencias-esteiras-joao-design.md`.

**Quatro fatos medidos que o plano assume:**

1. O motor **nunca rodou**: `campaign_enrollments` = 0, `campaign_execution_log` = 0, campanhas `active` = 0. Não há matrícula viva para quebrar.
2. O nó `wait` **não avança** a matrícula. Existe **um** ponto que muda `current_node_id` (`engine.py:367`) e o ramo do `wait` (`:340-345`) dá `return` antes dele.
3. O follow-up da **ValerIA não usa este motor** (`follow_up/`, 8.140 jobs). A campanha com selo `SISTEMA` no builder é um espelho read-only. Não mexer nela.
4. `REPOSICAO_PIPELINE_NAME = "João - Reposição"` (`leads/reposicao.py:27`) aponta para um funil que **não existe mais** — virou "João - Reposição Atacado".

**Travas:** worktree compartilhado — git só leitura (`log`/`diff`/`show`) mais `add`/`commit` dos arquivos da própria task; **proibido** `checkout`/`restore`/`reset`/`stash`. Nunca `git push`. Nunca aplicar migration.

**UUIDs de produção** (medidos 11/09/2026):

| funil | uuid |
|---|---|
| João - Atacado | `9706a14a-3d9a-413b-bceb-26838fc2cc45` |
| João - Private Label | `24fb6ce8-6b7b-4612-970d-8debb8c041b7` |
| João - Reposição Atacado | `79e35e6b-01d1-482a-bdf0-64c733ff1ca4` |
| João - Reposição Private Label | `9c027143-72f6-42d6-861f-a494ba5bbb4f` |
| canal do João (`channels.id`) | `a3a607b1-6bff-4370-8609-b275eef270dd` |

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `backend/app/automation/engine.py` | **modificar** — `wait` avança; `send_text` checa blacklist; ação no-op loga `skipped` |
| `backend/tests/test_wait_avanca_matricula.py` | **criar** — o teste que reprova o motor atual |
| `backend/app/campaigns/service.py` | **modificar** — primitivo `reset_enrollment` |
| `backend/app/campaigns/worker.py` | **modificar** — política `on_reply="reset"` |
| `backend/tests/test_on_reply_reset.py` | **criar** — testes do reset |
| `backend/app/leads/reposicao.py` | **modificar** — funil de destino por funil de origem (G2) |
| `backend/tests/test_reposicao_funil_por_origem.py` | **criar** |
| `supabase/migrations/20260911_cadencias_reentrada.sql` | **criar** — derruba a UNIQUE total |
| `backend/tests/test_cadencias_reentrada_migration.py` | **criar** — asserts no texto do SQL |
| `frontend/src/components/campaigns/cadence-flow/inspector.tsx` | **modificar** — filtro de etapa grava `key` |
| `frontend/src/app/(authenticated)/campanhas/page.tsx` | **modificar** — campo de público + painel de matrículas |
| `frontend/src/components/campaigns/cadence-enrollments-table.tsx` | **modificar** — aceitar "todas as campanhas" |
| `backend/app/campaigns/esteiras_joao.py` | **criar** — seed das 6 esteiras |
| `backend/tests/test_esteiras_joao_seed.py` | **criar** |

---

## Task 1: O nó `wait` passa a avançar a matrícula

Este é o conserto sem o qual nada mais importa. Hoje `_process_one` reagenda o **próprio** nó `wait`; o correto é agendar o **próximo** nó para depois.

**Files:**
- Test: `backend/tests/test_wait_avanca_matricula.py` (criar)
- Modify: `backend/app/automation/engine.py:340-345`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""O no `wait` tem de AGENDAR O PROXIMO no, nao estacionar em si mesmo.

Havia um teste da funcao pura `_wait_target` (test_wait_node_hours_2026_07_11.py), que
confere a ARITMETICA do instante. Ninguem testava o CONTROLE DE FLUXO. O resultado:
existe um unico ponto que muda `current_node_id` (engine.py:367) e o ramo do `wait` dava
`return` antes dele — a matricula reagendava o mesmo `wait` a cada tick, para sempre, e
nenhuma cadencia de dois ou mais toques podia funcionar.

MEDICAO (11/09/2026): campaign_enrollments = 0 linhas em toda a historia. O motor nunca
rodou, e por isso ninguem descobriu.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.automation import engine

NOW = datetime(2026, 9, 11, 13, 0, tzinfo=timezone.utc)  # 10:00 BRT, dentro da janela

WAIT_NODE = {
    "id": "no-wait",
    "type": "wait",
    "config": {"days": 1, "hours": 0},
    "next_node_id": "no-envio-2",
    "yes_node_id": None,
    "no_node_id": None,
}

ENROLLMENT = {
    "id": "matricula-1",
    "lead_id": "lead-1",
    "campaign_id": "camp-1",
    "current_node_id": "no-wait",
    "step_count": 3,
    "last_sent_node_id": "no-envio-1",
    "campaign_nodes": WAIT_NODE,
    "leads": {"id": "lead-1", "phone": "5534988861441", "ai_enabled": False},
    "campaigns": {"id": "camp-1", "status": "active", "audience": "humano"},
    "metadata": {},
}


def _rodar_wait():
    """Executa _process_one num no `wait` e devolve os kwargs de cada _update."""
    chamadas = []
    with patch.object(engine, "_update", side_effect=lambda eid, **kw: chamadas.append(kw)), \
         patch.object(engine, "_log_exec"), \
         patch.object(engine, "_guard_broken", return_value=False), \
         patch.object(engine, "_conversation_followup_disabled", return_value=False), \
         patch.object(engine, "_audience_allows", return_value=True), \
         patch.object(engine, "get_supabase", MagicMock()):
        import asyncio
        asyncio.run(engine._process_one(dict(ENROLLMENT), NOW))
    return chamadas


def test_wait_avanca_para_o_proximo_no():
    """O CRITERIO DE APROVACAO do ensaio: current_node_id MUDA ao passar por um wait."""
    chamadas = _rodar_wait()
    assert chamadas, "_process_one nao escreveu nada — o no wait foi ignorado"
    avanco = [c for c in chamadas if "current_node_id" in c]
    assert avanco, (
        "o no wait nao mudou current_node_id — a matricula estaciona nele para sempre"
    )
    assert avanco[-1]["current_node_id"] == "no-envio-2"


def test_wait_agenda_o_proximo_no_para_o_futuro():
    """Avancar sem adiar transformaria o wait em no-op: o proximo toque sairia no mesmo tick."""
    chamadas = _rodar_wait()
    agendamento = [c for c in chamadas if "next_execute_at" in c]
    assert agendamento, "o no wait nao agendou nada"
    alvo = datetime.fromisoformat(agendamento[-1]["next_execute_at"])
    assert alvo > NOW, f"o wait agendou para {alvo}, que nao e depois de {NOW}"


def test_wait_incrementa_step_count():
    """Sem isso o anti-loop MAX_STEPS nunca ve os ciclos que passam por wait."""
    chamadas = _rodar_wait()
    passo = [c for c in chamadas if "step_count" in c]
    assert passo, "o no wait nao incrementou step_count"
    assert passo[-1]["step_count"] == ENROLLMENT["step_count"] + 1


def test_wait_limpa_last_sent_node_id():
    """`last_sent_node_id` e a idempotencia do envio. Carregado para o proximo no, ele
    faria o envio seguinte ser pulado como se ja tivesse acontecido."""
    chamadas = _rodar_wait()
    limpeza = [c for c in chamadas if "last_sent_node_id" in c]
    assert limpeza, "o no wait nao limpou last_sent_node_id"
    assert limpeza[-1]["last_sent_node_id"] is None


def test_wait_sem_proximo_no_encerra_em_vez_de_estacionar():
    """Wait que e o ultimo no do grafo: o fluxo acabou. Estacionar criaria zumbi."""
    enrollment = dict(ENROLLMENT)
    enrollment["campaign_nodes"] = {**WAIT_NODE, "next_node_id": None}
    completados = []
    with patch.object(engine, "_update", side_effect=lambda eid, **kw: None), \
         patch.object(engine, "_complete", side_effect=lambda eid: completados.append(eid)), \
         patch.object(engine, "_log_exec"), \
         patch.object(engine, "_guard_broken", return_value=False), \
         patch.object(engine, "_conversation_followup_disabled", return_value=False), \
         patch.object(engine, "_audience_allows", return_value=True), \
         patch.object(engine, "get_supabase", MagicMock()):
        import asyncio
        asyncio.run(engine._process_one(enrollment, NOW))
    assert completados == ["matricula-1"], "wait sem proximo no deveria completar a matricula"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_wait_avanca_matricula.py -v`
Expected: FAIL — `test_wait_avanca_para_o_proximo_no` com "o no wait nao mudou current_node_id"

**Se algum teste passar já agora, pare e reporte** — significa que o diagnóstico está errado.

- [ ] **Step 3: Consertar o ramo do `wait`**

Em `backend/app/automation/engine.py`, substituir o bloco:

```python
        elif node_type == "wait":
            target = _wait_target(cfg, now)
            _update(enrollment["id"], next_execute_at=target.isoformat(), claimed_at=None)
            _log_exec(enrollment, node, "done",
                      f"aguardando (d={cfg.get('days', 1)}, h={cfg.get('hours', 0)})")
            return
```

por:

```python
        elif node_type == "wait":
            # O `wait` AGENDA O PROXIMO no para depois — nao estaciona em si mesmo.
            #
            # Ate 11/09/2026 este ramo reagendava o PROPRIO no e dava `return` antes do
            # avanco de `:367`, o unico ponto do codigo que muda `current_node_id`. A
            # matricula voltava ao mesmo `wait` a cada tick, indefinidamente: nenhuma
            # cadencia de dois ou mais toques podia funcionar. Como o motor nunca rodou
            # em producao (0 matriculas na historia), o defeito nunca apareceu.
            #
            # `last_sent_node_id=None` importa: ele e a idempotencia do envio, e carregado
            # para o proximo no faria o toque seguinte ser pulado como se ja tivesse saido.
            target = _wait_target(cfg, now)
            proximo = node.get("next_node_id")
            _log_exec(enrollment, node, "done",
                      f"aguardando (d={cfg.get('days', 1)}, h={cfg.get('hours', 0)})")
            if not proximo:
                # Wait como ultimo no do grafo: o fluxo acabou. Estacionar criaria zumbi.
                _complete(enrollment["id"])
                return
            _update(enrollment["id"],
                    current_node_id=proximo,
                    next_execute_at=target.isoformat(),
                    retry_count=0,
                    last_error=None,
                    claimed_at=None,
                    last_sent_node_id=None,
                    step_count=(enrollment.get("step_count") or 0) + 1)
            return
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd backend && python -m pytest tests/test_wait_avanca_matricula.py -v`
Expected: PASS — 5 testes

- [ ] **Step 5: Rodar a suíte inteira**

Run: `cd backend && python -m pytest -q`
Expected: **4217 passed, 4 skipped** (4212 do baseline + 5 desta task). Se algum teste antigo quebrar, **pare e reporte** — pode ser um teste que codificava o comportamento errado.

- [ ] **Step 6: Commit**

```bash
git add backend/app/automation/engine.py backend/tests/test_wait_avanca_matricula.py
git commit -m "fix(cadencias): o no wait avanca a matricula em vez de estacionar nela"
```

---

## Task 2: `on_reply="reset"` — a decisão central da reunião

A reunião de 10/09 decidiu que a esteira "Em conversa" **reseta a cada resposta do lead**. O motor conhece duas políticas (`cancel`, `pause`) e não sabe rebobinar.

Com `reset` a matrícula **permanece `active`**, então nunca passa pelo caminho de reinscrição — e o cooldown de 90 dias da RPC, que trancava o card para fora, deixa de ser obstáculo. Era por isso que `cancel` + reinscrever não servia.

**Files:**
- Test: `backend/tests/test_on_reply_reset.py` (criar)
- Modify: `backend/app/campaigns/service.py` (após `pause_enrollment`, ~linha 192)
- Modify: `backend/app/campaigns/worker.py` (`_trigger_on_reply` vizinho, e `_apply_reply_policy`)

- [ ] **Step 1: Escrever o teste que falha**

```python
"""`on_reply='reset'`: a resposta do lead rebobina a esteira em vez de encerra-la.

Decisao da reuniao de 10/09/2026 para a esteira "Em conversa": 7 toques em 30 dias, e
qualquer resposta do lead volta o relogio para D+0. O motor so sabia `cancel` e `pause`.

Por que nao bastava `cancel` + reinscrever: o cancelamento tranca o card para fora pelo
cooldown de 90 dias da RPC (`get_deals_stage_stagnant`), e `pause` conta como matricula
viva em `is_already_enrolled` sem que ninguem a retome. Com `reset` a matricula fica
ACTIVE e nunca passa pelo caminho de reinscricao — o cooldown deixa de ser obstaculo.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.campaigns import worker


TRIGGER = {"id": "no-gatilho", "type": "trigger", "config": {"on_reply": "reset"},
           "next_node_id": "no-primeiro-toque"}
ENVIO = {"id": "no-envio-3", "type": "send", "config": {}, "next_node_id": "no-wait-3"}

ENROLLMENT = {
    "id": "matricula-1",
    "campaign_id": "camp-1",
    "lead_id": "lead-1",
    "current_node_id": "no-envio-3",
    "step_count": 6,
    "campaign_nodes": ENVIO,
}


class TestPoliticaReset:
    def test_resposta_rebobina_para_o_primeiro_no(self):
        with patch.object(worker, "list_nodes", return_value=[TRIGGER, ENVIO]), \
             patch.object(worker, "reset_enrollment") as mock_reset, \
             patch.object(worker, "cancel_enrollment") as mock_cancel, \
             patch.object(worker, "pause_enrollment") as mock_pause:
            worker._apply_reply_policy(dict(ENROLLMENT))
        mock_reset.assert_called_once_with("matricula-1", "no-primeiro-toque")
        mock_cancel.assert_not_called()
        mock_pause.assert_not_called()

    def test_sem_primeiro_no_cai_em_pause_em_vez_de_quebrar(self):
        """FAIL-SAFE, mesma doutrina de `_trigger_on_reply`: pausar por engano e
        recuperavel; perder a esteira nao e."""
        gatilho_sem_saida = {**TRIGGER, "next_node_id": None}
        with patch.object(worker, "list_nodes", return_value=[gatilho_sem_saida, ENVIO]), \
             patch.object(worker, "reset_enrollment") as mock_reset, \
             patch.object(worker, "pause_enrollment") as mock_pause:
            worker._apply_reply_policy(dict(ENROLLMENT))
        mock_reset.assert_not_called()
        mock_pause.assert_called_once_with("matricula-1")

    def test_politica_do_no_vence_a_do_gatilho(self):
        """Precedencia existente preservada: o no descreve um toque, o gatilho descreve
        a esteira — e o no, quando opina, vence."""
        envio_que_pausa = {**ENVIO, "config": {"on_reply": "pause"}}
        enrollment = {**ENROLLMENT, "campaign_nodes": envio_que_pausa}
        with patch.object(worker, "list_nodes", return_value=[TRIGGER, envio_que_pausa]), \
             patch.object(worker, "reset_enrollment") as mock_reset, \
             patch.object(worker, "pause_enrollment") as mock_pause:
            worker._apply_reply_policy(enrollment)
        mock_reset.assert_not_called()
        mock_pause.assert_called_once_with("matricula-1")


class TestPrimitivoReset:
    def test_reset_mantem_a_matricula_ativa(self):
        """O ponto do desenho: ficando ACTIVE, ela nunca passa por reinscricao e o
        cooldown de 90 dias da RPC deixa de tranca-la para fora."""
        from app.campaigns.service import reset_enrollment
        mock_sb = MagicMock()
        with patch("app.campaigns.service.get_supabase", return_value=mock_sb):
            reset_enrollment("matricula-1", "no-primeiro-toque")
        payload = mock_sb.table.return_value.update.call_args[0][0]
        assert payload["status"] == "active"
        assert payload["current_node_id"] == "no-primeiro-toque"
        assert payload["step_count"] == 0
        assert payload["last_sent_node_id"] is None
        assert payload["paused_at"] is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_on_reply_reset.py -v`
Expected: FAIL — `ImportError` / `AttributeError` em `reset_enrollment`

- [ ] **Step 3: Criar o primitivo `reset_enrollment`**

Em `backend/app/campaigns/service.py`, logo depois de `pause_enrollment` (~linha 192):

```python
def reset_enrollment(enrollment_id: str, first_node_id: str) -> None:
    """Rebobina a matricula para o primeiro no, mantendo-a ATIVA.

    Terceira politica de `on_reply`, ao lado de `cancel` e `pause`. Existe para a esteira
    "Em conversa" da reuniao de 10/09/2026: 7 toques em 30 dias, e qualquer resposta do
    lead devolve o relogio para D+0.

    MANTER `status='active'` e o ponto do desenho, nao um detalhe. Cancelar e reinscrever
    pareceria equivalente, mas o cooldown de 90 dias da RPC `get_deals_stage_stagnant`
    conta QUALQUER matricula por `enrolled_at`, sem filtrar status — o card ficaria
    inelegivel por tres meses. Como o reset nao passa pelo caminho de reinscricao, o
    cooldown nunca e consultado.

    `last_sent_node_id=None` porque ele e a idempotencia do envio: carregado para o no
    rebobinado, faria o primeiro toque do novo ciclo ser pulado como se ja tivesse saido.
    `paused_at=None` limpa residuo de uma pausa anterior.
    """
    sb = get_supabase()
    sb.table("campaign_enrollments").update({
        "status": "active",
        "current_node_id": first_node_id,
        "next_execute_at": datetime.now(timezone.utc).isoformat(),
        "step_count": 0,
        "last_sent_node_id": None,
        "retry_count": 0,
        "last_error": None,
        "paused_at": None,
        "claimed_at": None,
    }).eq("id", enrollment_id).execute()
```

- [ ] **Step 4: Ensinar a política ao `_apply_reply_policy`**

Em `backend/app/campaigns/worker.py`, acrescentar o helper ao lado de `_trigger_on_reply`:

```python
def _trigger_first_node(campaign_id: str | None) -> str | None:
    """`next_node_id` do no de gatilho — o primeiro no EXECUTAVEL da esteira.

    E para ele que `on_reply='reset'` rebobina. Espelha `_trigger_on_reply`: mesma
    consulta, mesma doutrina fail-safe (None → o chamador pausa em vez de adivinhar).
    """
    if not campaign_id:
        return None
    try:
        from app.campaigns.service import list_nodes
        for n in list_nodes(campaign_id) or []:
            if n.get("type") == "trigger" and n.get("next_node_id"):
                return n["next_node_id"]
    except Exception as exc:
        logger.error("[CAMPAIGNS] falha ao resolver o primeiro no de %s: %s", campaign_id, exc)
    return None
```

E, dentro de `_apply_reply_policy`, trocar o bloco de decisão. O trecho atual:

```python
    if node_on_reply is not None:
        cancelar = node_on_reply == "cancel" and node.get("type") == "send"
        origem = "nó"
    else:
        cancelar = _trigger_on_reply(enrollment.get("campaign_id")) == "cancel"
        origem = "gatilho"
    if cancelar:
```

passa a ser:

```python
    if node_on_reply is not None:
        politica = node_on_reply
        origem = "nó"
    else:
        politica = _trigger_on_reply(enrollment.get("campaign_id"))
        origem = "gatilho"

    # `reset` rebobina em vez de encerrar (esteira "Em conversa", reunião de 10/09/2026).
    # Fail-safe: sem primeiro nó resolvido, pausa — pausar por engano é recuperável.
    if politica == "reset":
        primeiro = _trigger_first_node(enrollment.get("campaign_id"))
        if primeiro:
            reset_enrollment(enrollment["id"], primeiro)
            logger.info(
                "[CAMPAIGNS] Reset enrollment %s — lead respondeu (on_reply=reset via %s)",
                enrollment["id"], origem,
            )
            return
        logger.warning(
            "[CAMPAIGNS] on_reply=reset em %s sem primeiro nó resolvível — pausando",
            enrollment["id"],
        )

    # `cancel` vindo do NÓ segue restrito a nós `send`, como sempre foi.
    cancelar = politica == "cancel" and (origem == "gatilho" or node.get("type") == "send")
    if cancelar:
```

E acrescentar `reset_enrollment` ao import de `app.campaigns.service` no topo do arquivo, junto de `cancel_enrollment` e `pause_enrollment`.

- [ ] **Step 5: Rodar os testes desta task e a suíte**

Run: `cd backend && python -m pytest tests/test_on_reply_reset.py -v && python -m pytest -q`
Expected: 5 novos passam; suíte em **4222 passed, 4 skipped**

- [ ] **Step 6: Commit**

```bash
git add backend/app/campaigns/service.py backend/app/campaigns/worker.py backend/tests/test_on_reply_reset.py
git commit -m "feat(cadencias): on_reply=reset rebobina a esteira mantendo a matricula ativa"
```

---

## Task 3: O filtro de etapa passa a gravar `key`, não rótulo

O `<select>` de etapa grava `s.label` e o motor compara com `pipeline_stages.key` ou `leads.stage`. Interseção medida: **vazia**. Há prova salva em produção — a campanha "Reposição Inteligente — João" tem `{"stage_filter": "Novo (Frio)"}`, um rótulo onde o motor espera uma key. A `key` **já está carregada** no objeto e nunca é usada.

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow/inspector.tsx` (3 ocorrências de `value={s.label}`)

- [ ] **Step 1: Localizar as três ocorrências**

Run: `cd frontend && grep -n "value={s.label}" src/components/campaigns/cadence-flow/inspector.tsx`
Expected: 3 linhas (aproximadamente 166, 187, 413)

**Se o número for diferente de 3, pare e reporte** — o arquivo mudou desde a auditoria.

- [ ] **Step 2: Trocar as três por `value={s.key ?? ""}`**

Em cada uma das três linhas, trocar `value={s.label}` por `value={s.key ?? ""}`. O texto visível da `<option>` continua sendo `{s.label}` — muda só o valor gravado.

Acrescentar, acima do primeiro `<select>` afetado, o comentário:

```tsx
{/* O VALOR gravado e a `key`, nunca o rotulo: o motor compara com
    pipeline_stages.key (triggers.py) e o rotulo e editavel pelo operador.
    Ate 11/09/2026 gravava-se `s.label`, e a intersecao medida entre os dois
    conjuntos era vazia — o gatilho nunca casava com card nenhum. */}
```

- [ ] **Step 3: Verificar que nenhuma etapa fica sem valor**

Run: `cd frontend && grep -n "value={s.key ?? \"\"}" src/components/campaigns/cadence-flow/inspector.tsx`
Expected: 3 linhas

Desde a migration do SP0 toda etapa dos funis do João tem `key`. Etapa sem key vira valor vazio, e a RPC é fail-closed (exige `stage_id` ou `stage_key`), então o gatilho não dispara em vez de disparar errado.

- [ ] **Step 4: type-check e testes**

Run: `cd frontend && npm run type-check && npx vitest run`
Expected: `tsc` sem saída; **792 passed**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/campaigns/cadence-flow/inspector.tsx
git commit -m "fix(cadencias): filtro de etapa grava key em vez de rotulo"
```

---

## Task 4: `send_text` checa blacklist, e ação sem alvo para de logar sucesso

Dois consertos pequenos no mesmo arquivo. O nó `send` tem guarda de blacklist desde 25/06; o `send_text` não. E uma ação cujo alvo não existe grava "executada" no log — o operador vê ✅ onde nada aconteceu.

**Files:**
- Test: `backend/tests/test_send_text_blacklist.py` (criar)
- Modify: `backend/app/automation/engine.py` (`_execute_send_text` e o log de ação)

- [ ] **Step 1: Escrever o teste que falha**

```python
"""`send_text` tem de honrar a blacklist, como o `send` ja faz.

O no `send` (template) ganhou a guarda em 25/06/2026; o `send_text` (texto livre) nunca
teve. Um lead que pediu para sair continuava recebendo texto livre da cadencia.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.automation import engine

NOW = datetime(2026, 9, 11, 13, 0, tzinfo=timezone.utc)

NODE = {"id": "no-texto", "type": "send_text", "config": {"text": "oi"}, "next_node_id": None}
ENROLLMENT = {
    "id": "m-1", "lead_id": "lead-1", "campaign_id": "camp-1",
    "current_node_id": "no-texto", "step_count": 0, "last_sent_node_id": None,
    "campaign_nodes": NODE,
    "leads": {"id": "lead-1", "phone": "5534988861441", "ai_enabled": False},
    "campaigns": {"id": "camp-1", "status": "active", "audience": "humano"},
}


@pytest.mark.asyncio
async def test_send_text_nao_envia_para_lead_na_blacklist():
    enviou = AsyncMock()
    with patch.object(engine, "is_lead_blacklisted", return_value=True), \
         patch.object(engine, "_resolve_provider_and_send_text", enviou), \
         patch.object(engine, "get_supabase", MagicMock()):
        await engine._execute_send_text(dict(ENROLLMENT), NODE,
                                        ENROLLMENT["leads"], NOW, ENROLLMENT["campaigns"])
    enviou.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_text_envia_para_lead_fora_da_blacklist():
    enviou = AsyncMock()
    with patch.object(engine, "is_lead_blacklisted", return_value=False), \
         patch.object(engine, "_resolve_provider_and_send_text", enviou), \
         patch.object(engine, "get_supabase", MagicMock()):
        await engine._execute_send_text(dict(ENROLLMENT), NODE,
                                        ENROLLMENT["leads"], NOW, ENROLLMENT["campaigns"])
    enviou.assert_awaited_once()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_send_text_blacklist.py -v`
Expected: FAIL — `AttributeError` (os símbolos `is_lead_blacklisted` / `_resolve_provider_and_send_text` ainda não existem em `engine`)

**Ao implementar, leia primeiro `_execute_send_text` (`engine.py:407-437`) e adapte os nomes do teste à estrutura real da função** — se ela não isola o envio numa chamada mockável, extraia essa chamada para um helper `_resolve_provider_and_send_text` e ajuste o teste. Se precisar desviar do texto acima, **reporte o desvio**.

- [ ] **Step 3: Implementar a guarda**

No início de `_execute_send_text`, antes de qualquer envio:

```python
    # Mesma guarda que o no `send` tem desde 25/06/2026. Sem ela, o texto livre da
    # cadencia continuava saindo para quem ja tinha pedido para sair.
    from app.campaigns.worker import is_lead_blacklisted
    if is_lead_blacklisted(lead["id"]):
        logger.info("[AUTOMATION] send_text abortado — lead %s na blacklist", lead["id"])
        return None
```

- [ ] **Step 4: Ação sem alvo loga `skipped`**

Em `engine.py`, o ramo `elif node_type == "action":` hoje loga `done` incondicionalmente. Fazer `_execute_action` devolver `bool` (True = agiu, False = no-op) e usar:

```python
        elif node_type == "action":
            agiu = _execute_action(enrollment, node, lead)
            _log_exec(enrollment, node, "done" if agiu else "skipped",
                      f"ação {(cfg.get('action_type') or 'desconhecida')} "
                      + ("executada" if agiu else "sem alvo — nada foi feito"))
```

Cada ramo de `_execute_action` passa a `return True` ao agir e `return False` nos retornos antecipados por falta de alvo.

- [ ] **Step 5: Rodar os testes e a suíte**

Run: `cd backend && python -m pytest tests/test_send_text_blacklist.py -v && python -m pytest -q`
Expected: 2 novos passam; suíte em **4224 passed, 4 skipped**

- [ ] **Step 6: Commit**

```bash
git add backend/app/automation/engine.py backend/tests/test_send_text_blacklist.py
git commit -m "fix(cadencias): send_text honra blacklist e acao sem alvo loga skipped"
```

---

## Task 5: Migration — o lead pode reentrar numa campanha

Existe `UNIQUE (campaign_id, lead_id)` **sem cláusula parcial** em `campaign_enrollments`, além do índice parcial `uq_campaign_enrollments_active`. O total impede o lead de entrar numa campanha mais de uma vez **na vida** — fatal para a esteira de reposição, que repete a cada 45 dias.

**Files:**
- Create: `supabase/migrations/20260911_cadencias_reentrada.sql`
- Test: `backend/tests/test_cadencias_reentrada_migration.py` (criar)

- [ ] **Step 1: Escrever o teste que falha**

```python
"""Guardas da migration `20260911_cadencias_reentrada.sql`.

Asserts no TEXTO do SQL: a migration nao roda no deploy (e aplicada a mao no editor do
Supabase) e a suite nao tem banco. Mesmo padrao de test_esteiras_migration_sql.py.
"""
import pathlib
import re

SQL = (
    pathlib.Path(__file__).resolve().parents[2]
    / "supabase" / "migrations" / "20260911_cadencias_reentrada.sql"
)


def _sem_comentario() -> str:
    txt = SQL.read_text(encoding="utf-8")
    limpo = "\n".join(l.split("--")[0] for l in txt.splitlines())
    return re.sub(r"\s+", " ", limpo).strip()


def test_arquivo_existe():
    assert SQL.exists(), f"migration nao encontrada em {SQL}"


def test_derruba_a_constraint_total():
    """E a UNIQUE sem clausula parcial que impede o lead de reentrar na vida."""
    sql = _sem_comentario()
    assert "campaign_enrollments_campaign_id_lead_id_key" in sql
    assert "DROP CONSTRAINT" in sql


def test_preserva_o_indice_parcial():
    """O parcial protege o que importa — matricula VIVA duplicada. Derruba-lo tambem
    permitiria duas matriculas ativas do mesmo lead na mesma esteira."""
    sql = _sem_comentario()
    assert "uq_campaign_enrollments_active" not in sql.replace(
        "uq_campaign_enrollments_active", "", 1
    ) or "DROP INDEX" not in sql, (
        "a migration nao pode derrubar o indice parcial"
    )


def test_e_idempotente():
    assert "IF EXISTS" in _sem_comentario()


def test_termina_com_notify_pgrst():
    txt = SQL.read_text(encoding="utf-8").rstrip()
    assert "NOTIFY pgrst" in txt
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_cadencias_reentrada_migration.py -v`
Expected: FAIL — 5 testes, o primeiro com "migration nao encontrada"

- [ ] **Step 3: Escrever a migration**

```sql
-- 20260911_cadencias_reentrada.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. Roda a MAO no SQL editor do Supabase, depois de lida
--    e revisada por um humano. Nenhum agente de IA deve aplica-la.
--
-- ── O QUE FAZ ───────────────────────────────────────────────────────────────
-- Derruba a UNIQUE TOTAL (campaign_id, lead_id) de campaign_enrollments, preservando
-- o indice PARCIAL `uq_campaign_enrollments_active`.
--
-- ── POR QUE ─────────────────────────────────────────────────────────────────
-- A constraint total impede um lead de entrar numa campanha mais de uma vez NA VIDA:
-- assim que a matricula vira 'completed', `create_enrollment` colide e o lead nunca
-- mais reentra. Isso e fatal para a esteira de reposicao, cujo desenho e justamente
-- repetir a cada 45 dias, e para qualquer automacao recorrente.
--
-- O que precisa continuar protegido e outra coisa: duas matriculas VIVAS do mesmo lead
-- na mesma campanha. Disso cuida o indice parcial, que permanece.
--
-- A constraint total e drift — nasceu fora de migration (nenhum arquivo em
-- supabase/migrations/ a cria). Esta migration a remove e documenta o porque.
--
-- Reexecutar e seguro: DROP ... IF EXISTS.

ALTER TABLE campaign_enrollments
  DROP CONSTRAINT IF EXISTS campaign_enrollments_campaign_id_lead_id_key;

NOTIFY pgrst, 'reload schema';
```

- [ ] **Step 4: Rodar os testes**

Run: `cd backend && python -m pytest tests/test_cadencias_reentrada_migration.py -v`
Expected: PASS — 5 testes

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260911_cadencias_reentrada.sql backend/tests/test_cadencias_reentrada_migration.py
git commit -m "feat(cadencias): migration que devolve a reentrada do lead numa campanha"
```

---

## Task 6: G2 — o card de reposição nasce no funil certo

`ensure_reposicao_deal` procura o funil pelo nome literal `"João - Reposição"`, que **não existe mais** (virou "João - Reposição Atacado"). `create_deal`, ao não achar o nome, **cai no primeiro pipeline por `order_index`** — o card nasce em funil aleatório, em silêncio.

E agora há **dois** funis de reposição. O destino certo é decidido pelo **funil de origem** do card que fechou.

**Files:**
- Test: `backend/tests/test_reposicao_funil_por_origem.py` (criar)
- Modify: `backend/app/leads/reposicao.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""O card de reposicao nasce no funil que corresponde a ORIGEM da venda.

Dois defeitos ao mesmo tempo:

1. `REPOSICAO_PIPELINE_NAME = "João - Reposição"` aponta para um funil que nao existe
   mais (renomeado para "João - Reposição Atacado" em 10/09/2026). `create_deal`, ao nao
   achar o nome, cai no PRIMEIRO pipeline por order_index — o card nasce em funil
   aleatorio, sem erro visivel.
2. Existem DOIS funis de reposicao agora. Quem decide o destino e o funil de origem:
   Atacado -> Reposicao Atacado; Private Label -> Reposicao Private Label.

A etapa alvo e resolvida por KEY (`novo` = "Cliente Ativo"), nunca por rotulo.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.leads import reposicao

ATACADO = "9706a14a-3d9a-413b-bceb-26838fc2cc45"
PLABEL = "24fb6ce8-6b7b-4612-970d-8debb8c041b7"
REP_ATACADO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"
REP_PLABEL = "9c027143-72f6-42d6-861f-a494ba5bbb4f"


class TestDestinoPorOrigem:
    def test_atacado_vai_para_reposicao_atacado(self):
        assert reposicao.reposicao_pipeline_para(ATACADO) == REP_ATACADO

    def test_private_label_vai_para_reposicao_private_label(self):
        assert reposicao.reposicao_pipeline_para(PLABEL) == REP_PLABEL

    def test_funil_desconhecido_devolve_none_em_vez_de_adivinhar(self):
        """Fail-closed: sem destino conhecido e melhor nao criar card do que cria-lo no
        funil errado. Era exatamente o que o fallback de create_deal fazia."""
        assert reposicao.reposicao_pipeline_para("00000000-0000-0000-0000-000000000000") is None

    def test_nao_usa_mais_nome_literal_de_funil(self):
        """O nome mudou uma vez e quebrou tudo em silencio; nao pode ser o contrato."""
        import inspect
        fonte = inspect.getsource(reposicao)
        assert "João - Reposição" not in fonte


class TestEnsureReposicaoDeal:
    def test_cria_no_funil_de_destino_com_etapa_por_key(self):
        criados = []
        with patch.object(reposicao, "create_deal", side_effect=lambda **kw: criados.append(kw)), \
             patch.object(reposicao, "_pipeline_de_origem", return_value=PLABEL):
            reposicao.ensure_reposicao_deal("lead-1", deal_id="deal-origem")
        assert len(criados) == 1
        assert criados[0]["pipeline_id"] == REP_PLABEL
        assert criados[0]["stage_key"] == "novo"

    def test_origem_desconhecida_nao_cria_card(self):
        criados = []
        with patch.object(reposicao, "create_deal", side_effect=lambda **kw: criados.append(kw)), \
             patch.object(reposicao, "_pipeline_de_origem", return_value=None):
            reposicao.ensure_reposicao_deal("lead-1", deal_id="deal-origem")
        assert criados == []
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_reposicao_funil_por_origem.py -v`
Expected: FAIL — `AttributeError: module has no attribute 'reposicao_pipeline_para'`

- [ ] **Step 3: Implementar**

Em `backend/app/leads/reposicao.py`, substituir `REPOSICAO_PIPELINE_NAME` pelo mapa e acrescentar as funções:

```python
# Origem -> destino da reposicao, por UUID. Ate 11/09/2026 isto era o NOME literal
# "João - Reposição", que deixou de existir quando o funil foi renomeado para
# "João - Reposição Atacado" — e `create_deal`, ao nao achar o nome, cai no primeiro
# pipeline por order_index. O card de reposicao passou a nascer em funil aleatorio, sem
# erro visivel. UUID nao e editavel pela tela; nome e.
REPOSICAO_POR_ORIGEM: dict[str, str] = {
    "9706a14a-3d9a-413b-bceb-26838fc2cc45": "79e35e6b-01d1-482a-bdf0-64c733ff1ca4",  # Atacado
    "24fb6ce8-6b7b-4612-970d-8debb8c041b7": "9c027143-72f6-42d6-861f-a494ba5bbb4f",  # Private Label
}

# "Cliente Ativo" resolvida por KEY, nunca por rotulo — e tambem o marco zero dos 45
# dias: `deals.entered_stage_at` do card recem-criado E a data da venda.
REPOSICAO_STAGE_KEY = "novo"


def reposicao_pipeline_para(pipeline_origem: str | None) -> str | None:
    """Funil de reposicao correspondente a origem. None quando desconhecida.

    Fail-closed de proposito: sem destino conhecido, nao criar card e melhor do que
    cria-lo no funil errado — que e o que o fallback de `create_deal` vinha fazendo.
    """
    if not pipeline_origem:
        return None
    return REPOSICAO_POR_ORIGEM.get(pipeline_origem)


def _pipeline_de_origem(deal_id: str | None) -> str | None:
    """`pipeline_id` do deal que fechou. Fail-soft."""
    if not deal_id:
        return None
    try:
        sb = get_supabase()
        row = sb.table("deals").select("pipeline_id").eq("id", deal_id).limit(1).execute().data
        return (row[0].get("pipeline_id") if row else None)
    except Exception as exc:
        logger.error("_pipeline_de_origem(%s) falhou: %s", deal_id, exc, exc_info=True)
        return None
```

E reescrever `ensure_reposicao_deal`:

```python
def ensure_reposicao_deal(lead_id: str, deal_id: str | None = None) -> None:
    """Cria o card de reposicao no funil correspondente a origem da venda.

    O `dedupe_open` e ESCOPADO ao funil de reposicao: sem escopo ele reaproveita
    qualquer card aberto do lead — inclusive o de handoff da ValerIA em outro funil — e
    o card de reposicao nunca chega a existir. Fail-soft: nunca levanta.
    """
    if not lead_id:
        return
    try:
        destino = reposicao_pipeline_para(_pipeline_de_origem(deal_id))
        if not destino:
            logger.info(
                "[REPOSICAO] origem desconhecida para deal=%s — card nao criado", deal_id
            )
            return
        create_deal(
            lead_id=lead_id,
            title="Reposição",
            pipeline_id=destino,
            stage_key=REPOSICAO_STAGE_KEY,
            dedupe_open=True,
            dedupe_pipeline_id=destino,
        )
    except Exception as exc:
        logger.error("ensure_reposicao_deal(%s) falhou: %s", lead_id, exc, exc_info=True)
```

**`create_deal` precisa aceitar `pipeline_id`, `stage_key` e `dedupe_pipeline_id`.** Leia a assinatura atual em `backend/app/leads/service.py:1090-1130` e acrescente os parâmetros que faltarem, preservando o comportamento de quem já a chama. Se a mudança em `create_deal` for maior do que acrescentar três parâmetros opcionais, **pare e reporte antes de prosseguir**.

- [ ] **Step 4: Atualizar os chamadores de `ensure_reposicao_deal`**

Run: `cd backend && grep -rn "ensure_reposicao_deal(" app/ --include=*.py`

Cada chamador passa a informar o `deal_id` do card que fechou. Onde o `deal_id` não estiver disponível no ponto da chamada, **pare e reporte** em vez de inventar.

- [ ] **Step 5: Rodar os testes e a suíte**

Run: `cd backend && python -m pytest tests/test_reposicao_funil_por_origem.py -v && python -m pytest -q`
Expected: 6 novos passam; suíte em **4230 passed, 4 skipped**

- [ ] **Step 6: Commit**

```bash
git add backend/app/leads/reposicao.py backend/app/leads/service.py backend/tests/test_reposicao_funil_por_origem.py
git commit -m "fix(reposicao): card nasce no funil da origem, com etapa resolvida por key"
```

---

## Task 7: A tela de matrículas na home de `/campanhas`

`CampaignEnrollmentsTable` **já existe e está órfã** — zero referências no repositório. Ela é escopada a uma campanha; o pedido do dono é a visão cruzada: quais leads estão em job e de qual cadência.

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-enrollments-table.tsx`
- Modify: `frontend/src/app/(authenticated)/campanhas/page.tsx`

- [ ] **Step 1: Ler o componente inteiro antes de mexer**

Run: `cd frontend && cat src/components/campaigns/cadence-enrollments-table.tsx`

Entender como ele busca (`fetchEnrollments`), o que renderiza e quais campos de `CampaignEnrollment` usa.

- [ ] **Step 2: Tornar `campaignId` opcional**

Trocar a interface e a consulta:

```tsx
interface CampaignEnrollmentsTableProps {
  /** Ausente = todas as campanhas (visão cruzada da home). */
  campaignId?: string;
}
```

E, no `fetchEnrollments`, aplicar o filtro por campanha só quando ele existir, trazendo o nome da campanha junto para a visão cruzada:

```tsx
let query = supabase
  .from("campaign_enrollments")
  .select("*, leads(id, name, phone), campaigns(id, name)")
  .order("next_execute_at", { ascending: true })
  .limit(200);
if (campaignId) query = query.eq("campaign_id", campaignId);
```

Quando `campaignId` estiver ausente, a tabela ganha uma coluna **Cadência** com `enrollment.campaigns?.name`.

- [ ] **Step 3: Renderizar na home de `/campanhas`**

Em `frontend/src/app/(authenticated)/campanhas/page.tsx`, importar e renderizar abaixo da lista de campanhas:

```tsx
<section className="mt-8">
  <h2 className="text-[13px] font-medium uppercase tracking-[0.6px] text-[#7b7b78] mb-3">
    Leads em cadência
  </h2>
  <CampaignEnrollmentsTable />
</section>
```

- [ ] **Step 4: type-check e testes**

Run: `cd frontend && npm run type-check && npx vitest run`
Expected: `tsc` sem saída; **792 passed**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/campaigns/cadence-enrollments-table.tsx "frontend/src/app/(authenticated)/campanhas/page.tsx"
git commit -m "feat(campanhas): painel de leads em cadencia na home"
```

---

## Task 8: Campo de público (`audience`) na tela

`campaigns.audience` nasce `'ia'` por default e **não tem campo em tela nenhuma**. Toda automação montada no builder é cega para os leads do João, que têm `ai_enabled=False` por definição — o handoff desliga a IA.

**Files:**
- Modify: `frontend/src/app/(authenticated)/campanhas/page.tsx` (formulário de criação/edição)
- Modify: `frontend/src/app/api/campaigns/route.ts` (POST aceita `audience`)

- [ ] **Step 1: Ler o formulário e a rota**

Run: `cd frontend && grep -n "frequency_cap\|priority" src/app/\(authenticated\)/campanhas/page.tsx | head -10 && sed -n '20,45p' src/app/api/campaigns/route.ts`

O campo novo entra ao lado de `priority` / `frequency_cap`, que já existem no mesmo formulário.

- [ ] **Step 2: Acrescentar o `<select>` de público**

```tsx
<label className="block">
  <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Público</span>
  {/* Sem este campo toda campanha nasce 'ia' e ignora os leads do vendedor, que tem
      ai_enabled=false por definicao (o handoff desliga a IA). Era o segundo motivo,
      depois do no `wait`, para uma automacao montada na tela nunca fazer nada. */}
  <select value={audience} onChange={e => setAudience(e.target.value)}>
    <option value="ia">Leads da ValerIA (IA ligada)</option>
    <option value="humano">Leads do vendedor (IA desligada)</option>
    <option value="ambos">Ambos</option>
  </select>
</label>
```

Com `const [audience, setAudience] = useState("ia")` no componente, e `audience` incluído no corpo do POST/PATCH.

- [ ] **Step 3: A rota aceitar e persistir**

Em `frontend/src/app/api/campaigns/route.ts`, no POST, incluir `audience` no objeto inserido, com validação:

```ts
const AUDIENCIAS = ["ia", "humano", "ambos"];
// ...
audience: AUDIENCIAS.includes(body.audience) ? body.audience : "ia",
```

- [ ] **Step 4: type-check e testes**

Run: `cd frontend && npm run type-check && npx vitest run`
Expected: `tsc` sem saída; **792 passed**

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/app/(authenticated)/campanhas/page.tsx" frontend/src/app/api/campaigns/route.ts
git commit -m "feat(campanhas): campo de publico no formulario de campanha"
```

---

## Task 9: O seed das esteiras do João

Seis campanhas (três esteiras × dois funis), todas `draft`, `audience='humano'`, canal do João.

**Files:**
- Create: `backend/app/campaigns/esteiras_joao.py`
- Test: `backend/tests/test_esteiras_joao_seed.py` (criar)
- Modify: `backend/app/main.py` (chamar o seed no startup, ao lado do seed antigo)

- [ ] **Step 1: Ler o seed existente como modelo**

Run: `cd backend && sed -n '1,60p' app/campaigns/esteiras.py && grep -n "def build_node_rows" -A 40 app/campaigns/esteiras.py`

O arquivo novo segue o mesmo padrão: UUID determinístico por `uuid5` incluindo o `env_tag`, idempotência por existência do id, fail-soft por esteira.

- [ ] **Step 2: Escrever o teste que falha**

```python
"""Seed das esteiras do Joao — 6 campanhas (3 esteiras x 2 funis), todas em draft.

Decisoes da reuniao de 10/09/2026 que este seed materializa:
- "Novo": card parado 2 DIAS na etapa `novo`. Dois dias, e nao 36h, porque cabe no
  `deal_stage_stagnation` — o unico gatilho completo do sistema, o unico com guarda de
  blacklist, numero errado e conversa finalizada — sem precisar de horas na RPC. A
  reuniao decidiu "36h a dois dias"; dois dias esta dentro do que o dono aprovou.
- "Em conversa": 7 toques em 30 dias (D+2/4/7/12/18/24/30) com `on_reply='reset'`.
- "Reposicao": 45 dias em "Cliente Ativo", depois 3, depois 15 e 15.
"""
import pytest

from app.campaigns.esteiras_joao import ESTEIRAS_JOAO, build_node_rows

ATACADO = "9706a14a-3d9a-413b-bceb-26838fc2cc45"
PLABEL = "24fb6ce8-6b7b-4612-970d-8debb8c041b7"
CANAL_JOAO = "a3a607b1-6bff-4370-8609-b275eef270dd"


def test_seis_esteiras_tres_por_funil():
    assert len(ESTEIRAS_JOAO) == 6
    funis = [e["pipeline_id"] for e in ESTEIRAS_JOAO]
    assert funis.count(ATACADO) == 3
    assert funis.count(PLABEL) == 3


def test_todas_nascem_em_draft():
    """Nada dispara sem o dono ligar. O motor so processa campanhas active."""
    assert all(e["status"] == "draft" for e in ESTEIRAS_JOAO)


def test_todas_miram_o_publico_do_vendedor():
    """audience='ia' (o default) ignoraria todo lead do Joao, que tem ai_enabled=False."""
    assert all(e["audience"] == "humano" for e in ESTEIRAS_JOAO)


def test_todas_apontam_para_o_canal_do_joao():
    assert all(e["channel_id"] == CANAL_JOAO for e in ESTEIRAS_JOAO)


def test_ids_sao_deterministicos_e_distintos():
    ids = [e["campaign_id"] for e in ESTEIRAS_JOAO]
    assert len(set(ids)) == 6


def test_esteira_novo_usa_dois_dias_na_etapa():
    novo = [e for e in ESTEIRAS_JOAO if e["key"].startswith("novo")]
    assert len(novo) == 2
    for e in novo:
        assert e["gatilho"]["stage_key"] == "novo"
        assert e["gatilho"]["stage_days"] == 2


def test_esteira_em_conversa_tem_sete_toques_e_reseta():
    conversa = [e for e in ESTEIRAS_JOAO if e["key"].startswith("em_conversa")]
    assert len(conversa) == 2
    for e in conversa:
        assert e["gatilho"]["stage_key"] == "respondeu"
        assert e["gatilho"]["on_reply"] == "reset"
        assert [t["dias"] for t in e["toques"]] == [2, 2, 3, 5, 6, 6, 6]


def test_esteira_reposicao_tem_quarenta_e_cinco_dias_e_depois_3_15_15():
    rep = [e for e in ESTEIRAS_JOAO if e["key"].startswith("reposicao")]
    assert len(rep) == 2
    for e in rep:
        assert e["gatilho"]["stage_days"] == 45
        assert [t["dias"] for t in e["toques"]] == [0, 3, 15, 15]


def test_em_conversa_e_reposicao_terminam_em_em_atencao():
    """Estado terminal da esteira: sai do automatico e vira decisao do vendedor."""
    for e in ESTEIRAS_JOAO:
        if e["key"].startswith(("em_conversa", "reposicao")):
            assert e["acao_final"] == "move_deal_stage"
            assert e["stage_key_final"] == "em_atencao"


def test_build_node_rows_gera_grafo_ligado():
    """Todo no, exceto o ultimo, aponta para o proximo — grafo sem no orfao."""
    for e in ESTEIRAS_JOAO:
        nos = build_node_rows(e)
        ids = {n["id"] for n in nos}
        for n in nos[:-1]:
            assert n.get("next_node_id") in ids, (
                f"no {n['id']} da esteira {e['key']} aponta para fora do grafo"
            )
        assert nos[-1]["type"] == "end"
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `cd backend && python -m pytest tests/test_esteiras_joao_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: app.campaigns.esteiras_joao`

- [ ] **Step 4: Escrever o seed**

Criar `backend/app/campaigns/esteiras_joao.py` seguindo o padrão de `esteiras.py`, com `ESTEIRAS_JOAO` satisfazendo os testes acima, `build_node_rows(esteira)` produzindo a cadeia `trigger → (send → wait)* → action → end`, e `seed_esteiras_joao()` idempotente por existência do id.

Os **intervalos** de "Em conversa" são os deltas entre os toques absolutos D+2/4/7/12/18/24/30 — ou seja `[2, 2, 3, 5, 6, 6, 6]`, que é o que o teste exige.

Os `template_name` ficam como string vazia: **template é responsabilidade do dono**, preenchida na tela, e ligar a esteira exige template aprovado.

- [ ] **Step 5: Chamar no startup**

Em `backend/app/main.py`, ao lado do `seed_esteiras` existente:

```python
    try:
        from app.campaigns.esteiras_joao import seed_esteiras_joao
        await asyncio.to_thread(seed_esteiras_joao)
    except Exception as exc:
        logger.error("[STARTUP] seed das esteiras do Joao falhou: %s", exc)
```

- [ ] **Step 6: Rodar os testes e a suíte**

Run: `cd backend && python -m pytest tests/test_esteiras_joao_seed.py -v && python -m pytest -q`
Expected: 10 novos passam; suíte em **4240 passed, 4 skipped**

- [ ] **Step 7: Commit**

```bash
git add backend/app/campaigns/esteiras_joao.py backend/tests/test_esteiras_joao_seed.py backend/app/main.py
git commit -m "feat(esteiras): seed das 6 esteiras do Joao, em draft e no canal dele"
```

---

## Task 10: Verificação final

**Files:** nenhum — só verificação.

- [ ] **Step 1: Suíte de backend**

Run: `cd backend && python -m pytest -q`
Expected: **4240 passed, 4 skipped**. Se divergir, conferir antes de seguir.

- [ ] **Step 2: Portões de frontend, iguais aos do CI**

```bash
cd frontend
npm run type-check
npx vitest run
NEXT_PUBLIC_SUPABASE_URL=https://placeholder.supabase.co \
NEXT_PUBLIC_SUPABASE_ANON_KEY=placeholder-anon-key \
NEXT_PUBLIC_FASTAPI_URL=http://placeholder.api.local \
npm run build
```
Expected: `tsc` sem saída; **792 passed**; build exit 0

- [ ] **Step 3: Confirmar que nada foi aplicado nem ativado**

Run: `cd backend && grep -c "NOTIFY pgrst" ../supabase/migrations/20260911_cadencias_reentrada.sql`
Expected: `1`

**A migration NÃO deve ser aplicada por nenhum agente.** Ela é entregue ao dono.

- [ ] **Step 4: Relatório para o dono**

Sem commitar, reportar:
- que a migration `20260911` precisa ser aplicada à mão;
- que as 6 esteiras nascem em `draft`, sem template, e que ligar exige template aprovado;
- que o ensaio do §B6 do spec ainda não foi executado — ele exige um backend dev com `REHEARSAL_MODE`, que é decisão de ambiente do dono;
- que nada foi pushed.

---

## Auto-revisão deste plano

**Cobertura do spec:**

| bloco do spec | task |
|---|---|
| B1.1 `wait` avança | Task 1 |
| B1.2 filtro grava `key` | Task 3 |
| B1.3 campo de público | Task 8 |
| B1.4 derrubar UNIQUE total | Task 5 |
| B1.5 `send_text` blacklist | Task 4 |
| B1.6 ação no-op loga `skipped` | Task 4 |
| B2 `on_reply="reset"` | Task 2 |
| B3/G2 reposição por origem | Task 6 |
| B4 tela de matrículas | Task 7 |
| B5 as seis esteiras | Task 9 |
| B6 a prova | Task 10 Step 4 (entregue ao dono) |

**Lacuna consciente:** **B3/G1** (orçamento com vínculo obrigatório) **não tem task**. Ela depende de uma decisão de produto que o spec registra como pendência do dono — sem adoção do `/orcamento`, o conserto técnico não muda nada (`quotes` tem 0 linhas). Fica para um plano próprio, junto da conversa com o João.

**Consistência de tipos:** `reset_enrollment(enrollment_id, first_node_id)` é definida na Task 2 e usada com essa assinatura no mesmo arquivo. `reposicao_pipeline_para(pipeline_origem)` e `_pipeline_de_origem(deal_id)` são definidas e usadas na Task 6. `ESTEIRAS_JOAO` / `build_node_rows` / `seed_esteiras_joao` são definidas na Task 9 e usadas no `main.py` da mesma task.

**Ordem:** Task 1 antes de tudo (sem ela nada executa). Task 2 antes da Task 9 (a esteira "Em conversa" usa `reset`). Task 6 antes de ligar a esteira de Reposição (sem G2 não existem cards em "Cliente Ativo"). As demais são independentes.
