# Esteiras do Vendedor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Três esteiras automáticas (etapa Novo, reposição, follow-up de proposta) que trabalham o funil do vendedor humano, configuráveis numa tela sem deploy.

**Architecture:** Estende o motor de automação existente (`backend/app/automation/`) com um gatilho de estagnação por etapa do Kanban, um conceito de público (`campaigns.audience`) que libera o motor para agir sobre leads sob controle humano, e uma guarda que encerra a esteira quando o card muda de coluna. As esteiras em si nascem como campanhas normais (seed idempotente) e são editadas numa aba nova de `/campanhas`.

**Tech Stack:** Python 3 / FastAPI / Supabase (PostgREST + RPC), Next.js App Router / React / TypeScript, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-09-04-esteiras-vendedor-design.md`

---

## Contexto que o executor precisa saber

**O repositório não roda migrations no deploy.** O GitHub Actions sobe imagem Docker; arquivos em `supabase/migrations/` são executados à mão no SQL editor do Supabase. Escreva a migration como se ninguém fosse revisá-la e ela pudesse ser reexecutada — tudo `IF NOT EXISTS` / `OR REPLACE`.

**Testes usam `unittest.mock.patch` sobre o cliente Supabase**, nunca banco real (exceto os marcados `@pytest.mark.integration`). O padrão é: `patch("app.modulo.get_supabase", return_value=MagicMock())`. Siga o que já existe em `backend/tests/test_automation_triggers.py` e `test_automation_engine_actions.py`.

**Comandos:**
- backend: `cd backend && python -m pytest` (config em `backend/pytest.ini`, `asyncio_mode = auto` — testes async não precisam de decorator próprio, mas os existentes usam `@pytest.mark.asyncio` e você deve manter o padrão)
- frontend: `cd frontend && npm test` (vitest)
- `npm run lint` **já falha na master** (`react-hooks/set-state-in-effect` em ~15 hooks). Não é regressão sua; não tente consertar.

**Vocabulário que confunde:**
- `leads.stage` = **segmento** (`atacado`, `private_label`, `exportacao`, `consumo`, `secretaria`). NÃO é coluna do Kanban.
- `deals.stage_id` → `pipeline_stages` = **coluna do Kanban**. É o que as esteiras usam.
- `deals.stage` (texto) = coluna legada, ainda escrita por alguns caminhos antigos (ex.: `ja_chamado`).

---

## Estrutura de arquivos

**Criar:**
- `supabase/migrations/20260904_esteiras_vendedor.sql` — coluna, trigger, backfill, RPCs.
- `backend/app/campaigns/esteiras.py` — seed das 4 campanhas + leitura/escrita dos parâmetros da tela. Isolado de `system_cadence.py` de propósito: aquele é espelho read-only, este é editável.
- `backend/app/campaigns/esteiras_router.py` — os 2 endpoints da tela.
- `backend/tests/test_esteiras_*.py` — um arquivo por tema.
- `frontend/src/components/campaigns/esteiras-tab.tsx` — a aba.
- `frontend/src/app/api/automation/esteiras/route.ts` e `.../[key]/route.ts` — proxy.
- `scripts/create_esteira_templates.py` — submissão dos templates na Meta.

**Modificar:**
- `backend/app/automation/engine.py` — `audience` no gate, guarda de etapa, `alert_seller`, correção do deal em `mark_deal_*`.
- `backend/app/automation/triggers.py` — gatilho `deal_stage_stagnation`, `audience` nos gatilhos existentes.
- `backend/app/campaigns/service.py` — `create_enrollment` aceita `metadata`.
- `backend/app/main.py` — registra o router novo e roda o seed no lifespan.
- `frontend/src/app/(authenticated)/campanhas/page.tsx` — aba nova em `VALID_TABS`.
- `frontend/src/components/campaigns/cadence-flow/constants.ts` e `inspector.tsx` — o tipo de gatilho novo no builder.

---

## Ondas de execução (paralelismo)

Tarefas na mesma onda tocam arquivos disjuntos e podem rodar em paralelo. Não paralelize dentro de uma onda tarefas que compartilham arquivo.

- **Onda 1:** Task 1 (migration) ‖ Task 2+3+4+5 (todas em `engine.py`, um único agente, em ordem) ‖ Task 10 (script de templates)
- **Onda 2:** Task 6 (triggers.py) ‖ Task 7 (esteiras.py)
- **Onda 3:** Task 8 (router) ‖ Task 9 (frontend)

---

## Task 1: Migration e RPCs

**Files:**
- Create: `supabase/migrations/20260904_esteiras_vendedor.sql`

Não há teste automatizado — o repositório não tem harness de SQL. A validação é a revisão do arquivo e, no deploy, a execução manual.

- [ ] **Step 1: Escrever a migration**

```sql
-- supabase/migrations/20260904_esteiras_vendedor.sql
--
-- Esteiras do vendedor (itens 6, 7 e 8 da ata de 03/09/2026).
-- Spec: docs/superpowers/specs/2026-09-04-esteiras-vendedor-design.md
--
-- NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem, nao roda migration.
-- Executar a mao no SQL editor do Supabase ANTES do push.
--
-- PRE-REQUISITO: 20260825_quotes.sql precisa ter rodado antes. E ela quem cria a
-- etapa `proposta_enviada`, que e o gatilho da esteira E3. Sem ela a E3 nasce sem
-- etapa para observar.
--
-- Reexecutar e seguro: tudo IF NOT EXISTS / OR REPLACE, e o backfill do bloco 1 so
-- toca linha com entered_stage_at IS NULL.

-- ===========================================================================
-- 1. deals.entered_stage_at
-- ===========================================================================
-- Espelha leads.entered_stage_at (002_crm_enrichment.sql). Sem esta coluna nao ha
-- como saber ha quanto tempo um card esta parado numa coluna do Kanban — que e a
-- pergunta que as tres esteiras fazem.
--
-- Sem DEFAULT now() de proposito: com default, o ALTER carimbaria "agora" em todo
-- card existente e as esteiras so acordariam 15 dias depois de aplicada a migration.
-- O backfill abaixo usa updated_at, que e a melhor aproximacao da ultima
-- movimentacao real.
ALTER TABLE deals ADD COLUMN IF NOT EXISTS entered_stage_at timestamptz;

UPDATE deals
   SET entered_stage_at = COALESCE(updated_at, created_at)
 WHERE entered_stage_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_deals_entered_stage_at ON deals(entered_stage_at);

-- Observa as DUAS colunas de etapa: o Kanban usa stage_id, mas caminhos legados
-- ainda escrevem o texto em stage (ex.: 'ja_chamado'). Observar so uma deixaria
-- cards com data velha depois de terem sido movidos.
CREATE OR REPLACE FUNCTION update_deal_entered_stage_at()
RETURNS TRIGGER AS $$
BEGIN
    IF (NEW.stage_id IS DISTINCT FROM OLD.stage_id)
       OR (NEW.stage IS DISTINCT FROM OLD.stage) THEN
        NEW.entered_stage_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_deal_entered_stage_at ON deals;
CREATE TRIGGER trg_update_deal_entered_stage_at
    BEFORE UPDATE ON deals
    FOR EACH ROW EXECUTE FUNCTION update_deal_entered_stage_at();

-- ===========================================================================
-- 2. campaigns.audience
-- ===========================================================================
-- Quem a campanha pode tocar: leads da IA, leads sob controle humano, ou ambos.
--
-- O DEFAULT 'ia' e a rede de seguranca da mudanca inteira. A alternativa —
-- remover o filtro ai_enabled=TRUE dos gatilhos — faria TODA campanha ja existente
-- passar a enrolar lead sob controle humano, disparando automacao por cima de
-- conversa que um vendedor esta conduzindo. Com o default, nada muda para quem ja
-- existe; so quem marcar 'humano'/'ambos' opta por entrar.
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS audience text NOT NULL DEFAULT 'ia';

DO $$ BEGIN
  ALTER TABLE campaigns ADD CONSTRAINT campaigns_audience_check
    CHECK (audience IN ('ia', 'humano', 'ambos'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ===========================================================================
-- 3. campaign_enrollments.metadata
-- ===========================================================================
-- Guarda a "guarda de etapa" do enrollment:
--   {"guard": {"deal_id": "...", "stage_id": "...", "stage_key": "..."}}
-- Gravar no enrollment (em vez de reler o no de gatilho a cada tick) deixa a regra
-- de saida imune a edicao posterior da campanha: quem mexer no gatilho nao muda o
-- criterio de quem ja esta dentro.
ALTER TABLE campaign_enrollments ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}';

-- ===========================================================================
-- 4. RPC get_deals_stage_stagnant
-- ===========================================================================
-- Uma funcao cobre as tres esteiras. Em SQL porque a decisao depende de um
-- MAX(created_at) por conversa; via PostgREST isso seria N+1 sobre centenas de
-- cards a cada tick.
--
-- p_stage_days  = dias parado na ETAPA   (relogio do item 8: "proposta enviada conta 3 dias")
-- p_silence_days= dias sem MENSAGEM      (relogio dos itens 6 e 7: "sem conversa")
-- Os dois combinam por AND; 0 desliga o respectivo filtro.
CREATE OR REPLACE FUNCTION get_deals_stage_stagnant(
  p_stage_id      uuid,
  p_stage_key     text,
  p_pipeline_id   uuid,
  p_channel_id    uuid,
  p_stage_days    int,
  p_silence_days  int,
  p_last_speaker  text,
  p_audience      text,
  p_limit         int DEFAULT 20
)
RETURNS TABLE(lead_id uuid, deal_id uuid, stage_id uuid, last_speaker text, last_message_at timestamptz)
AS $$
  WITH candidatos AS (
    SELECT
      d.id            AS deal_id,
      d.lead_id       AS lead_id,
      d.stage_id      AS stage_id,
      d.entered_stage_at,
      d.created_at    AS deal_created_at,
      (
        SELECT m.created_at
          FROM messages m
          JOIN conversations c ON c.id = m.conversation_id
         WHERE c.lead_id = d.lead_id
           AND (p_channel_id IS NULL OR c.channel_id = p_channel_id)
         ORDER BY m.created_at DESC
         LIMIT 1
      ) AS ultima_msg_at,
      (
        SELECT CASE WHEN m.role = 'user' THEN 'lead' ELSE 'nos' END
          FROM messages m
          JOIN conversations c ON c.id = m.conversation_id
         WHERE c.lead_id = d.lead_id
           AND (p_channel_id IS NULL OR c.channel_id = p_channel_id)
         ORDER BY m.created_at DESC
         LIMIT 1
      ) AS falante
      FROM deals d
      JOIN leads l          ON l.id = d.lead_id
      JOIN pipeline_stages s ON s.id = d.stage_id
     WHERE
       -- etapa alvo: por id exato OU por key (vale em todo funil)
       (p_stage_id IS NULL OR d.stage_id = p_stage_id)
       AND (p_stage_key IS NULL OR s.key = p_stage_key)
       AND (p_pipeline_id IS NULL OR s.pipeline_id = p_pipeline_id)
       -- card tem de estar ABERTO. As tres keys porque
       -- 20260626_valeria_unify_stage_keys.sql deixou funis usando 'perdido'
       -- em vez de 'fechado_perdido'.
       AND (s.key IS NULL OR s.key NOT IN ('fechado_ganho', 'fechado_perdido', 'perdido'))
       -- publico
       AND (
         p_audience = 'ambos'
         OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
         OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
       )
  )
  SELECT
    c.lead_id,
    c.deal_id,
    c.stage_id,
    COALESCE(c.falante, 'nos') AS last_speaker,
    COALESCE(c.ultima_msg_at, c.deal_created_at) AS last_message_at
    FROM candidatos c
   WHERE
     (p_stage_days <= 0
       OR (c.entered_stage_at IS NOT NULL
           AND c.entered_stage_at <= now() - make_interval(days => p_stage_days)))
     -- Conversa SEM nenhuma mensagem conta como silencio: cai para deal.created_at.
     -- Sem esse COALESCE, card criado por importacao nunca entraria em esteira.
     AND (p_silence_days <= 0
       OR COALESCE(c.ultima_msg_at, c.deal_created_at) <= now() - make_interval(days => p_silence_days))
     AND (p_last_speaker = 'qualquer' OR COALESCE(c.falante, 'nos') = p_last_speaker)
   ORDER BY COALESCE(c.ultima_msg_at, c.deal_created_at) ASC
   LIMIT p_limit;
$$ LANGUAGE sql STABLE;

-- ===========================================================================
-- 5. audience nas RPCs existentes
-- ===========================================================================
-- DEFAULT 'ia' preserva a assinatura para qualquer chamador que nao passe o
-- argumento — inclusive o codigo em producao entre o SQL rodar e o deploy subir.
CREATE OR REPLACE FUNCTION get_leads_for_repurchase(
  cutoff_date TIMESTAMPTZ,
  p_env_tag TEXT,
  p_audience TEXT DEFAULT 'ia'
)
RETURNS TABLE(id UUID, phone TEXT) AS $$
  SELECT l.id, l.phone
  FROM leads l
  WHERE (
    p_audience = 'ambos'
    OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
    OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
  )
  AND EXISTS (SELECT 1 FROM sales s WHERE s.lead_id = l.id)
  AND (
    SELECT MAX(s2.sold_at) FROM sales s2 WHERE s2.lead_id = l.id
  ) <= cutoff_date;
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION get_leads_no_sale_in_stage(
  p_stage TEXT,
  cutoff_date TIMESTAMPTZ,
  p_env_tag TEXT,
  p_audience TEXT DEFAULT 'ia'
)
RETURNS TABLE(id UUID, phone TEXT) AS $$
  SELECT l.id, l.phone
  FROM leads l
  WHERE l.stage = p_stage
    AND (
      p_audience = 'ambos'
      OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
      OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
    )
    AND l.entered_stage_at IS NOT NULL
    AND l.entered_stage_at <= cutoff_date
    AND NOT EXISTS (
      SELECT 1 FROM sales s WHERE s.lead_id = l.id
    );
$$ LANGUAGE sql;

NOTIFY pgrst, 'reload schema';
```

- [ ] **Step 2: Conferir que não há erro de sintaxe óbvio**

Não há banco local. Leia o arquivo inteiro uma vez procurando por: vírgula faltando na lista de parâmetros, `$$` desbalanceado, e nome de coluna que não existe (confira `messages` tem `role`, `created_at`, `conversation_id`; `conversations` tem `lead_id`, `channel_id`).

Run: `grep -c '\$\$' supabase/migrations/20260904_esteiras_vendedor.sql`
Expected: um número **par** (cada função abre e fecha).

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260904_esteiras_vendedor.sql
git commit -m "feat(esteiras): migration - entered_stage_at, audience, metadata e RPC de estagnacao"
```

---

## Task 2: `mark_deal_*` opera no deal do enrollment

**Files:**
- Modify: `backend/app/automation/engine.py` (bloco `elif action_type in ("mark_deal_won", "mark_deal_lost", "move_deal_stage")`, hoje em ~`:493`)
- Test: `backend/tests/test_esteiras_deal_target.py`

Hoje a ação escolhe `order("created_at", desc=True).limit(1)` — o deal **mais recente do lead**, ignorando `enrollment["deal_id"]` que já está preenchido. Lead com card de reposição antigo e card novo teria o card errado marcado.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_esteiras_deal_target.py
"""mark_deal_* tem de agir no deal do ENROLLMENT, nao no mais recente do lead."""
from unittest.mock import MagicMock, patch

from app.automation.engine import _execute_action


def _sb_com_deal_mais_recente(deal_id="deal-mais-novo"):
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
       .order.return_value.limit.return_value.execute.return_value.data) = [{"id": deal_id}]
    return sb


def _updates(sb):
    return [c[0][0] for c in sb.table.return_value.update.call_args_list]


def _ids_atualizados(sb):
    return [c[0][1] for c in sb.table.return_value.update.return_value.eq.call_args_list]


class TestDealAlvo:
    def test_usa_deal_id_do_enrollment_quando_existe(self):
        sb = _sb_com_deal_mais_recente()
        enrollment = {"id": "e1", "lead_id": "lead1", "deal_id": "deal-da-esteira"}
        node = {"config": {"action_type": "mark_deal_lost", "stage_id": "stage-lost"}}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            _execute_action(enrollment, node, {"id": "lead1", "phone": "5511999"})
        assert "deal-da-esteira" in _ids_atualizados(sb)
        assert "deal-mais-novo" not in _ids_atualizados(sb)

    def test_cai_para_o_mais_recente_sem_deal_id(self):
        sb = _sb_com_deal_mais_recente()
        enrollment = {"id": "e1", "lead_id": "lead1"}
        node = {"config": {"action_type": "mark_deal_lost", "stage_id": "stage-lost"}}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            _execute_action(enrollment, node, {"id": "lead1", "phone": "5511999"})
        assert "deal-mais-novo" in _ids_atualizados(sb)


class TestLostReason:
    def test_grava_lost_reason_quando_configurado(self):
        sb = _sb_com_deal_mais_recente()
        enrollment = {"id": "e1", "lead_id": "lead1", "deal_id": "d9"}
        node = {"config": {
            "action_type": "mark_deal_lost",
            "stage_id": "stage-lost",
            "lost_reason": "sem resposta na esteira de reposicao",
        }}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            _execute_action(enrollment, node, {"id": "lead1", "phone": "5511999"})
        assert any(u.get("lost_reason") == "sem resposta na esteira de reposicao"
                   for u in _updates(sb))

    def test_nao_grava_lost_reason_em_mark_deal_won(self):
        sb = _sb_com_deal_mais_recente()
        enrollment = {"id": "e1", "lead_id": "lead1", "deal_id": "d9"}
        node = {"config": {
            "action_type": "mark_deal_won",
            "stage_id": "stage-won",
            "lost_reason": "nao deveria aparecer",
        }}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            _execute_action(enrollment, node, {"id": "lead1", "phone": "5511999"})
        assert all("lost_reason" not in u for u in _updates(sb))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_esteiras_deal_target.py -v`
Expected: FAIL — `test_usa_deal_id_do_enrollment_quando_existe` (o código atual sempre usa o mais recente) e os dois de `lost_reason`.

- [ ] **Step 3: Implementar**

Em `backend/app/automation/engine.py`, substitua o bloco inteiro:

```python
    elif action_type in ("mark_deal_won", "mark_deal_lost", "move_deal_stage"):
        stage_id = cfg.get("stage_id")
        if not stage_id:
            return
        # O deal do ENROLLMENT tem precedencia sobre "o mais recente do lead".
        # Um lead pode ter varios cards abertos (reposicao + oportunidade nova);
        # a esteira que disparou esta acao sabe qual e o dela.
        deal_id = enrollment.get("deal_id")
        if not deal_id:
            rows = (
                sb.table("deals")
                .select("id")
                .eq("lead_id", enrollment["lead_id"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
                .data
            )
            deal_id = rows[0]["id"] if rows else None
        if deal_id:
            update: dict = {"stage_id": stage_id}
            # lost_reason so faz sentido na perda; o campo existe na tabela desde
            # 009_deals.sql e nunca era preenchido por automacao.
            if action_type == "mark_deal_lost" and cfg.get("lost_reason"):
                update["lost_reason"] = cfg["lost_reason"]
            sb.table("deals").update(update).eq("id", deal_id).execute()
            # F9: dispara a conversao associada a etapa de destino (move_deal_stage /
            # mark_deal_won). Usa helper compartilhado com triggers._maybe_fire_stage_conversion.
            # Fail-soft — qualquer erro loga warning e NAO interrompe o tick.
            if action_type in ("mark_deal_won", "move_deal_stage"):
                try:
                    from app.campaigns.conversions import fire_conversion_for_deal_stage
                    fire_conversion_for_deal_stage(enrollment["lead_id"], deal_id)
                except Exception as exc:
                    logger.warning("[AUTOMATION] %s: falha ao disparar conversão: %s", action_type, exc)
```

- [ ] **Step 4: Rodar e ver passar (inclusive a suíte antiga)**

Run: `cd backend && python -m pytest tests/test_esteiras_deal_target.py tests/test_automation_engine_actions.py -v`
Expected: PASS em tudo. `test_automation_engine_actions.py` não passa `deal_id` no enrollment, então continua exercitando o fallback.

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/engine.py backend/tests/test_esteiras_deal_target.py
git commit -m "fix(automation): mark_deal_* age no deal do enrollment e grava lost_reason"
```

---

## Task 3: Ação `alert_seller`

**Files:**
- Modify: `backend/app/automation/engine.py`
- Test: `backend/tests/test_esteiras_alert_seller.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_esteiras_alert_seller.py
"""Acao alert_seller: alerta de sistema + nota no card, fail-soft."""
from unittest.mock import MagicMock, patch

from app.automation.engine import _execute_action


NODE = {"config": {
    "action_type": "alert_seller",
    "severity": "warning",
    "title": "Proposta esfriando",
    "message_template": "{{nome}} nao respondeu a proposta.",
}}
ENROLLMENT = {"id": "e1", "lead_id": "lead1", "deal_id": "d1", "campaign_id": "c1"}
LEAD = {"id": "lead1", "phone": "5511999", "name": "Marcella"}


def test_cria_alerta_com_metadata():
    sb = MagicMock()
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert") as mock_alert,
    ):
        _execute_action(ENROLLMENT, NODE, LEAD)
    mock_alert.assert_called_once()
    kwargs = mock_alert.call_args.kwargs
    assert kwargs["type"] == "esteira_vendedor"
    assert kwargs["severity"] == "warning"
    assert kwargs["metadata"]["lead_id"] == "lead1"
    assert kwargs["metadata"]["deal_id"] == "d1"
    assert kwargs["metadata"]["campaign_id"] == "c1"


def test_substitui_variaveis_na_mensagem():
    sb = MagicMock()
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert") as mock_alert,
    ):
        _execute_action(ENROLLMENT, NODE, LEAD)
    assert "Marcella" in mock_alert.call_args.kwargs["message"]


def test_grava_nota_no_lead():
    sb = MagicMock()
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert"),
    ):
        _execute_action(ENROLLMENT, NODE, LEAD)
    sb.table.assert_any_call("lead_notes")


def test_fail_soft_quando_alerta_explode():
    sb = MagicMock()
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert", side_effect=RuntimeError("boom")),
    ):
        _execute_action(ENROLLMENT, NODE, LEAD)  # nao levanta


def test_severity_default_e_warning():
    sb = MagicMock()
    node = {"config": {"action_type": "alert_seller", "title": "x", "message_template": "y"}}
    with (
        patch("app.automation.engine.get_supabase", return_value=sb),
        patch("app.alerts.service.create_system_alert") as mock_alert,
    ):
        _execute_action(ENROLLMENT, node, LEAD)
    assert mock_alert.call_args.kwargs["severity"] == "warning"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_esteiras_alert_seller.py -v`
Expected: FAIL — `create_system_alert` nunca é chamado (o `action_type` cai no fim da cadeia de `elif` sem fazer nada).

- [ ] **Step 3: Implementar**

Em `_execute_action`, adicione antes do `elif action_type == "assign_round_robin":`:

```python
    elif action_type == "alert_seller":
        # Avisa o dono do card que a esteira terminou sem resposta. O watchdog ja
        # detecta silencio pos-handoff em 20min (check handoff_sla_breach), mas so
        # em alerta interno; aqui o alerta nasce colado no card, com o historico.
        # Fail-soft absoluto: alerta que falha nao pode derrubar o tick da esteira.
        from app.alerts.service import create_system_alert
        titulo = substitute_variables(cfg.get("title") or "Esteira encerrada", lead, enrollment)
        corpo = substitute_variables(cfg.get("message_template") or "", lead, enrollment)
        try:
            create_system_alert(
                type="esteira_vendedor",
                title=titulo,
                message=corpo,
                severity=cfg.get("severity") or "warning",
                metadata={
                    "lead_id": enrollment.get("lead_id"),
                    "deal_id": enrollment.get("deal_id"),
                    "campaign_id": enrollment.get("campaign_id"),
                    "phone": lead.get("phone"),
                },
            )
        except Exception as exc:
            logger.warning("[AUTOMATION] alert_seller: falha ao criar alerta: %s", exc)
        try:
            sb.table("lead_notes").insert({
                "lead_id": enrollment["lead_id"],
                "content": f"[esteira] {titulo} — {corpo}",
            }).execute()
        except Exception as exc:
            logger.warning("[AUTOMATION] alert_seller: falha ao gravar nota: %s", exc)
```

Nota: o teste faz `patch("app.alerts.service.create_system_alert")` e o código importa dentro da função — por isso o patch pega. Não mova o import para o topo do módulo.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_esteiras_alert_seller.py -v`
Expected: PASS (5 testes).

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/engine.py backend/tests/test_esteiras_alert_seller.py
git commit -m "feat(automation): acao alert_seller"
```

---

## Task 4: Público (`audience`)

**Files:**
- Modify: `backend/app/automation/engine.py` (helper novo + gate de `_process_one` + `get_due_enrollments`)
- Modify: `backend/app/automation/triggers.py` (gatilhos `no_message`, `stage_stagnation`, `repurchase_window`, `no_sale_in_stage`)
- Test: `backend/tests/test_esteiras_audience.py`

**Achado importante:** `_process_one` tem hoje `if not lead.get("ai_enabled", True): return`. Mesmo enrolando o lead, a execução seria bloqueada. Sem mexer aqui, nada funciona.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_esteiras_audience.py
"""campaigns.audience libera (ou nao) o motor sobre lead com ai_enabled=False.

O teste de REGRESSAO deste arquivo (audience ausente => comportamento de hoje) e a
rede de seguranca da mudanca inteira: campanha antiga nao pode passar a disparar
por cima de conversa conduzida por vendedor.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.automation.engine import _audience_allows, _process_one


class TestAudienceAllows:
    def test_ia_aceita_lead_com_ia_ligada(self):
        assert _audience_allows("ia", {"ai_enabled": True}) is True

    def test_ia_recusa_lead_sob_controle_humano(self):
        assert _audience_allows("ia", {"ai_enabled": False}) is False

    def test_humano_aceita_so_controle_humano(self):
        assert _audience_allows("humano", {"ai_enabled": False}) is True
        assert _audience_allows("humano", {"ai_enabled": True}) is False

    def test_ambos_aceita_os_dois(self):
        assert _audience_allows("ambos", {"ai_enabled": True}) is True
        assert _audience_allows("ambos", {"ai_enabled": False}) is True

    def test_audience_ausente_ou_lixo_cai_em_ia(self):
        assert _audience_allows(None, {"ai_enabled": True}) is True
        assert _audience_allows(None, {"ai_enabled": False}) is False
        assert _audience_allows("banana", {"ai_enabled": False}) is False

    def test_lead_sem_a_chave_conta_como_ia_ligada(self):
        # Default historico: ausencia de ai_enabled sempre significou True.
        assert _audience_allows("ia", {}) is True


@pytest.mark.asyncio
class TestProcessOneGate:
    async def _roda(self, audience, ai_enabled):
        enrollment = {
            "id": "e1",
            "lead_id": "lead1",
            "step_count": 0,
            "leads": {"id": "lead1", "phone": "5511999", "ai_enabled": ai_enabled},
            "campaigns": {"id": "c1", "status": "active", "audience": audience, "channel_id": "ch1"},
            "campaign_nodes": {"id": "n1", "type": "end", "config": {}},
        }
        with (
            patch("app.automation.engine._conversation_followup_disabled", return_value=False),
            patch("app.automation.engine._complete") as mock_complete,
            patch("app.automation.engine._log_exec"),
        ):
            from datetime import datetime, timezone
            await _process_one(enrollment, datetime.now(timezone.utc))
        return mock_complete

    async def test_regressao_campanha_sem_audience_nao_toca_lead_humano(self):
        mock_complete = await self._roda(None, False)
        mock_complete.assert_not_called()

    async def test_campanha_ia_nao_toca_lead_humano(self):
        mock_complete = await self._roda("ia", False)
        mock_complete.assert_not_called()

    async def test_campanha_humano_processa_lead_humano(self):
        mock_complete = await self._roda("humano", False)
        mock_complete.assert_called_once()

    async def test_campanha_humano_nao_toca_lead_da_ia(self):
        mock_complete = await self._roda("humano", True)
        mock_complete.assert_not_called()

    async def test_campanha_ambos_processa_os_dois(self):
        assert (await self._roda("ambos", False)).call_count == 1
        assert (await self._roda("ambos", True)).call_count == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_esteiras_audience.py -v`
Expected: FAIL com `ImportError: cannot import name '_audience_allows'`.

- [ ] **Step 3: Implementar em `engine.py`**

Adicione o helper logo depois de `_conversation_followup_disabled`:

```python
# Publico que a campanha pode tocar. 'ia' = so lead com a IA ligada (o comportamento
# historico e o DEFAULT da coluna); 'humano' = so lead sob controle humano (pos-handoff,
# que e onde as esteiras do vendedor vivem); 'ambos' = sem filtro.
# Valor ausente ou desconhecido cai em 'ia' — nunca em 'ambos': o modo mais permissivo
# jamais pode ser resultado de dado faltando.
_AUDIENCES = ("ia", "humano", "ambos")


def _audience_allows(audience: str | None, lead: dict) -> bool:
    """True se a campanha com este `audience` pode agir sobre este lead. Funcao PURA."""
    modo = audience if audience in _AUDIENCES else "ia"
    if modo == "ambos":
        return True
    ai_ligada = bool(lead.get("ai_enabled", True))
    return ai_ligada if modo == "ia" else not ai_ligada
```

Em `_process_one`, troque:

```python
    if not lead.get("ai_enabled", True):
        return
```

por:

```python
    # Publico da campanha (audience). Antes desta linha o motor recusava TODO lead com
    # ai_enabled=False, o que tornava impossivel automatizar o funil do vendedor humano.
    if not _audience_allows(campaign.get("audience"), lead):
        return
```

Em `get_due_enrollments`, acrescente `audience` à lista de colunas de `campaigns!inner(...)`:

```python
            "campaigns!inner(id, name, status, priority, frequency_cap, send_start_hour, send_end_hour, channel_id, audience)"
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_esteiras_audience.py -v`
Expected: PASS.

- [ ] **Step 5: Propagar `audience` para os gatilhos de polling**

Em `triggers.py`, `get_campaigns_with_trigger_type` já traz o nó com `campaigns` embutido — mas só seleciona `id, status, channel_id`. Em `campaigns/service.py::get_campaigns_with_trigger_type`, troque o select:

```python
        .select("*, campaigns!inner(id, status, channel_id, audience)")
```

e no loop de achatamento, adicione:

```python
            n["audience"] = (n.get("campaigns") or {}).get("audience") or "ia"
```

Em `triggers.py::check_polling_triggers`, use o valor:

```python
    # ── no_message ────────────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("no_message"):
        cfg = tn.get("config") or {}
        days, stage_filter = cfg.get("days", 30), cfg.get("stage_filter")
        cutoff = (now - timedelta(days=days)).isoformat()
        q = sb.table("leads").select("id, phone").lte("last_msg_at", cutoff)
        q = _apply_audience(q, tn.get("audience"))
        if stage_filter:
            q = q.eq("stage", stage_filter)
```

e o mesmo em `stage_stagnation` (trocando `.eq("ai_enabled", True)` por `_apply_audience`). Nas duas RPCs, passe o parâmetro novo:

```python
        results = sb.rpc("get_leads_for_repurchase", {
            "cutoff_date": cutoff, "p_env_tag": env_tag, "p_audience": tn.get("audience") or "ia",
        }).execute().data or []
```

```python
        results = sb.rpc("get_leads_no_sale_in_stage", {
            "p_stage": stage, "cutoff_date": cutoff, "p_env_tag": env_tag,
            "p_audience": tn.get("audience") or "ia",
        }).execute().data or []
```

Helper novo no topo de `triggers.py`, depois de `_get_env_tag`:

```python
def _apply_audience(query, audience: str | None):
    """Aplica o filtro de ai_enabled correspondente ao publico da campanha.

    Espelha engine._audience_allows no lado da CONSULTA. Valor ausente/desconhecido
    cai em 'ia' — o comportamento historico — nunca em 'ambos'.
    """
    modo = audience if audience in ("ia", "humano", "ambos") else "ia"
    if modo == "ambos":
        return query
    return query.eq("ai_enabled", modo == "ia")
```

- [ ] **Step 6: Teste do helper de consulta**

Acrescente a `tests/test_esteiras_audience.py`:

```python
class TestApplyAudience:
    def test_ia_filtra_true(self):
        from app.automation.triggers import _apply_audience
        q = MagicMock()
        _apply_audience(q, "ia")
        q.eq.assert_called_once_with("ai_enabled", True)

    def test_humano_filtra_false(self):
        from app.automation.triggers import _apply_audience
        q = MagicMock()
        _apply_audience(q, "humano")
        q.eq.assert_called_once_with("ai_enabled", False)

    def test_ambos_nao_filtra(self):
        from app.automation.triggers import _apply_audience
        q = MagicMock()
        assert _apply_audience(q, "ambos") is q
        q.eq.assert_not_called()

    def test_ausente_cai_em_ia(self):
        from app.automation.triggers import _apply_audience
        q = MagicMock()
        _apply_audience(q, None)
        q.eq.assert_called_once_with("ai_enabled", True)
```

Run: `cd backend && python -m pytest tests/test_esteiras_audience.py tests/test_automation_triggers.py tests/test_automation_engine.py -v`
Expected: PASS em tudo.

- [ ] **Step 7: Commit**

```bash
git add backend/app/automation/engine.py backend/app/automation/triggers.py backend/app/campaigns/service.py backend/tests/test_esteiras_audience.py
git commit -m "feat(automation): campaigns.audience libera o motor sobre lead sob controle humano"
```

---

## Task 5: Guarda de etapa

**Files:**
- Modify: `backend/app/campaigns/service.py` (`create_enrollment` aceita `metadata`)
- Modify: `backend/app/automation/engine.py` (`_process_one`, `get_due_enrollments`)
- Test: `backend/tests/test_esteiras_guarda_etapa.py`

Implementa os dois "roda até" da ata: "até entrar em proposta" (E2) e "até fechado/perdido" (E3). O card sair da coluna é o evento que encerra a esteira.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_esteiras_guarda_etapa.py
"""Guarda de etapa: o enrollment morre quando o card sai da coluna de gatilho."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.automation.engine import _guard_broken, _process_one


def _sb_com_deal_em(stage_id):
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
       .limit.return_value.execute.return_value.data) = [{"id": "d1", "stage_id": stage_id}]
    return sb


class TestGuardBroken:
    def test_sem_guarda_nunca_quebra(self):
        assert _guard_broken({"metadata": {}}) is False
        assert _guard_broken({}) is False

    def test_card_na_mesma_etapa_nao_quebra(self):
        enr = {"metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}}}
        with patch("app.automation.engine.get_supabase", return_value=_sb_com_deal_em("s1")):
            assert _guard_broken(enr) is False

    def test_card_mudou_de_etapa_quebra(self):
        enr = {"metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}}}
        with patch("app.automation.engine.get_supabase", return_value=_sb_com_deal_em("s2")):
            assert _guard_broken(enr) is True

    def test_deal_apagado_quebra(self):
        sb = MagicMock()
        (sb.table.return_value.select.return_value.eq.return_value
           .limit.return_value.execute.return_value.data) = []
        enr = {"metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}}}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            assert _guard_broken(enr) is True

    def test_erro_de_banco_nao_quebra(self):
        # Fail-open: erro de leitura nao pode matar esteira legitima.
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("boom")
        enr = {"metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}}}
        with patch("app.automation.engine.get_supabase", return_value=sb):
            assert _guard_broken(enr) is False


@pytest.mark.asyncio
async def test_process_one_cancela_quando_a_guarda_quebra():
    enrollment = {
        "id": "e1",
        "lead_id": "lead1",
        "deal_id": "d1",
        "step_count": 0,
        "metadata": {"guard": {"deal_id": "d1", "stage_id": "s1"}},
        "leads": {"id": "lead1", "phone": "5511999", "ai_enabled": False},
        "campaigns": {"id": "c1", "status": "active", "audience": "humano", "channel_id": "ch1"},
        "campaign_nodes": {"id": "n1", "type": "end", "config": {}},
    }
    with (
        patch("app.automation.engine._conversation_followup_disabled", return_value=False),
        patch("app.automation.engine._guard_broken", return_value=True),
        patch("app.automation.engine._update") as mock_update,
        patch("app.automation.engine._complete") as mock_complete,
        patch("app.automation.engine._log_exec"),
    ):
        await _process_one(enrollment, datetime.now(timezone.utc))
    mock_complete.assert_not_called()
    assert mock_update.call_args.kwargs["status"] == "cancelled"


def test_create_enrollment_grava_metadata():
    from app.campaigns import service
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "e1"}]
    with (
        patch("app.campaigns.service.get_supabase", return_value=sb),
        patch("app.campaigns.service.emit_event"),
    ):
        service.create_enrollment(
            "c1", "lead1", "n1", datetime.now(timezone.utc),
            deal_id="d1", metadata={"guard": {"deal_id": "d1", "stage_id": "s1"}},
        )
    payload = sb.table.return_value.insert.call_args[0][0]
    assert payload["metadata"]["guard"]["stage_id"] == "s1"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_esteiras_guarda_etapa.py -v`
Expected: FAIL com `ImportError: cannot import name '_guard_broken'`.

- [ ] **Step 3: `create_enrollment` aceita metadata**

Em `backend/app/campaigns/service.py`:

```python
def create_enrollment(campaign_id: str, lead_id: str, current_node_id: str, next_execute_at: datetime, deal_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    sb = get_supabase()
    try:
        row = sb.table("campaign_enrollments").insert({
            "campaign_id": campaign_id,
            "lead_id": lead_id,
            "deal_id": deal_id,
            "current_node_id": current_node_id,
            "next_execute_at": next_execute_at.isoformat(),
            "env_tag": _ENV_TAG,
            "metadata": metadata or {},
        }).execute().data[0]
```

O resto da função fica igual.

- [ ] **Step 4: Implementar a guarda em `engine.py`**

Depois de `_audience_allows`:

```python
def _guard_broken(enrollment: dict) -> bool:
    """True se o card saiu da etapa que originou este enrollment.

    E o criterio de saida das esteiras do vendedor: "roda ate entrar em proposta" (E2)
    e "roda ate fechado/perdido" (E3) sao, os dois, "roda ate o card mudar de coluna".

    A guarda vem de `enrollment.metadata.guard` — gravada na criacao, nao relida do no
    de gatilho — para que editar a campanha depois nao mude a regra de quem ja esta
    dentro. FAIL-OPEN: erro de leitura devolve False; matar esteira legitima por causa
    de um timeout de banco seria pior que um toque a mais.
    """
    guard = (enrollment.get("metadata") or {}).get("guard") or {}
    deal_id, stage_id = guard.get("deal_id"), guard.get("stage_id")
    if not deal_id or not stage_id:
        return False
    try:
        rows = (
            get_supabase().table("deals").select("id, stage_id")
            .eq("id", deal_id).limit(1).execute().data
        )
    except Exception as exc:
        logger.warning("[AUTOMATION] guarda de etapa: falha ao reler deal %s: %s", deal_id, exc)
        return False
    if not rows:
        return True  # card apagado — nao ha mais o que trabalhar
    return rows[0].get("stage_id") != stage_id
```

Em `_process_one`, logo depois do gate de `_audience_allows` e antes do gate de
`_conversation_followup_disabled`:

```python
    if _guard_broken(enrollment):
        logger.info(
            "[AUTOMATION] enrollment=%s — card saiu da etapa de gatilho, encerrando",
            enrollment["id"],
        )
        _update(enrollment["id"], status="cancelled", last_error="deal_left_stage", claimed_at=None)
        _log_exec(enrollment, node, "cancelled", "card saiu da etapa de gatilho")
        return
```

Em `get_due_enrollments`, o `select("*, ...")` já traz `metadata` (é `*`) — não precisa mudar nada.

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_esteiras_guarda_etapa.py tests/test_cadence_hardening_enroll.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/automation/engine.py backend/app/campaigns/service.py backend/tests/test_esteiras_guarda_etapa.py
git commit -m "feat(automation): guarda de etapa encerra a esteira quando o card muda de coluna"
```

---

## Task 6: Gatilho `deal_stage_stagnation`

**Files:**
- Modify: `backend/app/automation/triggers.py`
- Modify: `frontend/src/components/campaigns/cadence-flow/constants.ts` (rótulo e ícone)
- Modify: `frontend/src/components/campaigns/cadence-flow/inspector.tsx` (opção no select)
- Test: `backend/tests/test_esteiras_trigger.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_esteiras_trigger.py
"""Gatilho deal_stage_stagnation: card parado na coluna do Kanban."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.automation.triggers import check_polling_triggers

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)

TRIGGER_NODE = {
    "campaign_id": "camp-e2",
    "next_node_id": "node-1",
    "channel_id": "ch-joao",
    "audience": "humano",
    "config": {
        "trigger_type": "deal_stage_stagnation",
        "stage_id": "stage-ja-chamado",
        "pipeline_id": "pipe-joao",
        "silence_days": 15,
        "stage_days": 0,
        "last_speaker": "qualquer",
    },
}

LINHA = {
    "lead_id": "lead1",
    "deal_id": "deal1",
    "stage_id": "stage-ja-chamado",
    "last_speaker": "nos",
    "last_message_at": "2026-08-01T12:00:00+00:00",
}


def _patches(rpc_rows, enrolled=False, disabled=False, blacklisted=False):
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = rpc_rows
    return (
        patch("app.automation.triggers.get_supabase", return_value=sb),
        patch("app.automation.triggers.get_campaigns_with_trigger_type",
              side_effect=lambda t: [TRIGGER_NODE] if t == "deal_stage_stagnation" else []),
        patch("app.automation.triggers.is_already_enrolled", return_value=enrolled),
        patch("app.automation.triggers._engine._conversation_followup_disabled", return_value=disabled),
        patch("app.automation.triggers.is_lead_blacklisted", return_value=blacklisted),
    ), sb


@pytest.mark.asyncio
async def test_enrolla_com_deal_id_e_guarda():
    ps, sb = _patches([LINHA])
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment") as mock_enroll:
        await check_polling_triggers(NOW)
    mock_enroll.assert_called_once()
    kwargs = mock_enroll.call_args.kwargs
    assert kwargs["deal_id"] == "deal1"
    assert kwargs["metadata"]["guard"] == {
        "deal_id": "deal1", "stage_id": "stage-ja-chamado", "stage_key": None,
    }


@pytest.mark.asyncio
async def test_passa_os_parametros_certos_para_a_rpc():
    ps, sb = _patches([])
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment"):
        await check_polling_triggers(NOW)
    nome, args = sb.rpc.call_args[0]
    assert nome == "get_deals_stage_stagnant"
    assert args["p_stage_id"] == "stage-ja-chamado"
    assert args["p_pipeline_id"] == "pipe-joao"
    assert args["p_channel_id"] == "ch-joao"
    assert args["p_silence_days"] == 15
    assert args["p_stage_days"] == 0
    assert args["p_last_speaker"] == "qualquer"
    assert args["p_audience"] == "humano"


@pytest.mark.asyncio
async def test_pula_ja_enrolado():
    ps, sb = _patches([LINHA], enrolled=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment") as mock_enroll:
        await check_polling_triggers(NOW)
    mock_enroll.assert_not_called()


@pytest.mark.asyncio
async def test_pula_conversa_finalizada():
    ps, sb = _patches([LINHA], disabled=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment") as mock_enroll:
        await check_polling_triggers(NOW)
    mock_enroll.assert_not_called()


@pytest.mark.asyncio
async def test_pula_blacklist():
    """A esteira de reposicao varre a base inteira — e onde mora quem pediu para
    nao ser incomodado. Os gatilhos de polling atuais nao tem essa guarda."""
    ps, sb = _patches([LINHA], blacklisted=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment") as mock_enroll:
        await check_polling_triggers(NOW)
    mock_enroll.assert_not_called()


@pytest.mark.asyncio
async def test_sem_next_node_nao_enrolla():
    node = dict(TRIGGER_NODE, next_node_id=None)
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = [LINHA]
    with (
        patch("app.automation.triggers.get_supabase", return_value=sb),
        patch("app.automation.triggers.get_campaigns_with_trigger_type",
              side_effect=lambda t: [node] if t == "deal_stage_stagnation" else []),
        patch("app.automation.triggers.is_already_enrolled", return_value=False),
        patch("app.automation.triggers._engine._conversation_followup_disabled", return_value=False),
        patch("app.automation.triggers.is_lead_blacklisted", return_value=False),
        patch("app.automation.triggers.create_enrollment") as mock_enroll,
    ):
        await check_polling_triggers(NOW)
    mock_enroll.assert_not_called()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_esteiras_trigger.py -v`
Expected: FAIL — `is_lead_blacklisted` não existe em `triggers.py` e a RPC nunca é chamada.

- [ ] **Step 3: Implementar**

No topo de `triggers.py`, junto dos outros imports:

```python
from app.broadcast.worker import is_lead_blacklisted
```

Se esse import criar ciclo, importe dentro da função — confirme rodando os testes.

No fim de `check_polling_triggers`, antes do `_safe_enroll` final:

```python
    # ── deal_stage_stagnation ─────────────────────────────────────────────────
    # Card parado numa COLUNA DO KANBAN (deals.stage_id), nao no segmento do lead.
    # E o gatilho das tres esteiras do vendedor; a RPC resolve etapa, silencio,
    # falante e publico numa consulta so (ver 20260904_esteiras_vendedor.sql).
    for tn in get_campaigns_with_trigger_type("deal_stage_stagnation"):
        cfg = tn.get("config") or {}
        if not tn.get("next_node_id"):
            continue
        args = {
            "p_stage_id": cfg.get("stage_id"),
            "p_stage_key": cfg.get("stage_key"),
            "p_pipeline_id": cfg.get("pipeline_id"),
            "p_channel_id": tn.get("channel_id"),
            "p_stage_days": int(cfg.get("stage_days") or 0),
            "p_silence_days": int(cfg.get("silence_days") or 0),
            "p_last_speaker": cfg.get("last_speaker") or "qualquer",
            "p_audience": tn.get("audience") or "ia",
            "p_limit": int(cfg.get("limit") or 20),
        }
        try:
            linhas = sb.rpc("get_deals_stage_stagnant", args).execute().data or []
        except Exception as exc:
            logger.error("[AUTOMATION] deal_stage_stagnation: RPC falhou: %s", exc)
            continue
        for linha in linhas:
            lead_id = linha["lead_id"]
            if is_already_enrolled(tn["campaign_id"], lead_id):
                continue
            if _engine._conversation_followup_disabled(lead_id, tn.get("channel_id")):
                continue
            # Guarda que os gatilhos antigos nao tem: a esteira de reposicao varre a
            # base inteira e e exatamente onde esta quem ja pediu para nao receber mais.
            if is_lead_blacklisted(lead_id):
                logger.info("[AUTOMATION] deal_stage_stagnation: lead %s na blacklist — skip", lead_id)
                continue
            try:
                create_enrollment(
                    campaign_id=tn["campaign_id"],
                    lead_id=lead_id,
                    current_node_id=tn["next_node_id"],
                    next_execute_at=now,
                    deal_id=linha.get("deal_id"),
                    metadata={"guard": {
                        "deal_id": linha.get("deal_id"),
                        "stage_id": linha.get("stage_id"),
                        "stage_key": cfg.get("stage_key"),
                    }},
                )
                logger.info("[AUTOMATION] Enrolled %s via deal_stage_stagnation", lead_id)
            except Exception as exc:
                logger.warning("[AUTOMATION] deal_stage_stagnation enroll falhou p/ %s: %s", lead_id, exc)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_esteiras_trigger.py tests/test_automation_triggers.py -v`
Expected: PASS.

- [ ] **Step 5: Registrar o tipo no builder (frontend)**

Em `frontend/src/components/campaigns/cadence-flow/constants.ts`, no mapa de rótulos (linha ~44) adicione `deal_stage_stagnation: "Card parado no funil",` e no mapa de ícones (linha ~66) `deal_stage_stagnation: "📋",`. Na lista de nós arrastáveis (linha ~113), acrescente:

```ts
  { type: "trigger", subtype: "deal_stage_stagnation", icon: "📋", label: "Card parado no funil", desc: "Parado X dias numa coluna" },
```

Em `inspector.tsx`, junto dos outros `<option>` de trigger (linha ~113):

```tsx
                <option value="deal_stage_stagnation">Card parado no funil</option>
```

- [ ] **Step 6: Rodar os testes do frontend**

Run: `cd frontend && npm test`
Expected: PASS. Se `describe-node.test.ts` ou `helpers.test.ts` quebrarem por causa do subtype novo, adicione o caso correspondente em `describe-node.ts` (`case "deal_stage_stagnation": return \`Card parado ha ${cfg.silence_days ?? cfg.stage_days ?? 0} dias\`;`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/automation/triggers.py backend/tests/test_esteiras_trigger.py frontend/src/components/campaigns/cadence-flow/
git commit -m "feat(automation): gatilho deal_stage_stagnation"
```

---

## Task 7: Seed das esteiras

**Files:**
- Create: `backend/app/campaigns/esteiras.py`
- Modify: `backend/app/main.py` (chamar o seed no lifespan)
- Test: `backend/tests/test_esteiras_seed.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_esteiras_seed.py
"""Seed das 4 campanhas de esteira: idempotente e NAO destrutivo."""
from unittest.mock import MagicMock, patch

from app.campaigns import esteiras


def test_quatro_esteiras_com_ids_deterministicos():
    ids = {e["key"]: e["campaign_id"] for e in esteiras.ESTEIRAS}
    assert set(ids) == {"novo_sem_resposta", "novo_reengajamento", "reposicao", "proposta"}
    # ids estaveis entre execucoes
    assert ids == {e["key"]: e["campaign_id"] for e in esteiras.ESTEIRAS}
    assert len(set(ids.values())) == 4


def test_todas_nascem_em_draft():
    for e in esteiras.ESTEIRAS:
        assert e["status"] == "draft"


def test_todas_com_audience_humano():
    """As esteiras existem justamente para o lead pos-handoff (ai_enabled=False)."""
    for e in esteiras.ESTEIRAS:
        assert e["audience"] == "humano"


def test_prioridade_proposta_maior_que_novo_maior_que_reposicao():
    p = {e["key"]: e["priority"] for e in esteiras.ESTEIRAS}
    assert p["proposta"] > p["novo_sem_resposta"] == p["novo_reengajamento"] > p["reposicao"]


def test_frequency_cap_um():
    for e in esteiras.ESTEIRAS:
        assert e["frequency_cap"] == 1


def test_envios_cancelam_no_reply():
    """on_reply='pause' deixaria o lead inelegivel para sempre (enrollment pausado
    conta como ativo em is_already_enrolled e nunca e retomado)."""
    for e in esteiras.ESTEIRAS:
        for no in e["nodes"]:
            if no["type"] == "send":
                assert no["config"]["on_reply"] == "cancel"


def test_seed_nao_sobrescreve_campanha_existente():
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": e["campaign_id"]} for e in esteiras.ESTEIRAS
    ]
    with patch("app.campaigns.esteiras.get_supabase", return_value=sb):
        esteiras.seed_esteiras()
    sb.table.return_value.insert.assert_not_called()
    sb.table.return_value.update.assert_not_called()


def test_seed_cria_o_que_falta():
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = []
    with patch("app.campaigns.esteiras.get_supabase", return_value=sb):
        esteiras.seed_esteiras()
    assert sb.table.return_value.insert.call_count >= 4


def test_seed_fail_soft():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("boom")
    with patch("app.campaigns.esteiras.get_supabase", return_value=sb):
        esteiras.seed_esteiras()  # nao levanta


def test_reposicao_tem_tres_toques_e_termina_em_mark_deal_lost():
    e = next(x for x in esteiras.ESTEIRAS if x["key"] == "reposicao")
    assert sum(1 for n in e["nodes"] if n["type"] == "send") == 3
    acoes = [n["config"].get("action_type") for n in e["nodes"] if n["type"] == "action"]
    assert "mark_deal_lost" in acoes


def test_proposta_tem_dois_toques_e_termina_em_alert_seller():
    e = next(x for x in esteiras.ESTEIRAS if x["key"] == "proposta")
    assert sum(1 for n in e["nodes"] if n["type"] == "send") == 2
    acoes = [n["config"].get("action_type") for n in e["nodes"] if n["type"] == "action"]
    assert "alert_seller" in acoes
    assert "mark_deal_lost" not in acoes  # proposta nunca vira perdido sozinha


def test_esteira_novo_sem_resposta_filtra_falante_lead():
    e = next(x for x in esteiras.ESTEIRAS if x["key"] == "novo_sem_resposta")
    trigger = next(n for n in e["nodes"] if n["type"] == "trigger")
    assert trigger["config"]["last_speaker"] == "lead"


def test_esteira_novo_reengajamento_filtra_falante_nos():
    e = next(x for x in esteiras.ESTEIRAS if x["key"] == "novo_reengajamento")
    trigger = next(n for n in e["nodes"] if n["type"] == "trigger")
    assert trigger["config"]["last_speaker"] == "nos"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_esteiras_seed.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.campaigns.esteiras'`.

- [ ] **Step 3: Implementar `esteiras.py`**

```python
"""Seed das esteiras do vendedor (itens 6, 7 e 8 da ata de 03/09/2026).

Spec: docs/superpowers/specs/2026-09-04-esteiras-vendedor-design.md

DIFERENCA ESSENCIAL para `system_cadence.py`: aquele modulo e um ESPELHO
read-only, re-sincronizado a cada deploy e desfazendo edicao manual. Este cria a
campanha UMA VEZ e nunca mais toca — porque a decisao do dono e que o Arthur e o
Joao editem prazo e template pela tela, sem deploy. O seed e idempotente por
EXISTENCIA do id, nao por conteudo.

As campanhas nascem `draft` (desligadas) de proposito: os templates da Meta ainda
podem estar em aprovacao, e ligar a esteira de reposicao num banco com meses de
cards parados torna elegivel, de uma vez, todo card com mais de 15 dias.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.campaigns.service import _ENV_TAG
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_NS = "canastra://system/esteiras-vendedor"


def _cid(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_NS}/{key}"))


def _nid(key: str, no: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{_NS}/{key}/{no}"))


# O encadeamento dos nos e POSICIONAL: a lista `nodes` de cada esteira esta em ordem
# linear e `seed_esteiras` liga cada no ao seguinte. Nao existe campo "next" nos
# helpers de proposito — duas fontes de verdade para a mesma aresta seria bug garantido.
def _trigger(key: str, *, stage_days: int, silence_days: int, last_speaker: str,
             stage_key: str | None = None) -> dict[str, Any]:
    return {
        "id": _nid(key, "trigger"), "type": "trigger",
        "config": {
            "trigger_type": "deal_stage_stagnation",
            "stage_id": None,       # preenchido na tela
            "stage_key": stage_key, # 'proposta_enviada' na E3; None nas outras
            "pipeline_id": None,    # preenchido na tela
            "stage_days": stage_days,
            "silence_days": silence_days,
            "last_speaker": last_speaker,
            "limit": 20,
        },
    }


def _send(key: str, no: str, template: str) -> dict[str, Any]:
    return {
        "id": _nid(key, no), "type": "send",
        "config": {
            "template_name": template,
            "template_language": "pt_BR",  # conferir o locale APROVADO — ver spec §7
            "template_variables": {"1": "{{nome}}", "2": "{{vendedor}}"},
            # 'pause' (o default do motor) deixaria o lead inelegivel para sempre:
            # enrollment pausado conta como ativo em is_already_enrolled e nunca e
            # retomado. 'cancel' deixa o lead sair limpo e poder voltar depois.
            "on_reply": "cancel",
        },
    }


def _wait(key: str, no: str, dias: int) -> dict[str, Any]:
    return {"id": _nid(key, no), "type": "wait", "config": {"days": dias}}


def _action(key: str, no: str, cfg: dict) -> dict[str, Any]:
    return {"id": _nid(key, no), "type": "action", "config": cfg}


def _end(key: str, no: str) -> dict[str, Any]:
    return {"id": _nid(key, no), "type": "end", "config": {}}


def _esteira(key: str, nome: str, descricao: str, priority: int, nodes: list[dict]) -> dict[str, Any]:
    return {
        "key": key,
        "campaign_id": _cid(key),
        "name": nome,
        "description": descricao,
        "status": "draft",
        "audience": "humano",
        "priority": priority,
        "frequency_cap": 1,
        "nodes": nodes,
    }


# E1a — o lead perguntou e ninguem respondeu.
_NOVO_SEM_RESPOSTA = _esteira(
    "novo_sem_resposta",
    "Esteira — Novo sem resposta nossa",
    "Card na etapa inicial, ultima mensagem do LEAD, 3 dias sem resposta. Manda o "
    "template de retomada e alerta o vendedor. Nao move o card.",
    priority=6,
    nodes=[
        _trigger("novo_sem_resposta", stage_days=0, silence_days=3, last_speaker="lead"),
        _send("novo_sem_resposta", "t1", "esteira_novo_sem_resposta_v1"),
        _action("novo_sem_resposta", "a1", {
            "action_type": "alert_seller",
            "severity": "warning",
            "title": "Lead sem resposta ha 3 dias",
            "message_template": "{{nome}} perguntou e ficou sem resposta. Template de retomada enviado.",
        }),
        _end("novo_sem_resposta", "fim"),
    ],
)

# E1b — atendemos e o lead sumiu.
_NOVO_REENGAJAMENTO = _esteira(
    "novo_reengajamento",
    "Esteira — Novo, lead sumiu",
    "Card na etapa inicial, ultima mensagem NOSSA, 3 dias sem retorno do lead. "
    "Um toque de reengajamento. Nao move o card.",
    priority=6,
    nodes=[
        _trigger("novo_reengajamento", stage_days=0, silence_days=3, last_speaker="nos"),
        _send("novo_reengajamento", "t1", "esteira_novo_reengajamento_v1"),
        _end("novo_reengajamento", "fim"),
    ],
)

# E2 — reposicao: 3 ciclos de 15 dias e o card vira Perdido.
_REPOSICAO = _esteira(
    "reposicao",
    "Esteira — Reposicao",
    "Card na etapa configurada, 15 dias sem conversa. Ate 3 toques de 15 em 15 dias; "
    "no terceiro silencio o card vai para Perdido. Sai sozinha se o card mudar de coluna.",
    priority=4,
    nodes=[
        _trigger("reposicao", stage_days=0, silence_days=15, last_speaker="qualquer"),
        _send("reposicao", "t1", "esteira_reposicao_v1"),
        _wait("reposicao", "w1", 15),
        _send("reposicao", "t2", "esteira_reposicao_v1"),
        _wait("reposicao", "w2", 15),
        _send("reposicao", "t3", "esteira_reposicao_v1"),
        _wait("reposicao", "w3", 15),
        _action("reposicao", "a1", {
            "action_type": "mark_deal_lost",
            "stage_id": None,  # preenchido na tela com a etapa Perdido do funil
            "lost_reason": "sem resposta na esteira de reposicao",
        }),
        _end("reposicao", "fim"),
    ],
)

# E3 — follow-up de proposta: 2 toques e alerta. Nunca move o card.
_PROPOSTA = _esteira(
    "proposta",
    "Esteira — Follow-up de proposta",
    "Card em Proposta Enviada ha 3 dias sem resposta do cliente. Toque em D+3 e D+8; "
    "depois alerta o vendedor. NUNCA move o card sozinho.",
    priority=8,
    nodes=[
        _trigger("proposta", stage_days=3, silence_days=0, last_speaker="nos",
                 stage_key="proposta_enviada"),
        _send("proposta", "t1", "esteira_proposta_d3_v1"),
        _wait("proposta", "w1", 5),
        _send("proposta", "t2", "esteira_proposta_d8_v1"),
        _wait("proposta", "w2", 2),
        _action("proposta", "a1", {
            "action_type": "alert_seller",
            "severity": "warning",
            "title": "Proposta esfriando",
            "message_template": "{{nome}} nao respondeu a proposta ha 10 dias. Card segue em Proposta Enviada.",
        }),
        _end("proposta", "fim"),
    ],
)

ESTEIRAS: tuple[dict[str, Any], ...] = (
    _NOVO_SEM_RESPOSTA, _NOVO_REENGAJAMENTO, _REPOSICAO, _PROPOSTA,
)


def seed_esteiras() -> None:
    """Cria as campanhas que ainda nao existem. NUNCA sobrescreve. Fail-soft."""
    try:
        sb = get_supabase()
        ids = [e["campaign_id"] for e in ESTEIRAS]
        existentes = {
            r["id"] for r in
            (sb.table("campaigns").select("id").in_("id", ids).execute().data or [])
        }
        for e in ESTEIRAS:
            if e["campaign_id"] in existentes:
                continue
            sb.table("campaigns").insert({
                "id": e["campaign_id"],
                "name": e["name"],
                "description": e["description"],
                "status": e["status"],
                "env_tag": _ENV_TAG,
                "audience": e["audience"],
                "priority": e["priority"],
                "frequency_cap": e["frequency_cap"],
            }).execute()
            # Insere os nos primeiro sem ligacao, depois liga — o FK next_node_id
            # aponta para linhas da mesma tabela, entao o alvo precisa existir antes.
            # A lista `nodes` ja esta em ordem linear: cada no aponta para o seguinte.
            for no in e["nodes"]:
                sb.table("campaign_nodes").insert({
                    "id": no["id"],
                    "campaign_id": e["campaign_id"],
                    "type": no["type"],
                    "config": no["config"],
                }).execute()
            for i, no in enumerate(e["nodes"]):
                proximo = e["nodes"][i + 1]["id"] if i + 1 < len(e["nodes"]) else None
                if proximo:
                    sb.table("campaign_nodes").update(
                        {"next_node_id": proximo}
                    ).eq("id", no["id"]).execute()
            logger.info("[ESTEIRAS] campanha '%s' criada", e["name"])
    except Exception as exc:
        logger.error("[ESTEIRAS] seed falhou: %s", exc, exc_info=True)
```

Nota para o executor: a lista `nodes` de cada esteira está em ordem linear e o
encadeamento acima é posicional — cada nó aponta para o seguinte. Não acrescente um
campo `next` aos helpers: duas fontes de verdade para a mesma aresta divergem no
primeiro ajuste.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_esteiras_seed.py -v`
Expected: PASS (13 testes).

- [ ] **Step 5: Chamar no lifespan**

Em `backend/app/main.py`, ao lado da chamada existente de `sync_valeria_cadence_campaign()`:

```python
    try:
        from app.campaigns.esteiras import seed_esteiras
        seed_esteiras()
    except Exception as exc:
        logger.error("[STARTUP] seed das esteiras falhou: %s", exc)
```

- [ ] **Step 6: Suíte inteira**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/campaigns/esteiras.py backend/app/main.py backend/tests/test_esteiras_seed.py
git commit -m "feat(esteiras): seed das quatro campanhas de esteira do vendedor"
```

---

## Task 8: API da tela

**Files:**
- Create: `backend/app/campaigns/esteiras_router.py`
- Modify: `backend/app/main.py` (incluir o router)
- Test: `backend/tests/test_esteiras_router.py`

**Contrato** (o frontend da Task 9 escreve contra isto):

```
GET /api/automation/esteiras
→ { "esteiras": [ {
      "key": "reposicao",
      "nome": "Esteira — Reposicao",
      "descricao": "...",
      "ativa": false,
      "canal_id": null,
      "funil_id": null,
      "etapa_id": null,
      "etapa_key": null,
      "toques": [ { "ordem": 1, "dias": 0, "template_name": "esteira_reposicao_v1" }, ... ],
      "acao_final": "mark_deal_lost"
  } ] }

PUT /api/automation/esteiras/{key}
body: { "ativa": true, "canal_id": "...", "funil_id": "...", "etapa_id": "...",
        "toques": [ { "ordem": 1, "dias": 0, "template_name": "..." } ],
        "stage_id_perdido": "..." }
→ { "ok": true }
```

`dias` do toque 1 é o `silence_days`/`stage_days` do gatilho; dos toques seguintes é
o `days` do nó `wait` anterior. A escrita **não** altera a topologia do grafo.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_esteiras_router.py
"""API achatada das esteiras: le e grava parametros, nunca topologia."""
import pytest
from unittest.mock import MagicMock, patch

from app.campaigns import esteiras_router


def _sb_com(campanhas, nos):
    sb = MagicMock()

    def table(nome):
        t = MagicMock()
        if nome == "campaigns":
            t.select.return_value.in_.return_value.execute.return_value.data = campanhas
        else:
            t.select.return_value.in_.return_value.execute.return_value.data = nos
        return t

    sb.table.side_effect = table
    return sb


@pytest.mark.asyncio
async def test_get_devolve_as_quatro_esteiras():
    from app.campaigns.esteiras import ESTEIRAS
    campanhas = [{"id": e["campaign_id"], "status": "draft", "channel_id": None} for e in ESTEIRAS]
    nos = []
    for e in ESTEIRAS:
        for n in e["nodes"]:
            nos.append({"id": n["id"], "campaign_id": e["campaign_id"],
                        "type": n["type"], "config": n["config"]})
    with patch("app.campaigns.esteiras_router.get_supabase", return_value=_sb_com(campanhas, nos)):
        out = await esteiras_router.listar_esteiras()
    assert len(out["esteiras"]) == 4
    assert {e["key"] for e in out["esteiras"]} == {
        "novo_sem_resposta", "novo_reengajamento", "reposicao", "proposta"}


@pytest.mark.asyncio
async def test_get_marca_ativa_quando_status_active():
    from app.campaigns.esteiras import ESTEIRAS
    campanhas = [{"id": e["campaign_id"],
                  "status": "active" if e["key"] == "reposicao" else "draft",
                  "channel_id": None} for e in ESTEIRAS]
    nos = [{"id": n["id"], "campaign_id": e["campaign_id"], "type": n["type"], "config": n["config"]}
           for e in ESTEIRAS for n in e["nodes"]]
    with patch("app.campaigns.esteiras_router.get_supabase", return_value=_sb_com(campanhas, nos)):
        out = await esteiras_router.listar_esteiras()
    ativa = {e["key"]: e["ativa"] for e in out["esteiras"]}
    assert ativa["reposicao"] is True
    assert ativa["proposta"] is False


@pytest.mark.asyncio
async def test_put_key_desconhecida_da_404():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await esteiras_router.gravar_esteira("nao_existe", {"ativa": True})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_put_liga_e_grava_canal():
    sb = MagicMock()
    with patch("app.campaigns.esteiras_router.get_supabase", return_value=sb):
        await esteiras_router.gravar_esteira("reposicao", {
            "ativa": True, "canal_id": "ch-joao", "funil_id": "pipe-joao",
            "etapa_id": "stage-x", "toques": [{"ordem": 1, "dias": 20, "template_name": "t"}],
        })
    updates = [c[0][0] for c in sb.table.return_value.update.call_args_list]
    assert any(u.get("status") == "active" for u in updates)
    assert any(u.get("channel_id") == "ch-joao" for u in updates)


@pytest.mark.asyncio
async def test_put_desliga_grava_draft():
    sb = MagicMock()
    with patch("app.campaigns.esteiras_router.get_supabase", return_value=sb):
        await esteiras_router.gravar_esteira("reposicao", {"ativa": False})
    updates = [c[0][0] for c in sb.table.return_value.update.call_args_list]
    assert any(u.get("status") == "draft" for u in updates)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && python -m pytest tests/test_esteiras_router.py -v`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar o router**

```python
"""API achatada das esteiras do vendedor — o que a aba /campanhas > Esteiras consome.

O frontend NAO conhece o formato do grafo de campaign_nodes. Este modulo traduz nos
dois sentidos, e a escrita so mexe em PARAMETRO (dias, template, canal, etapa) —
nunca na topologia. Quem quiser mudar a forma do fluxo usa o builder.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.campaigns.esteiras import ESTEIRAS
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/automation/esteiras", tags=["esteiras"])

_POR_KEY = {e["key"]: e for e in ESTEIRAS}


@router.get("")
async def listar_esteiras() -> dict[str, Any]:
    sb = get_supabase()
    ids = [e["campaign_id"] for e in ESTEIRAS]
    campanhas = {
        c["id"]: c for c in
        (sb.table("campaigns").select("id, status, channel_id").in_("id", ids).execute().data or [])
    }
    nos_por_campanha: dict[str, list[dict]] = {}
    for n in (sb.table("campaign_nodes").select("id, campaign_id, type, config")
              .in_("campaign_id", ids).execute().data or []):
        nos_por_campanha.setdefault(n["campaign_id"], []).append(n)

    saida = []
    for e in ESTEIRAS:
        camp = campanhas.get(e["campaign_id"]) or {}
        nos = nos_por_campanha.get(e["campaign_id"]) or e["nodes"]
        trigger = next((n for n in nos if n["type"] == "trigger"), {"config": {}})
        tcfg = trigger.get("config") or {}
        envios = [n for n in nos if n["type"] == "send"]
        esperas = [n for n in nos if n["type"] == "wait"]
        acoes = [n for n in nos if n["type"] == "action"]

        toques = []
        for i, envio in enumerate(envios):
            if i == 0:
                dias = tcfg.get("silence_days") or tcfg.get("stage_days") or 0
            else:
                espera = esperas[i - 1] if i - 1 < len(esperas) else {"config": {}}
                dias = (espera.get("config") or {}).get("days", 0)
            toques.append({
                "ordem": i + 1,
                "dias": dias,
                "template_name": (envio.get("config") or {}).get("template_name"),
            })

        saida.append({
            "key": e["key"],
            "nome": e["name"],
            "descricao": e["description"],
            "ativa": camp.get("status") == "active",
            "canal_id": camp.get("channel_id"),
            "funil_id": tcfg.get("pipeline_id"),
            "etapa_id": tcfg.get("stage_id"),
            "etapa_key": tcfg.get("stage_key"),
            "toques": toques,
            "acao_final": ((acoes[0].get("config") or {}).get("action_type") if acoes else None),
        })
    return {"esteiras": saida}


@router.put("/{key}")
async def gravar_esteira(key: str, body: dict = Body(...)) -> dict[str, Any]:
    esteira = _POR_KEY.get(key)
    if not esteira:
        raise HTTPException(404, f"esteira '{key}' nao existe")
    sb = get_supabase()
    cid = esteira["campaign_id"]

    campanha: dict[str, Any] = {}
    if "ativa" in body:
        campanha["status"] = "active" if body["ativa"] else "draft"
    if "canal_id" in body:
        campanha["channel_id"] = body["canal_id"]
    if campanha:
        sb.table("campaigns").update(campanha).eq("id", cid).execute()

    trigger = next((n for n in esteira["nodes"] if n["type"] == "trigger"), None)
    if trigger:
        tcfg = dict(trigger["config"])
        if "funil_id" in body:
            tcfg["pipeline_id"] = body["funil_id"]
        if "etapa_id" in body:
            tcfg["stage_id"] = body["etapa_id"]
        toques = body.get("toques") or []
        if toques:
            primeiro = toques[0].get("dias", 0)
            # Qual relogio o primeiro toque usa depende da esteira: a de proposta conta
            # dias na ETAPA, as outras contam dias de SILENCIO. Preserva o que o seed
            # definiu em vez de adivinhar.
            if tcfg.get("stage_days"):
                tcfg["stage_days"] = primeiro
            else:
                tcfg["silence_days"] = primeiro
        sb.table("campaign_nodes").update({"config": tcfg}).eq("id", trigger["id"]).execute()

    envios = [n for n in esteira["nodes"] if n["type"] == "send"]
    esperas = [n for n in esteira["nodes"] if n["type"] == "wait"]
    for i, toque in enumerate(body.get("toques") or []):
        if i < len(envios) and toque.get("template_name"):
            cfg = dict(envios[i]["config"])
            cfg["template_name"] = toque["template_name"]
            sb.table("campaign_nodes").update({"config": cfg}).eq("id", envios[i]["id"]).execute()
        if i > 0 and i - 1 < len(esperas):
            cfg = dict(esperas[i - 1]["config"])
            cfg["days"] = toque.get("dias", cfg.get("days", 1))
            sb.table("campaign_nodes").update({"config": cfg}).eq("id", esperas[i - 1]["id"]).execute()

    if body.get("stage_id_perdido"):
        for no in esteira["nodes"]:
            if no["type"] == "action" and (no["config"] or {}).get("action_type") == "mark_deal_lost":
                cfg = dict(no["config"])
                cfg["stage_id"] = body["stage_id_perdido"]
                sb.table("campaign_nodes").update({"config": cfg}).eq("id", no["id"]).execute()

    return {"ok": True}
```

- [ ] **Step 4: Registrar no `main.py`**

Ao lado dos outros `app.include_router(...)`:

```python
from app.campaigns.esteiras_router import router as esteiras_router
app.include_router(esteiras_router)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && python -m pytest tests/test_esteiras_router.py -v`
Expected: PASS (5 testes).

- [ ] **Step 6: Commit**

```bash
git add backend/app/campaigns/esteiras_router.py backend/app/main.py backend/tests/test_esteiras_router.py
git commit -m "feat(esteiras): API achatada de leitura e escrita dos parametros"
```

---

## Task 9: Aba "Esteiras"

**Files:**
- Create: `frontend/src/app/api/automation/esteiras/route.ts`
- Create: `frontend/src/app/api/automation/esteiras/[key]/route.ts`
- Create: `frontend/src/components/campaigns/esteiras-tab.tsx`
- Modify: `frontend/src/app/(authenticated)/campanhas/page.tsx`
- Test: `frontend/src/components/campaigns/esteiras-tab.test.tsx`

- [ ] **Step 1: Invocar a skill de design**

Antes de escrever qualquer componente, invoque a skill `frontend-design`. É regra do projeto (memória `feedback_frontend_skill`).

- [ ] **Step 2: Conferir se a rota entra no gate de autenticação**

Leia `frontend/src/proxy.ts` e `frontend/src/proxy-coverage.test.ts`. O matcher do proxy só protege rotas listadas — `/api/quotes` já ficou de fora uma vez por isso (ver spec do orçamento, §"o que a execução revelou", item 2). Acrescente `/api/automation/esteiras` ao matcher e confirme que `proxy-coverage.test.ts` continua passando.

- [ ] **Step 3: Escrever o teste que falha**

```tsx
// frontend/src/components/campaigns/esteiras-tab.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { EsteirasTab } from "./esteiras-tab";

const RESPOSTA = {
  esteiras: [
    { key: "novo_sem_resposta", nome: "Esteira — Novo sem resposta nossa", descricao: "d",
      ativa: false, canal_id: null, funil_id: null, etapa_id: null, etapa_key: null,
      toques: [{ ordem: 1, dias: 3, template_name: "esteira_novo_sem_resposta_v1" }],
      acao_final: "alert_seller" },
    { key: "reposicao", nome: "Esteira — Reposicao", descricao: "d",
      ativa: true, canal_id: "ch", funil_id: "p", etapa_id: "s", etapa_key: null,
      toques: [{ ordem: 1, dias: 15, template_name: "esteira_reposicao_v1" }],
      acao_final: "mark_deal_lost" },
  ],
};

beforeEach(() => {
  global.fetch = vi.fn(async (url: string) => {
    if (String(url).includes("/api/automation/esteiras")) {
      return { ok: true, json: async () => RESPOSTA } as Response;
    }
    return { ok: true, json: async () => ({ templates: [] }) } as Response;
  }) as unknown as typeof fetch;
});

describe("EsteirasTab", () => {
  it("lista as esteiras vindas da API", async () => {
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getByText(/Novo sem resposta/i)).toBeTruthy());
    expect(screen.getByText(/Reposicao/i)).toBeTruthy();
  });

  it("mostra o estado ligado/desligado de cada esteira", async () => {
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getAllByRole("switch").length).toBe(2));
    const switches = screen.getAllByRole("switch");
    expect(switches[0].getAttribute("aria-checked")).toBe("false");
    expect(switches[1].getAttribute("aria-checked")).toBe("true");
  });

  it("mostra a acao final como texto, nao como campo editavel", async () => {
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getByText(/move para Perdido/i)).toBeTruthy());
    expect(screen.getByText(/avisa o vendedor/i)).toBeTruthy();
  });
});
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `cd frontend && npm test -- esteiras-tab`
Expected: FAIL — módulo não existe.

- [ ] **Step 5: Implementar o proxy e o componente**

O proxy segue o padrão de `frontend/src/app/api/` já existente (leia
`frontend/src/app/api/pipelines/route.ts` como referência de forma). O componente é
um formulário, não um builder:

- um card por esteira (as duas de "Novo" aparecem juntas sob o título "Etapa Novo");
- `role="switch"` com `aria-checked` no liga/desliga — os testes dependem disso;
- selects de canal, funil e etapa (etapa carregada de `/api/pipelines` conforme o
  funil escolhido);
- por toque: número de dias e select de template, alimentado por
  `/api/templates` **filtrando só os aprovados**;
- ação final renderizada como texto fixo: `mark_deal_lost` → "move para Perdido",
  `alert_seller` → "avisa o vendedor";
- ao ligar uma esteira, um aviso antes de confirmar dizendo quantos cards ficam
  elegíveis naquele instante (§5.1 da spec — a avalanche do primeiro dia tem de ser
  visível antes do clique);
- link "abrir no builder" apontando para `/campanhas/cadencias/{campaign_id}`.

- [ ] **Step 6: Registrar a aba**

Em `frontend/src/app/(authenticated)/campanhas/page.tsx`, acrescente `"esteiras"` a
`VALID_TABS` e renderize `<EsteirasTab />` quando `activeTab === "esteiras"`, no
mesmo formato dos outros ramos.

- [ ] **Step 7: Rodar e ver passar**

Run: `cd frontend && npm test`
Expected: PASS. Nada de novo pode quebrar; `npm run lint` continua falhando na master (não é seu).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/api/automation frontend/src/components/campaigns/esteiras-tab.tsx frontend/src/components/campaigns/esteiras-tab.test.tsx "frontend/src/app/(authenticated)/campanhas/page.tsx" frontend/src/proxy.ts
git commit -m "feat(esteiras): aba Esteiras em /campanhas"
```

---

## Task 10: Script dos templates da Meta

**Files:**
- Create: `scripts/create_esteira_templates.py`

Modelado em `scripts/create_utility_templates.py` (não versionado), com uma
diferença obrigatória: **token e WABA_ID vêm do ambiente**. O script atual tem um
access token da Meta escrito no arquivo; versionar assim vazaria o token no
histórico do git para sempre.

- [ ] **Step 1: Escrever o script**

```python
"""Submete na Meta os 5 templates das esteiras do vendedor.

Spec: docs/superpowers/specs/2026-09-04-esteiras-vendedor-design.md §7

Uso:
    META_WABA_ID=... META_ACCESS_TOKEN=... python scripts/create_esteira_templates.py

Diferente de scripts/create_utility_templates.py, este NAO tem credencial no
arquivo — token em codigo versionado vaza no historico do git para sempre.

LOCALE: submetemos em pt_BR, mas o que vale e o idioma que a Meta APROVAR. O
template automacao_valeria_to_joao foi aprovado so em `en` (corpo em portugues) e o
default pt_BR causava 404 #132001 com o job cancelado sem entregar. Depois da
aprovacao, confira em message_templates e ajuste `template_language` na config do
no de envio.
"""
import json
import os
import sys
import urllib.request

WABA_ID = os.environ.get("META_WABA_ID")
TOKEN = os.environ.get("META_ACCESS_TOKEN")
if not WABA_ID or not TOKEN:
    sys.exit("Defina META_WABA_ID e META_ACCESS_TOKEN no ambiente.")

URL = f"https://graph.facebook.com/v21.0/{WABA_ID}/message_templates"

# O terceiro botao ("Nao tenho interesse") ja alimenta a blacklist no fluxo atual —
# e a saida digna que protege o rating do numero de bloqueio em massa.
BUTTONS = [
    {"type": "QUICK_REPLY", "text": "Continuar atendimento"},
    {"type": "QUICK_REPLY", "text": "Tirar duvidas"},
    {"type": "QUICK_REPLY", "text": "Nao tenho interesse"},
]


def body(text, examples):
    return {"type": "BODY", "text": text, "example": {"body_text": [examples]}}


TEMPLATES = [
    {
        "name": "esteira_novo_sem_resposta_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Aqui e o {{2}}, do Cafe Canastra. Vi que sua mensagem ficou "
                "sem retorno e a responsabilidade e nossa. Sigo a disposicao para te "
                "passar valores e condicoes. Posso continuar por aqui?",
                ["Marcella", "Joao"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
    {
        "name": "esteira_novo_reengajamento_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Aqui e o {{2}}, do Cafe Canastra. Nosso atendimento ficou "
                "em aberto e queria saber se voce ainda tem interesse. Basta responder "
                "esta mensagem que sigo de onde paramos.",
                ["Marcella", "Joao"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
    {
        "name": "esteira_reposicao_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Aqui e o {{2}}, do Cafe Canastra. Faz um tempo desde o "
                "nosso ultimo contato e queria saber como esta seu estoque. Se quiser, "
                "te mando as condicoes atuais.",
                ["Marcella", "Joao"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
    {
        "name": "esteira_proposta_d3_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Aqui e o {{2}}, do Cafe Canastra. Passando para saber se "
                "voce conseguiu ver a proposta que te enviei. Qualquer duvida sobre "
                "valores, prazo ou personalizacao, e so responder aqui.",
                ["Marcella", "Joao"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
    {
        "name": "esteira_proposta_d8_v1",
        "language": "pt_BR",
        "components": [
            body(
                "Ola, {{1}}! Aqui e o {{2}}, do Cafe Canastra. Sua proposta continua "
                "valendo e nao quero que voce perca o prazo. Me diz se faz sentido "
                "seguir ou se prefere que eu ajuste alguma coisa.",
                ["Marcella", "Joao"],
            ),
            {"type": "BUTTONS", "buttons": BUTTONS},
        ],
    },
]


def submeter(tmpl):
    payload = json.dumps({
        "name": tmpl["name"],
        "language": tmpl["language"],
        "category": "UTILITY",
        "components": tmpl["components"],
    }).encode("utf-8")
    req = urllib.request.Request(
        URL, data=payload, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, exc.read().decode("utf-8")


if __name__ == "__main__":
    for tmpl in TEMPLATES:
        ok, resposta = submeter(tmpl)
        print(f"{'OK ' if ok else 'ERRO'} {tmpl['name']}: {resposta}")
```

- [ ] **Step 2: Verificar que o script não roda sem credencial**

Run: `cd backend && python ../scripts/create_esteira_templates.py`
Expected: sai com a mensagem "Defina META_WABA_ID e META_ACCESS_TOKEN no ambiente." e código 1. **Não** submeta nada de verdade sem o dono pedir — templates rejeitados contam contra a conta.

- [ ] **Step 3: Commit**

```bash
git add scripts/create_esteira_templates.py
git commit -m "feat(esteiras): script de submissao dos templates na Meta"
```

---

## Fechamento

- [ ] **Suíte inteira, backend e frontend**

Run: `cd backend && python -m pytest -q` — Expected: PASS, sem regressão.
Run: `cd frontend && npm test` — Expected: PASS.

- [ ] **Checklist para o dono (nada disso é código; vai no relatório final)**

1. Aplicar `supabase/migrations/20260825_quotes.sql` — **pré-requisito**, e é o que
   destrava `/orcamento` e o item 9 da ata.
2. Conferir se `20260709_cadence_enrollment_hardening.sql` já foi aplicada.
3. Aplicar `supabase/migrations/20260904_esteiras_vendedor.sql`.
4. Rodar `scripts/create_esteira_templates.py` e aguardar aprovação dos 5 templates.
5. Conferir o **locale aprovado** de cada um e ajustar `template_language` na tela.
6. Em `/campanhas > Esteiras`: escolher canal e funil, apontar a etapa de cada
   esteira, e só então ligar — uma de cada vez, observando o volume do primeiro dia.
