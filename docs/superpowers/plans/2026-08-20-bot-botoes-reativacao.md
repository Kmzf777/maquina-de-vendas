# Bot de Botões — Qualificação de Reativação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar um agente determinístico de fluxo de botões ("Bot Reativação") que qualifica leads inativos por cliques, reconhecido como agente no CRM e elencável em disparos nos números da ValerIA e do João.

**Architecture:** Uma linha em `agent_profiles` com `kind='button_flow'` identifica o bot. Um módulo novo `backend/app/button_flow/` implementa o fluxo — núcleo puro (`flows.py` + `engine.py`), efeitos de CRM (`effects.py`) e orquestração (`runner.py`). Um gate em `buffer/processor.py`, posicionado **antes** do gate de canal humano, desvia a conversa para o bot e retorna sem nunca tocar no LLM.

**Tech Stack:** Python 3 / FastAPI / Supabase (PostgREST) / Meta Cloud API / pytest (asyncio_mode=auto) · Next.js App Router / TypeScript / vitest

**Spec:** `docs/superpowers/specs/2026-08-20-bot-botoes-reativacao-design.md`

---

## Contexto que o implementador precisa saber

Este repositório tem convenções fortes. Leia antes de começar:

1. **`CLAUDE.md` na raiz** — fluxo git sem PRs, regra de endereços Docker, Meta Graph API é o único provedor ativo (ignore Evolution).
2. **Migrations não rodam no deploy.** O SQL é aplicado à mão no Supabase. Logo, todo código novo precisa ser **inerte** enquanto a coluna não existe.
3. **Fail-soft é a regra.** Quase todo I/O aqui é `try/except` que loga e segue. Nunca deixe um erro de CRM derrubar o turno da conversa.
4. **Testes:** `cd backend && python -m pytest`. `asyncio_mode=auto` (não precisa de `@pytest.mark.asyncio`, mas os testes existentes usam — mantenha o padrão). Nome do arquivo: `test_<assunto>_<data>.py`.
5. **Comentários em português**, explicando o *porquê* (não o *quê*), como no resto do código.

### Arquivos de referência para copiar padrões

| Para fazer | Olhe |
|---|---|
| Núcleo puro testável sem I/O | `backend/app/agent/persona.py` |
| Efeito de CRM fail-soft | `backend/app/leads/service.py:1593` (`apply_optout_side_effects`) |
| Método opcional de provider | `backend/app/whatsapp/base.py` (`send_contact`) |
| Teste de gate do processor | `backend/tests/test_processor_mark_read_gating_2026_07_03.py` |
| Teste de arquivo SQL | `backend/tests/test_reativacao_sql.py` |
| Migração idempotente | `supabase/migrations/009b_multi_agent_schema.sql` |

---

## Estrutura de arquivos

**Criar:**

| Arquivo | Responsabilidade |
|---|---|
| `supabase/migrations/20260820_button_flow_agent.sql` | Colunas `kind`/`flow_state`, seed do agente e das 6 tags |
| `backend/app/button_flow/__init__.py` | Vazio |
| `backend/app/button_flow/flows.py` | Dados puros: nós, rótulos, ids, textos, tags. Zero lógica. |
| `backend/app/button_flow/engine.py` | Núcleo puro: `decidir(estado, evento, canal_do_vendedor) -> Decisao`. Zero I/O. |
| `backend/app/button_flow/effects.py` | Efeitos no CRM (tags, opt-out, handoff, recontato). Supabase. |
| `backend/app/button_flow/runner.py` | Orquestração: estado → engine → envio → efeitos → persiste. |
| `backend/tests/test_button_flow_engine_2026_08_20.py` | Matriz completa do núcleo puro |
| `backend/tests/test_button_flow_parser_2026_08_20.py` | Parser + buffer carregam o payload |
| `backend/tests/test_button_flow_provider_2026_08_20.py` | `send_interactive_buttons` |
| `backend/tests/test_button_flow_effects_2026_08_20.py` | Efeitos de CRM |
| `backend/tests/test_button_flow_runner_2026_08_20.py` | Orquestração |
| `backend/tests/test_button_flow_gate_2026_08_20.py` | Gate no processor |
| `backend/tests/test_button_flow_preflight_2026_08_20.py` | Preflight do disparo |
| `backend/tests/test_button_flow_migration_2026_08_20.py` | Conteúdo do SQL |
| `frontend/src/lib/agent-picker.ts` | Regra pura: quais perfis o seletor mostra por canal |
| `frontend/src/lib/agent-picker.test.ts` | Testes da regra |

**Modificar:**

| Arquivo | O quê |
|---|---|
| `backend/app/webhook/meta_parser.py:138-151` | Emitir `type="button"` com `metadata` |
| `backend/app/buffer/manager.py:30,40` | `"button"` em `_META_TYPES` |
| `backend/app/buffer/processor.py:2225` | `"button"` decodificado em `_resolve_media` |
| `backend/app/buffer/processor.py:~1409` | Gate do bot antes do gate de canal humano |
| `backend/app/whatsapp/base.py` | `send_interactive_buttons` (default `NotImplementedError`) |
| `backend/app/whatsapp/meta.py` | Implementação Meta |
| `backend/app/whatsapp/mock_provider.py` | Implementação mock |
| `backend/app/agent_profiles/service.py` | `get_profile_kind(profile_id)` |
| `backend/app/templates/preflight.py` | Checagem de botões quando o perfil é `button_flow` |
| `backend/app/broadcast/router.py` | Passa o `kind` do agente ao preflight no `/start` |
| `frontend/src/lib/types.ts` | `kind` em `AgentProfile` |
| `frontend/src/components/campaigns/create-broadcast-modal.tsx` | Seletor usa `agent-picker.ts` |

---

## Task 1: Migração de banco

**Files:**
- Create: `supabase/migrations/20260820_button_flow_agent.sql`
- Test: `backend/tests/test_button_flow_migration_2026_08_20.py`

- [ ] **Step 1: Write the failing test**

```python
"""A migração do bot de botões precisa ser idempotente e semear TODAS as tags.

Testar SQL como texto parece pobre, mas aqui é o único guard-rail possível: a
migração é aplicada à mão no Supabase (o deploy não roda migrations), então um
seed faltando só apareceria em produção, silenciosamente — `add_tags_to_lead`
ignora nome de tag inexistente sem erro.
"""
from pathlib import Path

import pytest

SQL = (
    Path(__file__).resolve().parents[2]
    / "supabase" / "migrations" / "20260820_button_flow_agent.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    assert SQL.exists(), f"migração não encontrada em {SQL}"
    return SQL.read_text(encoding="utf-8")


def test_adiciona_colunas_de_forma_idempotente(sql: str):
    assert "agent_profiles" in sql and "kind" in sql
    assert "conversations" in sql and "flow_state" in sql
    assert sql.count("ADD COLUMN IF NOT EXISTS") >= 2


def test_constraint_de_kind_dentro_de_do_block(sql: str):
    # ADD CONSTRAINT não aceita IF NOT EXISTS — sem o DO block a migração
    # quebra na segunda execução.
    assert "DO $$" in sql
    assert "agent_profiles_kind_check" in sql
    assert "'llm'" in sql and "'button_flow'" in sql


def test_semeia_o_agente_com_prompt_key_estavel(sql: str):
    assert "Bot Reativação" in sql
    assert "bot_reativacao" in sql
    assert "WHERE NOT EXISTS" in sql


@pytest.mark.parametrize("tag", [
    "Reativação: Quente",
    "Reativação: 1 mês",
    "Reativação: 3 meses",
    "Reativação: 6 meses",
    "Reativação: Recusou",
    "Reativação: Atendimento humano",
])
def test_semeia_todas_as_seis_tags(sql: str, tag: str):
    assert tag in sql, f"tag {tag!r} não semeada — add_tags_to_lead a ignoraria em silêncio"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_migration_2026_08_20.py -v`
Expected: FAIL — todos com `AssertionError: migração não encontrada em ...`

- [ ] **Step 3: Write the migration**

Create `supabase/migrations/20260820_button_flow_agent.sql`:

```sql
-- 20260820_button_flow_agent.sql
-- Bot de botões (Meta interactive) para qualificação de reativação.
--
-- Introduz o conceito de agente NÃO-LLM: `agent_profiles.kind='button_flow'`.
-- Um perfil desse tipo é atendido por app/button_flow/runner.py (fluxo fechado,
-- determinístico) em vez do orquestrador Gemini — inclusive em canais mode='human',
-- porque um fluxo de botões não é IA generativa.
--
-- APLICAR À MÃO no Supabase: o deploy não roda migrations. Até ser aplicada, o código
-- novo é inerte (nenhum perfil button_flow existe, o gate nunca dispara).

-- 1) Tipo do agente ---------------------------------------------------------
ALTER TABLE agent_profiles
  ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'llm';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'agent_profiles_kind_check'
  ) THEN
    ALTER TABLE agent_profiles
      ADD CONSTRAINT agent_profiles_kind_check
      CHECK (kind IN ('llm', 'button_flow'));
  END IF;
END $$;

COMMENT ON COLUMN agent_profiles.kind IS
  'llm = atendido pelo orquestrador Gemini; button_flow = fluxo determinístico de botões (app/button_flow).';

-- 2) Estado do fluxo por conversa -------------------------------------------
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS flow_state jsonb DEFAULT NULL;

COMMENT ON COLUMN conversations.flow_state IS
  'Estado do bot de botões: {"flow","node","nudged","updated_at"}. NULL = fluxo não iniciado.';

-- 3) O agente ---------------------------------------------------------------
INSERT INTO agent_profiles (name, kind, prompt_key, model, base_prompt, stages)
SELECT 'Bot Reativação', 'button_flow', 'bot_reativacao', '', '', '{}'::jsonb
WHERE NOT EXISTS (
  SELECT 1 FROM agent_profiles WHERE prompt_key = 'bot_reativacao'
);

-- 4) Tags do desfecho -------------------------------------------------------
-- add_tags_to_lead resolve por NOME EXATO e nunca cria tags. Sem este seed, as
-- tags do bot seriam ignoradas sem nenhum erro visível.
INSERT INTO tags (name, color)
SELECT v.name, v.color
FROM (VALUES
  ('Reativação: Quente',             '#ef4444'),
  ('Reativação: 1 mês',              '#f59e0b'),
  ('Reativação: 3 meses',            '#eab308'),
  ('Reativação: 6 meses',            '#84cc16'),
  ('Reativação: Recusou',            '#6b7280'),
  ('Reativação: Atendimento humano',  '#3b82f6')
) AS v(name, color)
WHERE NOT EXISTS (SELECT 1 FROM tags t WHERE t.name = v.name);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_migration_2026_08_20.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260820_button_flow_agent.sql backend/tests/test_button_flow_migration_2026_08_20.py
git commit -m "feat(button-flow): migracao do agente de fluxo de botoes"
```

---

## Task 2: `flows.py` — declaração do fluxo

**Files:**
- Create: `backend/app/button_flow/__init__.py` (vazio)
- Create: `backend/app/button_flow/flows.py`
- Test: `backend/tests/test_button_flow_engine_2026_08_20.py` (primeiros testes)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_button_flow_engine_2026_08_20.py`:

```python
"""Núcleo puro do bot de botões: declaração do fluxo + motor de decisão.

Sem I/O: tudo aqui opera sobre dicts e dataclasses, no mesmo espírito de
app/agent/persona.py. É a camada onde a matriz de comportamento tem que estar
100% coberta, porque é a única que roda igual em produção e no teste.
"""
from app.button_flow import flows


def test_limites_da_meta_nos_botoes():
    """3 botões no máximo, título de até 20 chars na interativa, ids únicos."""
    for no, botoes in flows.BOTOES_POR_NO.items():
        assert 1 <= len(botoes) <= 3, f"{no}: a Meta aceita no máximo 3 botões"
        ids = [b.id for b in botoes]
        assert len(ids) == len(set(ids)), f"{no}: ids duplicados"
        for b in botoes:
            assert len(b.titulo) <= 20, f"{no}/{b.id}: título > 20 chars na interativa"


def test_rotulo_do_template_e_aceito_pelo_botao_correspondente():
    """Nível 1 tem DOIS rótulos por botão: o do template e o da interativa.

    A Meta permite 25 chars no botão de template e só 20 no de mensagem interativa,
    e dois dos rótulos aprovados têm 22 — não cabem na interativa. O template mantém
    a copy aprovada; o reoferecimento usa a versão curta. Os dois têm que casar o
    mesmo clique, senão o lead que responde ao template cai no vazio.
    """
    for botao, rotulo in zip(flows.BOTOES_INTERESSE, flows.ROTULOS_TEMPLATE_NIVEL1):
        assert rotulo in botao.titulos_aceitos
        assert botao.titulo in botao.titulos_aceitos


def test_rotulos_do_template_cabem_no_limite_de_template():
    for rotulo in flows.ROTULOS_TEMPLATE_NIVEL1:
        assert len(rotulo) <= 25, f"{rotulo!r}: título > 25 chars no template"


def test_nenhum_rotulo_aceito_e_ambiguo():
    """Dois botões que aceitam o mesmo texto tornariam o clique indecidível."""
    vistos: dict[str, str] = {}
    for no, botoes in flows.BOTOES_POR_NO.items():
        for b in botoes:
            for titulo in b.titulos_aceitos:
                chave = titulo.strip().lower()
                assert chave not in vistos, f"{titulo!r} já é aceito por {vistos[chave]}"
                vistos[chave] = f"{no}/{b.id}"


def test_todo_prazo_tem_tag_e_meses():
    for prazo in flows.PRAZOS:
        assert prazo.meses > 0
        assert prazo.tag.startswith("Reativação: ")
        assert prazo.rotulo_humano
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_engine_2026_08_20.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.button_flow'`

- [ ] **Step 3: Write `flows.py`**

Create `backend/app/button_flow/__init__.py` (arquivo vazio).

Create `backend/app/button_flow/flows.py`:

```python
"""Declaração do fluxo de botões da reativação. Dados puros, zero lógica.

Separado de engine.py de propósito: mudar um texto ou um rótulo não deve exigir
reler o motor de decisão, e o motor não deve precisar mudar para um fluxo novo.

Leaf module: não importa nada de `app`, evitando ciclos de import.
"""
from __future__ import annotations

from dataclasses import dataclass

# Versão do fluxo. Gravada em conversations.flow_state["flow"]; um estado com
# versão diferente é tratado como incompatível e devolvido ao humano.
FLOW_ID = "reativacao_v1"

# ── Nós ─────────────────────────────────────────────────────────────────────
NO_INTERESSE = "aguardando_interesse"
NO_PRAZO = "aguardando_prazo"
NO_ENCERRADO = "encerrado"

# ── Tags de desfecho (semeadas em 20260820_button_flow_agent.sql) ───────────
TAG_QUENTE = "Reativação: Quente"
TAG_RECUSOU = "Reativação: Recusou"
TAG_HUMANO = "Reativação: Atendimento humano"


@dataclass(frozen=True)
class Botao:
    """Um botão do fluxo.

    `titulo` é o rótulo da mensagem INTERATIVA (limite Meta: 20 chars).
    `rotulo_template` é o rótulo aprovado no TEMPLATE (limite: 25 chars), quando ele
    precisa ser diferente por não caber nos 20. O motor aceita os dois ao casar um
    clique — é o mesmo botão, em duas superfícies com limites diferentes.
    """
    id: str
    titulo: str
    rotulo_template: str | None = None

    @property
    def titulos_aceitos(self) -> tuple[str, ...]:
        if self.rotulo_template and self.rotulo_template != self.titulo:
            return (self.titulo, self.rotulo_template)
        return (self.titulo,)


@dataclass(frozen=True)
class Prazo:
    id: str
    titulo: str
    meses: int
    rotulo_humano: str
    tag: str


# ── Nível 1: interesse ──────────────────────────────────────────────────────
# Os IDs só valem para o reoferecimento (nudge), que sai como mensagem interativa:
# quick reply de template não aceita payload customizado — o payload chega igual ao
# texto do botão. Por isso o motor casa nível 1 por id OU por título normalizado.
#
# Dois rótulos por botão: a Meta permite 25 chars no template e só 20 na interativa,
# e a copy aprovada de dois deles tem 22. O template (a mensagem que os leads de fato
# recebem no disparo) fica com a copy aprovada; o nudge usa a versão curta.
BTN_QUENTE = Botao("interesse_quente", "Quero comprar agora")
BTN_TALVEZ = Botao("interesse_talvez", "Mais pra frente", "Talvez em alguns meses")
BTN_SAIR = Botao("interesse_sair", "Sair da lista", "Não quero mais receber")

BOTOES_INTERESSE: tuple[Botao, ...] = (BTN_QUENTE, BTN_TALVEZ, BTN_SAIR)

# Contrato com o template aprovado — verificado pelo preflight do disparo.
ROTULOS_TEMPLATE_NIVEL1: tuple[str, ...] = tuple(
    b.rotulo_template or b.titulo for b in BOTOES_INTERESSE
)

# ── Nível 2: prazo de recontato ─────────────────────────────────────────────
PRAZOS: tuple[Prazo, ...] = (
    Prazo("prazo_1m", "Daqui a 1 mês", 1, "daqui a 1 mês", "Reativação: 1 mês"),
    Prazo("prazo_3m", "Daqui a 3 meses", 3, "daqui a 3 meses", "Reativação: 3 meses"),
    Prazo("prazo_6m", "Daqui a 6 meses", 6, "daqui a 6 meses", "Reativação: 6 meses"),
)

BOTOES_PRAZO: tuple[Botao, ...] = tuple(Botao(p.id, p.titulo) for p in PRAZOS)

BOTOES_POR_NO: dict[str, tuple[Botao, ...]] = {
    NO_INTERESSE: BOTOES_INTERESSE,
    NO_PRAZO: BOTOES_PRAZO,
}

# ── Textos ──────────────────────────────────────────────────────────────────
# O corpo do nível 1 NÃO vive aqui: ele é o template aprovado na Meta, escolhido
# pelo operador no disparo. Só o corpo do reoferecimento é nosso.
CORPO_NUDGE = "Pra facilitar, é só tocar numa das opções abaixo:"

CORPO_PRAZO = "Beleza! Quando faz sentido eu te chamar de novo?"

MSG_QUENTE_VALERIA = (
    "Perfeito! Vou te passar pro João, nosso especialista — ele te chama já já. "
    "Deixo o contato dele aqui embaixo pra agilizar."
)
MSG_QUENTE_VENDEDOR = "Perfeito! Já te chamo por aqui pra gente resolver."

MSG_PRAZO_FECHAMENTO = (
    "Combinado, {prazo}. Vou anotar aqui e te chamo nessa época. "
    "Qualquer coisa antes disso, é só me escrever!"
)

MSG_OPTOUT = "Entendido, não te mando mais nada. Obrigado pelo tempo e um abraço!"

# Corpo do reoferecimento por nó: no nível 1 só o convite (a pergunta já foi feita
# pelo template); no nível 2 a pergunta inteira, porque ela é nossa.
CORPO_NUDGE_POR_NO: dict[str, str] = {
    NO_INTERESSE: CORPO_NUDGE,
    NO_PRAZO: f"{CORPO_NUDGE}\n\n{CORPO_PRAZO}",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_engine_2026_08_20.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/button_flow/ backend/tests/test_button_flow_engine_2026_08_20.py
git commit -m "feat(button-flow): declaracao do fluxo de reativacao"
```

---

## Task 3: `engine.py` — motor de decisão puro

**Files:**
- Create: `backend/app/button_flow/engine.py`
- Modify: `backend/tests/test_button_flow_engine_2026_08_20.py` (acrescentar)

- [ ] **Step 1: Write the failing test**

Acrescente ao fim de `backend/tests/test_button_flow_engine_2026_08_20.py`:

```python
from app.button_flow import engine
from app.button_flow.engine import Clique, Decisao, Texto


def estado(no: str = flows.NO_INTERESSE, nudged: bool = False) -> dict:
    return {"flow": flows.FLOW_ID, "node": no, "nudged": nudged}


# ── Nível 1 ─────────────────────────────────────────────────────────────────
def test_clique_quente_no_numero_da_valeria_manda_cartao():
    d = engine.decidir(estado(), Clique("Quero comprar agora", "Quero comprar agora"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem.corpo == flows.MSG_QUENTE_VALERIA
    assert d.mensagem.enviar_cartao_vendedor is True
    assert d.mensagem.botoes == ()
    assert d.efeitos.handoff is True
    assert d.efeitos.tags == (flows.TAG_QUENTE,)
    assert d.efeitos.optout is False


def test_clique_quente_no_numero_do_vendedor_nao_manda_cartao():
    d = engine.decidir(estado(), Clique("Quero comprar agora", "Quero comprar agora"),
                       canal_do_vendedor=True)
    assert d.mensagem.corpo == flows.MSG_QUENTE_VENDEDOR
    assert d.mensagem.enviar_cartao_vendedor is False
    assert d.efeitos.handoff is True


def test_clique_talvez_abre_o_nivel_2():
    d = engine.decidir(estado(), Clique("Talvez em alguns meses", "Talvez em alguns meses"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_PRAZO
    assert d.mensagem.corpo == flows.CORPO_PRAZO
    assert d.mensagem.botoes == flows.BOTOES_PRAZO
    assert d.efeitos.tags == ()
    assert d.efeitos.handoff is False


def test_clique_sair_faz_optout():
    d = engine.decidir(estado(), Clique("Não quero mais receber", "Não quero mais receber"),
                       canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem.corpo == flows.MSG_OPTOUT
    assert d.efeitos.optout is True
    assert d.efeitos.tags == (flows.TAG_RECUSOU,)


def test_clique_casa_pelo_rotulo_curto_da_interativa():
    """O nudge sai com o rótulo curto; o clique nele tem que valer o mesmo."""
    d = engine.decidir(estado(nudged=True), Clique("Sair da lista", "Sair da lista"),
                       canal_do_vendedor=False)
    assert d.efeitos.optout is True


def test_clique_do_nudge_casa_por_id():
    """O reoferecimento sai como interativa com ids nossos — tem que casar igual."""
    d = engine.decidir(estado(nudged=True), Clique("interesse_sair", "Não quero mais receber"),
                       canal_do_vendedor=False)
    assert d.efeitos.optout is True


def test_casamento_de_titulo_ignora_caixa_e_acento():
    d = engine.decidir(estado(), Clique("NAO QUERO MAIS RECEBER", "NAO QUERO MAIS RECEBER"),
                       canal_do_vendedor=False)
    assert d.efeitos.optout is True


# ── Nível 2 ─────────────────────────────────────────────────────────────────
def test_cada_prazo_grava_tag_e_meses():
    for prazo in flows.PRAZOS:
        d = engine.decidir(estado(flows.NO_PRAZO), Clique(prazo.id, prazo.titulo),
                           canal_do_vendedor=False)
        assert d.proximo_no == flows.NO_ENCERRADO
        assert d.efeitos.tags == (prazo.tag,)
        assert d.efeitos.recontato_meses == prazo.meses
        assert prazo.rotulo_humano in d.mensagem.corpo
        assert d.mensagem.botoes == ()


# ── Texto livre ─────────────────────────────────────────────────────────────
def test_texto_livre_reoferece_os_botoes_uma_vez():
    d = engine.decidir(estado(), Texto("oi, quanto custa?"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_INTERESSE
    assert d.mensagem.botoes == flows.BOTOES_INTERESSE
    assert d.mensagem.corpo == flows.CORPO_NUDGE
    assert d.marcar_nudge is True
    assert d.efeitos.tags == ()


def test_texto_livre_no_nivel_2_reoferece_os_botoes_de_prazo():
    d = engine.decidir(estado(flows.NO_PRAZO), Texto("sei lá"), canal_do_vendedor=False)
    assert d.mensagem.botoes == flows.BOTOES_PRAZO
    assert d.marcar_nudge is True


def test_segundo_texto_livre_entrega_ao_humano():
    d = engine.decidir(estado(nudged=True), Texto("me liga"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem is None
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


# ── Cliques fora do nó ──────────────────────────────────────────────────────
def test_clique_de_outro_no_e_ignorado_sem_nudge():
    """Tocar de novo no botão do nível 1 já respondido não é recusa a usar botões."""
    d = engine.decidir(estado(flows.NO_PRAZO),
                       Clique("Talvez em alguns meses", "Talvez em alguns meses"),
                       canal_do_vendedor=False)
    assert d.ignorar is True
    assert d.mensagem is None
    assert d.efeitos.tags == ()
    assert d.proximo_no == flows.NO_PRAZO
    assert d.marcar_nudge is False


def test_clique_desconhecido_cai_na_regra_de_texto_livre():
    """Botão que não pertence a nenhum nó do fluxo é tratado como texto."""
    d = engine.decidir(estado(), Clique("botao_de_outro_bot", "Sei lá"),
                       canal_do_vendedor=False)
    assert d.ignorar is False
    assert d.mensagem.botoes == flows.BOTOES_INTERESSE


# ── Estados terminais e inválidos ───────────────────────────────────────────
def test_no_encerrado_ignora_tudo():
    d = engine.decidir(estado(flows.NO_ENCERRADO), Texto("oi"), canal_do_vendedor=False)
    assert d.ignorar is True
    assert d.mensagem is None


def test_flow_de_outra_versao_devolve_ao_humano():
    d = engine.decidir({"flow": "reativacao_v0", "node": flows.NO_INTERESSE},
                       Texto("oi"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.mensagem is None
    assert d.efeitos.tags == (flows.TAG_HUMANO,)


def test_estado_vazio_comeca_no_no_inicial():
    """Primeiro inbound de uma conversa semeada por disparo: flow_state ainda é NULL."""
    d = engine.decidir(None, Clique("Quero comprar agora", "Quero comprar agora"),
                       canal_do_vendedor=False)
    assert d.efeitos.handoff is True


def test_estado_corrompido_devolve_ao_humano():
    d = engine.decidir({"node": 42}, Texto("oi"), canal_do_vendedor=False)
    assert d.proximo_no == flows.NO_ENCERRADO
    assert d.efeitos.tags == (flows.TAG_HUMANO,)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_engine_2026_08_20.py -v`
Expected: FAIL — `ImportError: cannot import name 'engine' from 'app.button_flow'`

- [ ] **Step 3: Write `engine.py`**

Create `backend/app/button_flow/engine.py`:

```python
"""Motor de decisão do bot de botões. Núcleo puro: sem banco, sem rede, sem relógio.

Recebe o estado do fluxo e um evento (clique ou texto) e devolve uma Decisao —
o que responder, o que mudar no CRM e para qual nó ir. Todo I/O fica no runner.

Mesmo contrato de app/agent/persona.py: função pura em cima de dicts, testável
com a matriz completa de casos sem nenhum mock.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from app.button_flow import flows
from app.button_flow.flows import Botao


# ── Eventos de entrada ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class Clique:
    """Clique num botão. `payload` é o id (interativa) ou o texto (template)."""
    payload: str
    titulo: str


@dataclass(frozen=True)
class Texto:
    conteudo: str


Evento = Clique | Texto


# ── Saída ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Mensagem:
    corpo: str
    botoes: tuple[Botao, ...] = ()
    enviar_cartao_vendedor: bool = False


@dataclass(frozen=True)
class Efeitos:
    tags: tuple[str, ...] = ()
    optout: bool = False
    handoff: bool = False
    recontato_meses: int | None = None


@dataclass(frozen=True)
class Decisao:
    proximo_no: str
    mensagem: Mensagem | None = None
    efeitos: Efeitos = field(default_factory=Efeitos)
    marcar_nudge: bool = False
    ignorar: bool = False


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, sem espaço nas pontas — para casar rótulo de template.

    Necessário porque quick reply de template devolve o payload igual ao TEXTO do
    botão, e o teclado do lead (ou o próprio WhatsApp) pode devolver sem acento.
    """
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.strip().lower()


# Índices de casamento, montados uma vez no import.
_POR_ID: dict[str, tuple[str, Botao]] = {
    b.id: (no, b) for no, botoes in flows.BOTOES_POR_NO.items() for b in botoes
}
# Todos os rótulos aceitos de cada botão entram no índice: um clique vindo do
# template traz o rótulo longo, um vindo do nudge traz o curto — os dois são o
# mesmo botão (ver Botao.titulos_aceitos).
_POR_TITULO: dict[str, tuple[str, Botao]] = {
    normalizar(titulo): (no, b)
    for no, botoes in flows.BOTOES_POR_NO.items()
    for b in botoes
    for titulo in b.titulos_aceitos
}


def _casar(clique: Clique) -> tuple[str, Botao] | None:
    """Resolve (nó dono, botão) de um clique. None = botão não é deste fluxo."""
    achado = _POR_ID.get(clique.payload)
    if achado:
        return achado
    achado = _POR_TITULO.get(normalizar(clique.payload))
    if achado:
        return achado
    return _POR_TITULO.get(normalizar(clique.titulo))


def _estado_valido(estado: dict | None) -> str | None:
    """Nó atual, ou None se o estado for incompatível/corrompido.

    Estado ausente (None/{}) é legítimo: é o primeiro inbound de uma conversa que
    o disparo semeou e ainda não passou pelo bot. Já um `flow` de outra versão ou
    um `node` que não existe são incompatíveis — o fluxo mudou debaixo do lead e a
    única resposta segura é devolver ao humano.
    """
    if not estado:
        return flows.NO_INTERESSE
    if estado.get("flow") != flows.FLOW_ID:
        return None
    no = estado.get("node")
    if no not in (flows.NO_INTERESSE, flows.NO_PRAZO, flows.NO_ENCERRADO):
        return None
    return no


def _nudge(no: str) -> Decisao:
    return Decisao(
        proximo_no=no,
        mensagem=Mensagem(
            corpo=flows.CORPO_NUDGE_POR_NO[no],
            botoes=flows.BOTOES_POR_NO[no],
        ),
        marcar_nudge=True,
    )


_ENTREGAR_AO_HUMANO = Decisao(
    proximo_no=flows.NO_ENCERRADO,
    efeitos=Efeitos(tags=(flows.TAG_HUMANO,)),
)


def decidir(estado: dict | None, evento: Evento, *, canal_do_vendedor: bool) -> Decisao:
    """Decide o próximo passo do fluxo. Pura: mesma entrada, mesma saída, sempre.

    `canal_do_vendedor` distingue o número do João do número da ValerIA: no número
    do próprio vendedor não faz sentido mandar o cartão de contato dele.
    """
    no = _estado_valido(estado)
    if no is None:
        return _ENTREGAR_AO_HUMANO
    if no == flows.NO_ENCERRADO:
        return Decisao(proximo_no=flows.NO_ENCERRADO, ignorar=True)

    if isinstance(evento, Clique):
        casado = _casar(evento)
        if casado:
            no_dono, botao = casado
            if no_dono != no:
                # Botão do fluxo, mas de outro nó — lead tocou duas vezes ou rolou a
                # conversa e clicou no template de novo. Ignorar é o certo: não é
                # recusa a usar botões, e reprocessar o efeito seria duplicar CRM.
                return Decisao(proximo_no=no, ignorar=True)
            return _decidir_botao(no, botao, canal_do_vendedor=canal_do_vendedor)
        # Botão que não é deste fluxo: trata como texto livre.

    nudge_ja_dado = bool((estado or {}).get("nudged"))
    return _ENTREGAR_AO_HUMANO if nudge_ja_dado else _nudge(no)


def _decidir_botao(no: str, botao: Botao, *, canal_do_vendedor: bool) -> Decisao:
    if no == flows.NO_INTERESSE:
        if botao.id == flows.BTN_QUENTE.id:
            corpo = flows.MSG_QUENTE_VENDEDOR if canal_do_vendedor else flows.MSG_QUENTE_VALERIA
            return Decisao(
                proximo_no=flows.NO_ENCERRADO,
                mensagem=Mensagem(corpo=corpo, enviar_cartao_vendedor=not canal_do_vendedor),
                efeitos=Efeitos(tags=(flows.TAG_QUENTE,), handoff=True),
            )
        if botao.id == flows.BTN_TALVEZ.id:
            return Decisao(
                proximo_no=flows.NO_PRAZO,
                mensagem=Mensagem(corpo=flows.CORPO_PRAZO, botoes=flows.BOTOES_PRAZO),
            )
        if botao.id == flows.BTN_SAIR.id:
            return Decisao(
                proximo_no=flows.NO_ENCERRADO,
                mensagem=Mensagem(corpo=flows.MSG_OPTOUT),
                efeitos=Efeitos(tags=(flows.TAG_RECUSOU,), optout=True),
            )
        # Botão declarado no nó de interesse mas sem tratamento aqui: hoje inalcançável
        # (só existem três). Cair no opt-out por fall-through seria o pior default
        # possível — um botão novo desligaria o lead da base sem ninguém pedir.
        return Decisao(proximo_no=no, ignorar=True)

    prazo = next(p for p in flows.PRAZOS if p.id == botao.id)
    return Decisao(
        proximo_no=flows.NO_ENCERRADO,
        mensagem=Mensagem(corpo=flows.MSG_PRAZO_FECHAMENTO.format(prazo=prazo.rotulo_humano)),
        efeitos=Efeitos(tags=(prazo.tag,), recontato_meses=prazo.meses),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_engine_2026_08_20.py -v`
Expected: PASS (20 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/button_flow/engine.py backend/tests/test_button_flow_engine_2026_08_20.py
git commit -m "feat(button-flow): motor de decisao puro"
```

---

## Task 4: Parser captura o payload do botão

**Files:**
- Modify: `backend/app/webhook/meta_parser.py:137-153`
- Test: `backend/tests/test_button_flow_parser_2026_08_20.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_button_flow_parser_2026_08_20.py`:

```python
"""O clique tem que chegar ao bot como CLIQUE, não como texto.

Até aqui o parser transformava clique em texto puro e jogava fora o identificador
(meta_parser.py:138-151). Sem esse identificador não dá para distinguir um lead
que TOCOU no botão de um que DIGITOU a mesma frase — e é justamente essa
diferença que torna o bot determinístico.
"""
from app.webhook.meta_parser import parse_meta_webhook_payload


def _payload(mensagem: dict) -> dict:
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "123"},
        "contacts": [{"wa_id": "5511999999999", "profile": {"name": "Fulano"}}],
        "messages": [{"from": "5511999999999", "id": "wamid.1",
                      "timestamp": "1700000000", **mensagem}],
    }}]}]}


def test_quick_reply_de_template_vira_clique_com_payload():
    msgs = parse_meta_webhook_payload(_payload({
        "type": "button",
        "button": {"payload": "Quero comprar agora", "text": "Quero comprar agora"},
    }))
    assert len(msgs) == 1
    assert msgs[0].type == "button"
    assert msgs[0].text == "Quero comprar agora"
    assert msgs[0].metadata == {"payload": "Quero comprar agora", "title": "Quero comprar agora"}


def test_button_reply_interativo_vira_clique_com_id():
    msgs = parse_meta_webhook_payload(_payload({
        "type": "interactive",
        "interactive": {"type": "button_reply",
                        "button_reply": {"id": "prazo_3m", "title": "Daqui a 3 meses"}},
    }))
    assert msgs[0].type == "button"
    assert msgs[0].metadata == {"payload": "prazo_3m", "title": "Daqui a 3 meses"}


def test_template_sem_payload_cai_no_texto_do_botao():
    """Defensivo: se a Meta omitir `payload`, o texto do botão serve de identidade."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "button", "button": {"text": "Não quero mais receber"},
    }))
    assert msgs[0].metadata["payload"] == "Não quero mais receber"


def test_list_reply_continua_texto():
    """Listas estão fora do escopo do bot — comportamento atual preservado."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "interactive",
        "interactive": {"type": "list_reply",
                        "list_reply": {"id": "x", "title": "Opção A"}},
    }))
    assert msgs[0].type == "text"
    assert msgs[0].text == "Opção A"


def test_texto_digitado_igual_ao_rotulo_nao_vira_clique():
    """A distinção que sustenta todo o determinismo do bot."""
    msgs = parse_meta_webhook_payload(_payload({
        "type": "text", "text": {"body": "Quero comprar agora"},
    }))
    assert msgs[0].type == "text"
    assert msgs[0].metadata is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_parser_2026_08_20.py -v`
Expected: FAIL — `assert 'text' == 'button'` nos dois primeiros testes

- [ ] **Step 3: Modify `meta_parser.py`**

Substitua o bloco em `backend/app/webhook/meta_parser.py` (linhas 137-153, os ramos
`elif msg_type == "button":` e `elif msg_type == "interactive":`) por:

```python
                elif msg_type == "button":
                    # Quick reply de TEMPLATE. A Meta não permite payload customizado em
                    # template — o payload chega igual ao texto do botão. O que prova que
                    # foi clique (e não digitação) é o próprio msg_type == "button".
                    btn = msg.get("button", {})
                    text = btn.get("text", "")
                    parsed_type = "button"
                    metadata_dict = {
                        "payload": btn.get("payload") or text,
                        "title": text,
                    }

                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    interactive_type = interactive.get("type", "")
                    if interactive_type == "button_reply":
                        # Mensagem interativa nossa: aqui o `id` é controlado por nós.
                        reply = interactive.get("button_reply", {})
                        text = reply.get("title", "")
                        parsed_type = "button"
                        metadata_dict = {
                            "payload": reply.get("id") or text,
                            "title": text,
                        }
                    elif interactive_type == "list_reply":
                        # Listas estão fora do escopo do bot de botões — segue como texto.
                        text = interactive.get("list_reply", {}).get("title", "")
                        parsed_type = "text"
                    else:
                        logger.info(f"Skipping unsupported interactive sub-type: {interactive_type}")
                        continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_parser_2026_08_20.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the existing parser suite for regressions**

Run: `cd backend && python -m pytest tests/ -k "parser or meta_webhook" -q`
Expected: PASS — nenhum teste existente quebrado. Se algum teste antigo esperava
`type == "text"` para clique de botão, atualize-o: o novo contrato é `type == "button"`,
e o texto visível continua sendo o título do botão.

- [ ] **Step 6: Commit**

```bash
git add backend/app/webhook/meta_parser.py backend/tests/test_button_flow_parser_2026_08_20.py
git commit -m "feat(button-flow): parser preserva o payload do botao clicado"
```

---

## Task 5: Payload atravessa o buffer

**Files:**
- Modify: `backend/app/buffer/manager.py:30` e `:40`
- Modify: `backend/app/buffer/processor.py:2225`
- Test: `backend/tests/test_button_flow_parser_2026_08_20.py` (acrescentar)

- [ ] **Step 1: Write the failing test**

Acrescente ao fim de `backend/tests/test_button_flow_parser_2026_08_20.py`:

```python
import base64
import json

from app.buffer.processor import _resolve_media


async def test_clique_atravessa_o_buffer_preservando_o_payload():
    """O buffer achata mensagens em TEXTO; metadados só sobrevivem via meta_b64.

    Mesmo mecanismo já usado por location/contact/reaction. Sem isto, o payload
    do botão morre entre o webhook e o processor.
    """
    meta = {"payload": "prazo_6m", "title": "Daqui a 6 meses"}
    b64 = base64.b64encode(json.dumps(meta).encode()).decode()

    # Assinatura real: _resolve_media(text, provider, lead_id=None, stage="")
    # → (resolved_text, media_url, message_type, document_name, metadata)
    texto, _url, tipo, _doc, metadata = await _resolve_media(
        f"[button: meta_b64={b64}]", None,
    )

    assert tipo == "button"
    assert metadata == meta
    # O texto visível no CRM é o título do botão — o vendedor precisa enxergar
    # no histórico o que o lead clicou.
    assert texto.strip() == "Daqui a 6 meses"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_parser_2026_08_20.py -k buffer -v`
Expected: FAIL — `assert None == 'button'`

- [ ] **Step 3: Modify `buffer/manager.py`**

Em `backend/app/buffer/manager.py`, na função `push_to_buffer`, troque a linha que
declara `_META_TYPES`:

```python
    # "button" entra aqui para o payload do clique sobreviver ao achatamento do
    # buffer — o bot de botões precisa distinguir clique de texto digitado.
    _META_TYPES = ("location", "contact", "reaction", "button")
```

- [ ] **Step 4: Modify `buffer/processor.py`**

Em `backend/app/buffer/processor.py`, dentro de `_resolve_media`, no laço
`for match in re.finditer(meta_b64_pattern, text):`, troque o bloco:

```python
        if meta_type in ("location", "contact", "reaction", "button") and message_type is None:
            try:
                metadata = json.loads(base64.b64decode(match.group(2)).decode())
                message_type = meta_type
                # Clique de botão: o título vira o texto visível da mensagem, para o
                # vendedor ver no histórico o que o lead tocou. Os outros meta-tipos
                # continuam sendo renderizados por _apply_media_signal.
                if meta_type == "button":
                    replacement = (metadata or {}).get("title", "")
```

Mantenha o restante do bloco (`except`, `text = text.replace(match.group(0), replacement)`)
exatamente como está.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_parser_2026_08_20.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Run the buffer suite for regressions**

Run: `cd backend && python -m pytest tests/ -k "buffer or resolve_media or reaction" -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/buffer/manager.py backend/app/buffer/processor.py backend/tests/test_button_flow_parser_2026_08_20.py
git commit -m "feat(button-flow): payload do clique sobrevive ao buffer"
```

---

## Task 6: `send_interactive_buttons` no provider

**Files:**
- Modify: `backend/app/whatsapp/base.py`
- Modify: `backend/app/whatsapp/meta.py`
- Modify: `backend/app/whatsapp/mock_provider.py`
- Test: `backend/tests/test_button_flow_provider_2026_08_20.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_button_flow_provider_2026_08_20.py`:

```python
"""Envio de mensagem interativa com botões de resposta (Meta Cloud API)."""
from unittest.mock import AsyncMock, patch

import pytest

from app.whatsapp.meta import MetaCloudClient
from app.whatsapp.mock_provider import MockProvider

CONFIG = {"phone_number_id": "123", "access_token": "tok"}
BOTOES = [("prazo_1m", "Daqui a 1 mês"), ("prazo_3m", "Daqui a 3 meses")]


async def test_meta_monta_o_payload_interativo():
    client = MetaCloudClient(CONFIG)
    with patch.object(client, "_post", new=AsyncMock(return_value={"messages": [{"id": "w1"}]})) as post:
        await client.send_interactive_buttons("5511999999999", "Quando te chamo?", BOTOES)

    enviado = post.await_args.args[0]
    assert enviado["type"] == "interactive"
    assert enviado["interactive"]["type"] == "button"
    assert enviado["interactive"]["body"]["text"] == "Quando te chamo?"
    assert enviado["interactive"]["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "prazo_1m", "title": "Daqui a 1 mês"}},
        {"type": "reply", "reply": {"id": "prazo_3m", "title": "Daqui a 3 meses"}},
    ]


async def test_meta_rejeita_resposta_sem_messages():
    """Mesma defesa de send_text: a Meta devolve 200 com erro embutido."""
    client = MetaCloudClient(CONFIG)
    with patch.object(client, "_post", new=AsyncMock(return_value={"error": {"code": 131042}})):
        with pytest.raises(RuntimeError):
            await client.send_interactive_buttons("5511999999999", "corpo", BOTOES)


async def test_meta_recusa_mais_de_tres_botoes():
    client = MetaCloudClient(CONFIG)
    with pytest.raises(ValueError):
        await client.send_interactive_buttons(
            "5511999999999", "corpo",
            [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
        )


async def test_meta_recusa_lista_vazia():
    client = MetaCloudClient(CONFIG)
    with pytest.raises(ValueError):
        await client.send_interactive_buttons("5511999999999", "corpo", [])


async def test_mock_registra_o_envio():
    mock = MockProvider({})
    res = await mock.send_interactive_buttons("5511999999999", "corpo", BOTOES)
    assert res["messages"][0]["id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_provider_2026_08_20.py -v`
Expected: FAIL — `AttributeError: 'MetaCloudClient' object has no attribute 'send_interactive_buttons'`

- [ ] **Step 3: Add the default to `base.py`**

Acrescente em `backend/app/whatsapp/base.py`, dentro de `WhatsAppProvider`, logo após
`send_reaction`:

```python
    async def send_interactive_buttons(
        self, to: str, body: str, buttons: list[tuple[str, str]]
    ) -> dict:
        """Envia uma mensagem interativa com até 3 botões de resposta.

        `buttons` é uma lista de (id, título). Como send_contact/send_reaction:
        método concreto com default não-suportado — só os provedores ativos (Meta)
        e o mock o sobrescrevem; o Evolution (descontinuado) herda este default.
        """
        raise NotImplementedError(
            f"{type(self).__name__} não suporta send_interactive_buttons"
        )
```

- [ ] **Step 4: Implement in `meta.py`**

Acrescente em `backend/app/whatsapp/meta.py`, dentro de `MetaCloudClient`, logo após
`send_reaction`:

```python
    async def send_interactive_buttons(
        self, to: str, body: str, buttons: list[tuple[str, str]]
    ) -> dict:
        """Mensagem interativa com botões de resposta (máx. 3, título ≤ 20 chars).

        Só funciona com a janela de 24h ABERTA — fora dela, a Meta exige template.
        O bot de botões só usa este caminho depois de o lead ter clicado/escrito,
        o que abre a janela.
        """
        if not 1 <= len(buttons) <= 3:
            raise ValueError(
                f"send_interactive_buttons aceita de 1 a 3 botões, recebeu {len(buttons)}"
            )
        result = await self._post({
            "messaging_product": "whatsapp",
            **_recipient_field(to),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": bid, "title": titulo}}
                        for bid, titulo in buttons
                    ]
                },
            },
        }, request_type="send_interactive_buttons")
        # Mesma defesa de send_text: a Meta devolve HTTP 200 com erro embutido.
        if not isinstance(result, dict) or "messages" not in result:
            raise RuntimeError(
                f"Meta send_interactive_buttons rejected (missing messages): {result!r}"
            )
        return result
```

- [ ] **Step 5: Implement in `mock_provider.py`**

Acrescente em `backend/app/whatsapp/mock_provider.py`, dentro de `MockProvider`, seguindo
o formato de retorno que os outros métodos do mock já usam (leia `send_text` no mesmo
arquivo e espelhe o shape do dict):

```python
    async def send_interactive_buttons(
        self, to: str, body: str, buttons: list[tuple[str, str]]
    ) -> dict:
        logger.info("[MOCK] interactive buttons → %s: %r %s", to, body, buttons)
        return {"messages": [{"id": f"mock.interactive.{to}"}]}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_provider_2026_08_20.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/app/whatsapp/ backend/tests/test_button_flow_provider_2026_08_20.py
git commit -m "feat(button-flow): send_interactive_buttons no provider Meta"
```

---

## Task 7: `effects.py` — efeitos no CRM

**Files:**
- Create: `backend/app/button_flow/effects.py`
- Test: `backend/tests/test_button_flow_effects_2026_08_20.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_button_flow_effects_2026_08_20.py`:

```python
"""Efeitos do bot no CRM. Reusa as funções existentes — nada de regra reimplementada."""
from unittest.mock import MagicMock, patch

import pytest

from app.button_flow import effects, flows
from app.button_flow.engine import Efeitos

LEAD = {"id": "lead-1", "phone": "5511999999999", "name": "Fulano", "metadata": {}}


def test_tags_sao_aplicadas_pelo_helper_existente():
    with patch("app.button_flow.effects.add_tags_to_lead") as add:
        ok = effects.aplicar(Efeitos(tags=(flows.TAG_QUENTE,)), lead=LEAD, conversation_id="c1")
    assert ok is True
    add.assert_called_once_with("lead-1", [flows.TAG_QUENTE])


def test_optout_desliga_ia_e_dispara_os_efeitos_colaterais():
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.apply_optout_side_effects") as side, \
         patch("app.button_flow.effects.append_lead_observation"), \
         patch("app.button_flow.effects.save_message"):
        ok = effects.aplicar(
            Efeitos(tags=(flows.TAG_RECUSOU,), optout=True), lead=LEAD, conversation_id="c1"
        )

    assert ok is True
    upd.assert_called_once_with("lead-1", ai_enabled=False, opt_out=True)
    side.assert_called_once_with("lead-1", "5511999999999", reason="optout")


def test_falha_ao_gravar_optout_bloqueia_o_avanco():
    """Única exceção ao fail-soft: continuar disparando p/ quem pediu p/ sair é o pior desfecho."""
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead", side_effect=RuntimeError("boom")), \
         patch("app.button_flow.effects.apply_optout_side_effects") as side, \
         patch("app.button_flow.effects.append_lead_observation"), \
         patch("app.button_flow.effects.save_message"):
        ok = effects.aplicar(Efeitos(optout=True), lead=LEAD, conversation_id="c1")

    assert ok is False
    side.assert_not_called()


def test_falha_de_tag_nao_bloqueia():
    """Fail-soft: o lead já recebeu a resposta, não pode ficar preso por uma tag."""
    with patch("app.button_flow.effects.add_tags_to_lead", side_effect=RuntimeError("boom")):
        ok = effects.aplicar(Efeitos(tags=("X",)), lead=LEAD, conversation_id="c1")
    assert ok is True


def test_handoff_desliga_ia_e_carimba_metadata():
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.append_lead_observation") as obs, \
         patch("app.button_flow.effects.save_message"):
        ok = effects.aplicar(
            Efeitos(tags=(flows.TAG_QUENTE,), handoff=True), lead=LEAD, conversation_id="c1"
        )

    assert ok is True
    chamadas = {c.kwargs.get("ai_enabled") for c in upd.call_args_list}
    assert False in chamadas
    carimbo = [c for c in upd.call_args_list if "metadata" in c.kwargs]
    assert carimbo, "handoff precisa carimbar metadata.handoff (cascata de qualificados)"
    assert carimbo[0].kwargs["metadata"]["handoff"]["vendedor"]
    obs.assert_called_once()


def test_recontato_grava_data_futura_em_metadata():
    from datetime import datetime, timezone
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.save_message"):
        effects.aplicar(Efeitos(recontato_meses=3), lead=LEAD, conversation_id="c1")

    meta = upd.call_args.kwargs["metadata"]
    quando = datetime.fromisoformat(meta["recontatar_em"])
    dias = (quando - datetime.now(timezone.utc)).days
    assert 80 <= dias <= 100, f"3 meses ≈ 90 dias, veio {dias}"


def test_sem_efeitos_nao_toca_no_banco():
    with patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.add_tags_to_lead") as add:
        assert effects.aplicar(Efeitos(), lead=LEAD, conversation_id="c1") is True
    upd.assert_not_called()
    add.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_effects_2026_08_20.py -v`
Expected: FAIL — `ImportError: cannot import name 'effects'`

- [ ] **Step 3: Write `effects.py`**

Create `backend/app/button_flow/effects.py`:

```python
"""Efeitos do bot de botões no CRM.

Toda regra de negócio aqui já existe em outro lugar — este módulo só a chama na
ordem certa. Nada é reimplementado: opt-out é o mesmo `apply_optout_side_effects`
usado pela tool do LLM e pelo endpoint manual, tag é o mesmo `add_tags_to_lead`.

Fail-soft por padrão: um erro de CRM loga e segue, porque o lead já recebeu a
resposta e não pode ficar preso. A ÚNICA exceção é o opt-out — ver `aplicar`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.agent.tools import SUPERVISOR_NAME
from app.button_flow.engine import Efeitos
from app.leads.service import (
    add_tags_to_lead,
    append_lead_observation,
    apply_optout_side_effects,
    save_message,
    update_lead,
)

logger = logging.getLogger(__name__)

# Aproximação deliberada: "3 meses" aqui é 90 dias. O lead escolheu uma faixa, não
# uma data — precisão de calendário não agrega e traria dependência de dateutil.
_DIAS_POR_MES = 30


def aplicar(efeitos: Efeitos, *, lead: dict, conversation_id: str) -> bool:
    """Aplica os efeitos da decisão. Retorna False se o fluxo NÃO deve avançar.

    Só o opt-out bloqueia: se não conseguimos gravar `opt_out=true`, avançar o nó
    encerraria o fluxo com o lead ainda elegível a disparos — exatamente o que ele
    acabou de pedir para não acontecer. O nó fica onde está e o próximo clique retenta.
    """
    lead_id = lead["id"]

    if efeitos.tags:
        try:
            add_tags_to_lead(lead_id, list(efeitos.tags))
        except Exception as exc:
            logger.warning("[BUTTON FLOW] tags %s falharam p/ lead %s: %s",
                           efeitos.tags, lead_id, exc)

    if efeitos.optout and not _aplicar_optout(lead, conversation_id):
        return False

    if efeitos.handoff:
        _aplicar_handoff(lead, conversation_id)

    if efeitos.recontato_meses:
        _agendar_recontato(lead, efeitos.recontato_meses, conversation_id)

    return True


def _aplicar_optout(lead: dict, conversation_id: str) -> bool:
    lead_id = lead["id"]
    try:
        update_lead(lead_id, ai_enabled=False, opt_out=True)
    except Exception as exc:
        logger.error(
            "[BUTTON FLOW] FALHA ao gravar opt-out do lead %s — fluxo NÃO avança: %s",
            lead_id, exc, exc_info=True,
        )
        return False

    apply_optout_side_effects(lead_id, lead.get("phone") or "", reason="optout")
    _anotar(lead_id, conversation_id,
            "🚫 [OPT-OUT] Lead clicou em 'Não quero mais receber' no bot de reativação.")
    return True


def _aplicar_handoff(lead: dict, conversation_id: str) -> None:
    """Handoff enxuto: sem resumo por LLM (não houve conversa) e sem rescue job.

    O carimbo `metadata.handoff` é o mesmo de `encaminhar_humano` — é ele que a
    cascata de Qualificados/Aceites conta, e um handoff do bot precisa aparecer lá.
    """
    lead_id = lead["id"]
    try:
        update_lead(lead_id, ai_enabled=False)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao desligar IA no handoff do lead %s: %s",
                       lead_id, exc)
    try:
        meta = dict(lead.get("metadata") or {})
        meta["handoff"] = {
            "vendedor": SUPERVISOR_NAME,
            "motivo": "bot de reativação: lead clicou em 'Quero comprar agora'",
            "at": datetime.now(timezone.utc).isoformat(),
            "origem": "button_flow",
        }
        update_lead(lead_id, metadata=meta)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao carimbar metadata.handoff do lead %s: %s",
                       lead_id, exc)
    _anotar(lead_id, conversation_id,
            f"➡️ [TRANSBORDO p/ {SUPERVISOR_NAME}] Bot de reativação: lead clicou em "
            f"'Quero comprar agora'. Nenhuma qualificação por conversa — abordar direto.")


def _agendar_recontato(lead: dict, meses: int, conversation_id: str) -> None:
    lead_id = lead["id"]
    quando = datetime.now(timezone.utc) + timedelta(days=meses * _DIAS_POR_MES)
    try:
        meta = dict(lead.get("metadata") or {})
        meta["recontatar_em"] = quando.isoformat()
        update_lead(lead_id, metadata=meta)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao gravar recontatar_em do lead %s: %s",
                       lead_id, exc)
        return
    _anotar(lead_id, conversation_id,
            f"⏰ [RECONTATO] Lead pediu contato em ~{meses} mês(es) "
            f"({quando.date().isoformat()}), via bot de reativação.")


def _anotar(lead_id: str, conversation_id: str, texto: str) -> None:
    """Observação no lead + mensagem de sistema na conversa. Fail-soft nos dois."""
    try:
        append_lead_observation(lead_id, texto)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] observação não gravada p/ lead %s: %s", lead_id, exc)
    try:
        save_message(lead_id, "system", f"[button_flow] {texto}",
                     conversation_id=conversation_id)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] mensagem de sistema não gravada p/ conv %s: %s",
                       conversation_id, exc)
```

- [ ] **Step 4: Verify the imports exist**

Run: `cd backend && python -c "from app.leads.service import add_tags_to_lead, append_lead_observation, apply_optout_side_effects, save_message, update_lead; from app.agent.tools import SUPERVISOR_NAME; print('ok')"`
Expected: `ok`

**Atenção — existem DUAS `save_message` no repositório**, com assinaturas diferentes:
`app.leads.service.save_message(lead_id, role, content, ..., conversation_id=...)` e
`app.conversations.service.save_message(conversation_id, lead_id, role, content, ...)`.
O módulo `button_flow` usa a de `app.leads.service`, a mesma que `app/agent/tools.py` usa.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_effects_2026_08_20.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/button_flow/effects.py backend/tests/test_button_flow_effects_2026_08_20.py
git commit -m "feat(button-flow): efeitos de CRM (tags, opt-out, handoff, recontato)"
```

---

## Task 8: `runner.py` — orquestração

**Files:**
- Create: `backend/app/button_flow/runner.py`
- Modify: `backend/app/agent_profiles/service.py`
- Test: `backend/tests/test_button_flow_runner_2026_08_20.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_button_flow_runner_2026_08_20.py`:

```python
"""Orquestração do bot: estado → motor → envio → efeitos → persistência."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.button_flow import flows, runner

LEAD = {"id": "lead-1", "phone": "5511999999999", "name": "Fulano", "metadata": {}}
CANAL_VALERIA = {"id": "ch-1", "phone": "5534999990000", "provider": "meta_cloud"}
CANAL_JOAO = {"id": "ch-2", "phone": "553491461669", "provider": "meta_cloud"}


def _conversa(flow_state=None) -> dict:
    return {"id": "conv-1", "lead_id": "lead-1", "channel_id": "ch-1",
            "agent_profile_id": "ap-bot", "flow_state": flow_state}


# ── is_button_flow_conversation ─────────────────────────────────────────────
def test_reconhece_conversa_de_bot():
    with patch("app.button_flow.runner.get_profile_kind", return_value="button_flow"):
        assert runner.is_button_flow_conversation(_conversa()) is True


def test_conversa_sem_perfil_nao_e_bot():
    conv = _conversa()
    conv["agent_profile_id"] = None
    assert runner.is_button_flow_conversation(conv) is False


def test_perfil_llm_nao_e_bot():
    with patch("app.button_flow.runner.get_profile_kind", return_value="llm"):
        assert runner.is_button_flow_conversation(_conversa()) is False


def test_conversa_encerrada_sai_do_bot():
    """Encerrado devolve a conversa ao fluxo normal do CRM (vendedor humano)."""
    conv = _conversa({"flow": flows.FLOW_ID, "node": flows.NO_ENCERRADO})
    with patch("app.button_flow.runner.get_profile_kind", return_value="button_flow"):
        assert runner.is_button_flow_conversation(conv) is False


def test_erro_ao_resolver_o_perfil_nao_ativa_o_bot():
    """Fail-CLOSED aqui: na dúvida, o bot NÃO sequestra a conversa."""
    with patch("app.button_flow.runner.get_profile_kind", side_effect=RuntimeError("boom")):
        assert runner.is_button_flow_conversation(_conversa()) is False


# ── run_button_flow ─────────────────────────────────────────────────────────
async def _rodar(conversa, canal, texto, metadata, message_type="button"):
    provider = AsyncMock()
    with patch("app.button_flow.runner.effects.aplicar", return_value=True) as aplicar, \
         patch("app.button_flow.runner.save_message") as save, \
         patch("app.button_flow.runner.update_conversation") as upd:
        await runner.run_button_flow(
            lead=LEAD, conversation=conversa, channel=canal, provider=provider,
            send_to="5511999999999", texto=texto,
            message_type=message_type, metadata=metadata,
        )
    return provider, aplicar, save, upd


async def test_clique_talvez_envia_botoes_de_prazo_e_grava_no():
    provider, aplicar, _save, upd = await _rodar(
        _conversa(), CANAL_VALERIA, "Talvez em alguns meses",
        {"payload": "Talvez em alguns meses", "title": "Talvez em alguns meses"},
    )
    provider.send_interactive_buttons.assert_awaited_once()
    corpo = provider.send_interactive_buttons.await_args.args[1]
    assert corpo == flows.CORPO_PRAZO
    estado = upd.call_args.kwargs["flow_state"]
    assert estado["node"] == flows.NO_PRAZO
    assert estado["flow"] == flows.FLOW_ID


async def test_clique_quente_no_numero_da_valeria_manda_texto_e_cartao():
    provider, _aplicar, _save, _upd = await _rodar(
        _conversa(), CANAL_VALERIA, "Quero comprar agora",
        {"payload": "Quero comprar agora", "title": "Quero comprar agora"},
    )
    provider.send_text.assert_awaited_once()
    provider.send_contact.assert_awaited_once()


async def test_clique_quente_no_numero_do_joao_nao_manda_cartao():
    provider, _aplicar, _save, _upd = await _rodar(
        _conversa(), CANAL_JOAO, "Quero comprar agora",
        {"payload": "Quero comprar agora", "title": "Quero comprar agora"},
    )
    provider.send_text.assert_awaited_once()
    provider.send_contact.assert_not_awaited()


async def test_texto_livre_reoferece_botoes_e_marca_nudge():
    provider, _aplicar, _save, upd = await _rodar(
        _conversa(), CANAL_VALERIA, "quanto custa?", None, message_type="text",
    )
    provider.send_interactive_buttons.assert_awaited_once()
    assert upd.call_args.kwargs["flow_state"]["nudged"] is True


async def test_falha_de_envio_nao_avanca_o_no():
    """O lead precisa poder clicar de novo — o estado tem que ficar onde estava."""
    provider = AsyncMock()
    provider.send_interactive_buttons.side_effect = RuntimeError("meta fora")
    with patch("app.button_flow.runner.effects.aplicar", return_value=True), \
         patch("app.button_flow.runner.save_message"), \
         patch("app.button_flow.runner.update_conversation") as upd:
        await runner.run_button_flow(
            lead=LEAD, conversation=_conversa(), channel=CANAL_VALERIA, provider=provider,
            send_to="5511999999999", texto="Talvez em alguns meses",
            message_type="button",
            metadata={"payload": "Talvez em alguns meses", "title": "Talvez em alguns meses"},
        )
    upd.assert_not_called()


async def test_optout_que_falhou_nao_avanca_o_no():
    provider = AsyncMock()
    with patch("app.button_flow.runner.effects.aplicar", return_value=False), \
         patch("app.button_flow.runner.save_message"), \
         patch("app.button_flow.runner.update_conversation") as upd:
        await runner.run_button_flow(
            lead=LEAD, conversation=_conversa(), channel=CANAL_VALERIA, provider=provider,
            send_to="5511999999999", texto="Não quero mais receber",
            message_type="button",
            metadata={"payload": "Não quero mais receber", "title": "Não quero mais receber"},
        )
    upd.assert_not_called()


async def test_clique_de_outro_no_nao_envia_nem_grava():
    conv = _conversa({"flow": flows.FLOW_ID, "node": flows.NO_PRAZO, "nudged": False})
    provider, aplicar, _save, upd = await _rodar(
        conv, CANAL_VALERIA, "Talvez em alguns meses",
        {"payload": "Talvez em alguns meses", "title": "Talvez em alguns meses"},
    )
    provider.send_text.assert_not_awaited()
    provider.send_interactive_buttons.assert_not_awaited()
    aplicar.assert_not_called()
    upd.assert_not_called()


async def test_resposta_do_bot_e_persistida_na_conversa():
    """O vendedor precisa ver no histórico o que o bot respondeu."""
    _provider, _aplicar, save, _upd = await _rodar(
        _conversa(), CANAL_VALERIA, "Quero comprar agora",
        {"payload": "Quero comprar agora", "title": "Quero comprar agora"},
    )
    papeis = [c.args[1] for c in save.call_args_list]
    assert "assistant" in papeis
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_runner_2026_08_20.py -v`
Expected: FAIL — `ImportError: cannot import name 'runner'`

- [ ] **Step 3: Add `get_profile_kind` to `agent_profiles/service.py`**

Acrescente ao fim de `backend/app/agent_profiles/service.py`:

```python
def get_profile_kind(profile_id: str | None) -> str:
    """Tipo do agente: 'llm' (orquestrador Gemini) ou 'button_flow' (fluxo de botões).

    Levanta em caso de erro — de propósito. O chamador (runner) trata a exceção
    como "não é bot" e segue o fluxo normal: na dúvida, o bot NUNCA sequestra a
    conversa. Um fail-open silencioso aqui poderia calar a ValerIA.

    Retorna 'llm' quando a coluna `kind` ainda não existe (migração não aplicada),
    o que mantém o código novo inerte até o SQL rodar no Supabase.
    """
    if not profile_id:
        return "llm"
    sb = get_supabase()
    result = (
        sb.table("agent_profiles")
        .select("kind")
        .eq("id", profile_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return "llm"
    return result.data[0].get("kind") or "llm"
```

- [ ] **Step 4: Write `runner.py`**

Create `backend/app/button_flow/runner.py`:

```python
"""Orquestração do bot de botões: a única camada com I/O do fluxo.

Sequência de um turno:
  1. lê `conversations.flow_state`
  2. traduz o inbound em Clique ou Texto
  3. chama `engine.decidir` (puro)
  4. envia a resposta (texto, texto+botões, cartão de contato)
  5. aplica os efeitos de CRM
  6. só então grava o novo estado

A ordem 4→5→6 é deliberada: o estado só avança quando a resposta chegou ao lead E
os efeitos que não podem falhar deram certo. Se qualquer um dos dois falhar, o nó
fica onde estava e o próximo clique do lead retenta o mesmo passo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.agent.tools import SUPERVISOR_NAME, SUPERVISOR_PHONE
from app.agent_profiles.service import get_profile_kind
from app.button_flow import effects, flows
from app.button_flow.engine import Clique, Decisao, Texto, decidir
from app.conversations.service import update_conversation
from app.leads.service import normalize_phone, save_message

logger = logging.getLogger(__name__)


def is_button_flow_conversation(conversation: dict) -> bool:
    """True quando esta conversa deve ser atendida pelo bot de botões.

    Fail-CLOSED: qualquer erro devolve False. O custo de um falso negativo é o bot
    não responder um turno; o de um falso positivo é o bot calar a ValerIA numa
    conversa de venda.
    """
    profile_id = conversation.get("agent_profile_id")
    if not profile_id:
        return False
    estado = conversation.get("flow_state") or {}
    if estado.get("node") == flows.NO_ENCERRADO:
        return False
    try:
        return get_profile_kind(profile_id) == "button_flow"
    except Exception as exc:
        logger.warning(
            "[BUTTON FLOW] não foi possível resolver o kind do perfil %s (segue fluxo normal): %s",
            profile_id, exc,
        )
        return False


def _canal_do_vendedor(channel: dict) -> bool:
    """O disparo saiu pelo próprio número do João? Então não há para onde transferir."""
    return normalize_phone(channel.get("phone") or "") == normalize_phone(SUPERVISOR_PHONE)


def _evento(texto: str, message_type: str | None, metadata: dict | None):
    if message_type == "button" and metadata:
        return Clique(
            payload=metadata.get("payload") or "",
            titulo=metadata.get("title") or texto or "",
        )
    return Texto(conteudo=texto or "")


async def _enviar(decisao: Decisao, *, provider, send_to: str,
                  lead_id: str, conversation_id: str) -> bool:
    """Envia a resposta da decisão. False = falhou (o nó não deve avançar)."""
    mensagem = decisao.mensagem
    if mensagem is None:
        return True
    try:
        if mensagem.botoes:
            await provider.send_interactive_buttons(
                send_to, mensagem.corpo,
                [(b.id, b.titulo) for b in mensagem.botoes],
            )
        else:
            await provider.send_text(send_to, mensagem.corpo)
    except Exception as exc:
        logger.error(
            "[BUTTON FLOW] falha ao enviar resposta p/ conv %s — nó NÃO avança: %s",
            conversation_id, exc, exc_info=True,
        )
        return False

    try:
        save_message(lead_id, "assistant", mensagem.corpo,
                     sent_by="button_flow", conversation_id=conversation_id)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] resposta não persistida p/ conv %s: %s",
                       conversation_id, exc)

    if mensagem.enviar_cartao_vendedor:
        # Fail-soft: o cartão é um atalho. Sem ele o handoff continua válido.
        try:
            await provider.send_contact(send_to, contact_name=SUPERVISOR_NAME,
                                        contact_phone=SUPERVISOR_PHONE)
        except Exception as exc:
            logger.warning("[BUTTON FLOW] cartão do vendedor não enviado p/ conv %s: %s",
                           conversation_id, exc)
    return True


def _gravar_estado(conversation: dict, decisao: Decisao) -> None:
    estado_anterior = conversation.get("flow_state") or {}
    novo = {
        "flow": flows.FLOW_ID,
        "node": decisao.proximo_no,
        "nudged": bool(estado_anterior.get("nudged")) or decisao.marcar_nudge,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        # update_conversation recebe os campos por KWARGS, nao um dict.
        update_conversation(conversation["id"], flow_state=novo)
        conversation["flow_state"] = novo
    except Exception as exc:
        logger.error("[BUTTON FLOW] falha ao gravar flow_state da conv %s: %s",
                     conversation["id"], exc, exc_info=True)


async def run_button_flow(*, lead: dict, conversation: dict, channel: dict, provider,
                          send_to: str, texto: str, message_type: str | None,
                          metadata: dict | None) -> None:
    """Roda um turno do bot. Nunca levanta — o turno da conversa não pode cair."""
    conversation_id = conversation["id"]
    decisao = decidir(
        conversation.get("flow_state"),
        _evento(texto, message_type, metadata),
        canal_do_vendedor=_canal_do_vendedor(channel),
    )

    if decisao.ignorar:
        logger.info(
            "[BUTTON FLOW] evento ignorado na conv %s (nó=%s) — clique fora do nó atual "
            "ou fluxo encerrado", conversation_id, decisao.proximo_no,
        )
        return

    if not await _enviar(decisao, provider=provider, send_to=send_to,
                         lead_id=lead["id"], conversation_id=conversation_id):
        return

    if not effects.aplicar(decisao.efeitos, lead=lead, conversation_id=conversation_id):
        logger.error(
            "[BUTTON FLOW] efeito bloqueante falhou na conv %s — nó NÃO avança",
            conversation_id,
        )
        return

    _gravar_estado(conversation, decisao)
    logger.info("[BUTTON FLOW] conv %s → nó %s", conversation_id, decisao.proximo_no)
```

- [ ] **Step 5: Verify the imports exist**

Run: `cd backend && python -c "from app.conversations.service import update_conversation; from app.leads.service import normalize_phone, save_message; from app.agent.tools import SUPERVISOR_NAME, SUPERVISOR_PHONE; print('ok')"`
Expected: `ok`

Lembrete de assinatura: `update_conversation(conversation_id, **fields)` recebe os campos
por **kwargs**, não um dict — por isso `update_conversation(conv_id, flow_state=novo)` e
não `update_conversation(conv_id, {"flow_state": novo})`.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_runner_2026_08_20.py -v`
Expected: PASS (13 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/app/button_flow/runner.py backend/app/agent_profiles/service.py backend/tests/test_button_flow_runner_2026_08_20.py
git commit -m "feat(button-flow): runner de orquestracao do fluxo"
```

---

## Task 9: Gate no processor

**Files:**
- Modify: `backend/app/buffer/processor.py` (logo após o gate de reação isolada, ~linha 1409)
- Test: `backend/tests/test_button_flow_gate_2026_08_20.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_button_flow_gate_2026_08_20.py`:

```python
"""Posição do gate do bot dentro do processor.

A posição é o coração do requisito "funcionar nos dois números": o gate fica ANTES
do gate de canal humano (processor.py:~1418), que é o que impede a ValerIA de
responder no número do João. Um fluxo fechado de botões não é IA generativa, então
pode rodar ali sem abrir aquele número para o LLM.

Mocks espelham tests/test_processor_mark_read_gating_2026_07_03.py.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.button_flow import flows

LEAD = {"id": "lead-1", "phone": "+5511999999999", "stage": "secretaria",
        "status": "active", "ai_enabled": True, "name": "Fulano", "metadata": {}}


def _channel(mode: str = "ai") -> dict:
    return {"id": "ch-1", "is_active": True, "mode": mode, "phone": "5534999990000",
            "provider": "meta_cloud", "agent_profiles": {"id": "p1", "stages": {}},
            "provider_config": {"phone_number_id": "123", "access_token": "tok"}}


def _conversation(profile_id: str | None = "ap-bot", flow_state=None) -> dict:
    return {"id": "conv-1", "lead_id": "lead-1", "channel_id": "ch-1",
            "stage": "secretaria", "status": "active",
            "agent_profile_id": profile_id, "flow_state": flow_state}


def _patches(channel, conversation):
    return [
        patch("app.buffer.processor.get_or_create_lead", return_value=LEAD),
        patch("app.buffer.processor.get_channel_by_id", return_value=channel),
        patch("app.buffer.processor.get_or_create_conversation", return_value=conversation),
        patch("app.buffer.processor.get_active_enrollment", return_value=None),
        patch("app.buffer.processor.save_message"),
        patch("app.buffer.processor.run_agent") as _agent,
        patch("app.buffer.processor._is_recent_duplicate", return_value=False),
        patch("app.buffer.processor._wamid_already_processed", return_value=False),
        patch("app.buffer.processor._get_buffer_redis", side_effect=RuntimeError("sem redis")),
        patch("app.buffer.processor.update_conversation"),
    ]


async def _processar(channel, conversation, texto="Quero comprar agora"):
    from contextlib import ExitStack
    from app.buffer.processor import process_buffered_messages

    with ExitStack() as stack:
        for p in _patches(channel, conversation):
            stack.enter_context(p)
        mock_run = stack.enter_context(
            patch("app.buffer.processor.run_button_flow", new=AsyncMock()))
        mock_agent = stack.enter_context(patch("app.buffer.processor.run_agent"))
        stack.enter_context(patch("app.buffer.processor.get_provider",
                                  return_value=AsyncMock()))
        await process_buffered_messages("+5511999999999", texto, "ch-1", wamid="wamid.1")
    return mock_run, mock_agent


async def test_bot_roda_em_canal_humano():
    """O requisito central: o bot funciona no número do João."""
    with patch("app.buffer.processor.is_button_flow_conversation", return_value=True):
        mock_run, mock_agent = await _processar(_channel("human"), _conversation())
    mock_run.assert_awaited_once()
    mock_agent.assert_not_called()


async def test_bot_roda_em_canal_ai():
    with patch("app.buffer.processor.is_button_flow_conversation", return_value=True):
        mock_run, mock_agent = await _processar(_channel("ai"), _conversation())
    mock_run.assert_awaited_once()
    mock_agent.assert_not_called()


async def test_conversa_normal_em_canal_humano_continua_bloqueada():
    """A exceção vale SÓ para o bot — a ValerIA segue muda no número do João."""
    with patch("app.buffer.processor.is_button_flow_conversation", return_value=False):
        mock_run, mock_agent = await _processar(_channel("human"), _conversation(None))
    mock_run.assert_not_awaited()
    mock_agent.assert_not_called()


async def test_conversa_de_bot_encerrada_nao_roda_o_bot():
    encerrada = _conversation(flow_state={"flow": flows.FLOW_ID, "node": flows.NO_ENCERRADO})
    with patch("app.buffer.processor.is_button_flow_conversation", return_value=False):
        mock_run, _agent = await _processar(_channel("ai"), encerrada)
    mock_run.assert_not_awaited()


async def test_reacao_isolada_nao_aciona_o_bot():
    """Reação não é turno — o gate de reação precede o do bot."""
    with patch("app.buffer.processor.is_button_flow_conversation", return_value=True):
        mock_run, _agent = await _processar(
            _channel("ai"), _conversation(), texto="[O lead reagiu com ❤️]")
    mock_run.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_gate_2026_08_20.py -v`
Expected: FAIL — `AttributeError: <module 'app.buffer.processor'> does not have the attribute 'run_button_flow'`

- [ ] **Step 3: Add the import to `processor.py`**

Junto aos outros imports no topo de `backend/app/buffer/processor.py`, acrescente:

```python
from app.button_flow.runner import is_button_flow_conversation, run_button_flow
```

- [ ] **Step 4: Insert the gate**

Em `backend/app/buffer/processor.py`, dentro de `process_buffered_messages`,
**imediatamente após** o bloco do gate de reação isolada (que termina com
`_update_last_msg(conversation["id"])` / `return`, por volta da linha 1415) e
**imediatamente antes** do comentário `# Channel-level gate: human channels never run AI`,
insira:

```python
    # Bot de botões (agente kind='button_flow'): fluxo determinístico, sem LLM.
    # Roda ANTES do gate de canal humano DE PROPÓSITO — é o que faz o bot funcionar
    # no número do João sem abrir aquele número para a ValerIA. O gate de canal
    # humano logo abaixo continua intacto para o LLM.
    #
    # Também fica antes de _resolve_agent_profile_id (Eixo 1, ~linha 1505): aquela
    # função recomputa a persona pelo histórico e sobrescreveria o perfil fixado
    # pelo disparo — um disparo do bot é classificado como cold_reactivation e
    # cairia em valeria_outbound. Com o gate aqui, não há conflito.
    if is_button_flow_conversation(conversation):
        try:
            await run_button_flow(
                lead=lead, conversation=conversation, channel=channel,
                provider=provider, send_to=resolve_send_target(lead, phone),
                texto=resolved_text, message_type=_message_type, metadata=_metadata,
            )
        except Exception as exc:
            logger.error(
                "[BUTTON FLOW] turno falhou na conv %s (conversa segue no CRM): %s",
                conversation["id"], exc, exc_info=True,
            )
        _update_last_msg(conversation["id"])
        return
```

- [ ] **Step 5: Confirm the scope**

`provider` já está atribuído em `processor.py:1249` (`provider = get_provider(channel)`) e
`resolve_send_target` já está importado no topo (`processor.py:16`) — ambos estão em escopo
no ponto de inserção. Confirme:

Run: `cd backend && grep -n "resolve_send_target\|provider = get_provider" app/buffer/processor.py | head -5`
Expected: `16:    get_or_create_lead, resolve_send_target, ...` e `1249:        provider = get_provider(channel)`

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_gate_2026_08_20.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Run the whole processor suite for regressions**

Run: `cd backend && python -m pytest tests/ -k "processor" -q`
Expected: PASS — nenhum teste existente quebrado.

- [ ] **Step 8: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_button_flow_gate_2026_08_20.py
git commit -m "feat(button-flow): gate do bot antes do gate de canal humano"
```

---

## Task 10: Preflight do disparo

**Files:**
- Modify: `backend/app/templates/preflight.py`
- Modify: `backend/app/broadcast/router.py` (chamada do preflight no `/start`)
- Test: `backend/tests/test_button_flow_preflight_2026_08_20.py`

Contexto já verificado, não precisa reinvestigar:
`validate_template_for_broadcast(template_name, template_language_code, template_variables, channel) -> list[str]`
(`preflight.py:250`) devolve uma **lista de erros em PT-BR** (vazia = liberado) e é chamada
em `broadcast/router.py:233`, cujo bloco seguinte levanta `HTTPException(400)` quando a lista
não é vazia. O kill-switch `PREFLIGHT_TEMPLATE=off` desliga o gate inteiro — e o `conftest.py`
já o deixa `off` na suíte, então os testes da checagem pura não passam por ele.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_button_flow_preflight_2026_08_20.py`:

```python
"""Pareamento bot x template: sem os 3 botoes certos, o disparo nao pode sair.

Sem esta checagem o operador consegue elencar o Bot Reativacao com um template
sem botoes e disparar para 1.208 leads num fluxo que nunca avanca — e cada envio
consome uma janela de conversa paga.
"""
import pytest

from app.button_flow import flows
from app.templates.preflight import checar_template_do_button_flow

BOTOES_OK = [{"type": "QUICK_REPLY", "text": t} for t in flows.ROTULOS_TEMPLATE_NIVEL1]


def _componentes(botoes=None):
    comps = [{"type": "BODY", "text": "Oi {{1}}, faz um tempo..."}]
    if botoes is not None:
        comps.append({"type": "BUTTONS", "buttons": botoes})
    return comps


def test_template_correto_passa():
    assert checar_template_do_button_flow(_componentes(BOTOES_OK)) == []


def test_template_sem_componente_de_botoes_e_rejeitado():
    erros = checar_template_do_button_flow(_componentes(None))
    assert len(erros) == 1 and "BUTTONS" in erros[0]


def test_template_com_rotulos_errados_e_rejeitado():
    erros = checar_template_do_button_flow(_componentes(
        [{"type": "QUICK_REPLY", "text": "Sim"}, {"type": "QUICK_REPLY", "text": "Nao"}]
    ))
    assert erros
    assert flows.ROTULOS_TEMPLATE_NIVEL1[0] in erros[0]


def test_ordem_dos_botoes_nao_importa():
    """O que casa o clique e o texto, nao a posicao."""
    assert checar_template_do_button_flow(_componentes(list(reversed(BOTOES_OK)))) == []


def test_acento_e_caixa_nao_importam():
    quase = [{"type": "QUICK_REPLY", "text": t.upper()} for t in flows.ROTULOS_TEMPLATE_NIVEL1]
    assert checar_template_do_button_flow(_componentes(quase)) == []


def test_botao_extra_e_rejeitado():
    assert checar_template_do_button_flow(
        _componentes(BOTOES_OK + [{"type": "QUICK_REPLY", "text": "Outro"}])
    )


def test_type_do_componente_e_case_insensitive():
    """preflight._component_type ja normaliza para maiuscula — nao regredir."""
    comps = [{"type": "buttons", "buttons": BOTOES_OK}]
    assert checar_template_do_button_flow(comps) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_button_flow_preflight_2026_08_20.py -v`
Expected: FAIL — `ImportError: cannot import name 'checar_template_do_button_flow'`

- [ ] **Step 3: Add the pure check to `preflight.py`**

Acrescente em `backend/app/templates/preflight.py`, logo antes de
`async def validate_template_for_broadcast`:

```python
def checar_template_do_button_flow(components: list) -> list[str]:
    """Valida que o template tem exatamente os botoes que o bot de botoes sabe casar.

    Retorna lista de erros (vazia = liberado), no mesmo contrato das demais checagens
    deste modulo. Funcao pura: quem levanta o HTTPException e o router.

    Existe porque os rotulos vivem em DOIS lugares — no template aprovado na Meta e em
    app/button_flow/flows.py. Divergindo, o clique do lead nunca casa: o disparo sai,
    queima janela paga em cada lead e nao qualifica ninguem.
    """
    from app.button_flow.engine import normalizar
    from app.button_flow.flows import ROTULOS_TEMPLATE_NIVEL1

    esperado_txt = ", ".join(ROTULOS_TEMPLATE_NIVEL1)
    bloco = next((c for c in components or [] if _component_type(c) == "BUTTONS"), None)
    if not bloco or not bloco.get("buttons"):
        return [
            f"o agente 'Bot Reativacao' exige um template com componente BUTTONS "
            f"contendo exatamente estes botoes: {esperado_txt}"
        ]

    encontrados = [b.get("text", "") for b in bloco["buttons"]]
    if {normalizar(t) for t in encontrados} != {normalizar(r) for r in ROTULOS_TEMPLATE_NIVEL1}:
        return [
            f"os botoes do template nao batem com o fluxo do 'Bot Reativacao' — "
            f"esperado: {esperado_txt}; encontrado: {', '.join(encontrados)}"
        ]
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_button_flow_preflight_2026_08_20.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Add the parameter to `validate_template_for_broadcast`**

Em `backend/app/templates/preflight.py`, acrescente um parâmetro opcional na assinatura
(`preflight.py:250`), mantendo os quatro existentes na mesma ordem:

```python
async def validate_template_for_broadcast(
    template_name: str,
    template_language_code: str,
    template_variables: dict | None,
    channel: dict | None,
    agent_profile_kind: str | None = None,
) -> list[str]:
```

E, no fim da função, **antes** do `return errors`, acrescente a checagem:

```python
    # Checagem 5: pareamento bot x template. So se aplica quando o disparo foi
    # elencado para um agente de fluxo de botoes — o template precisa carregar os
    # botoes que o motor sabe casar.
    if agent_profile_kind == "button_flow":
        errors.extend(checar_template_do_button_flow(components))
```

Acrescente ao mesmo arquivo de teste:

```python
async def test_validate_ignora_a_checagem_quando_o_agente_nao_e_bot(monkeypatch):
    """Disparo normal (ValerIA) nao passa pela checagem de botoes."""
    monkeypatch.setenv("PREFLIGHT_TEMPLATE", "on")
    from app.templates import preflight

    variante = {"status": "approved", "language": "pt_BR",
                "components": _componentes(None), "source": "local"}
    monkeypatch.setattr(preflight, "_lookup_local", lambda nome: [variante])
    monkeypatch.setattr(preflight, "_normalize_variants", lambda rows, src: [variante])

    erros = await preflight.validate_template_for_broadcast(
        "reativacao_v1", "pt_BR", {}, None, agent_profile_kind=None,
    )
    assert not any("Bot Reativacao" in e for e in erros)


async def test_validate_bloqueia_bot_com_template_sem_botoes(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_TEMPLATE", "on")
    from app.templates import preflight

    variante = {"status": "approved", "language": "pt_BR",
                "components": _componentes(None), "source": "local"}
    monkeypatch.setattr(preflight, "_lookup_local", lambda nome: [variante])
    monkeypatch.setattr(preflight, "_normalize_variants", lambda rows, src: [variante])

    erros = await preflight.validate_template_for_broadcast(
        "reativacao_v1", "pt_BR", {}, None, agent_profile_kind="button_flow",
    )
    assert any("Bot Reativacao" in e for e in erros)
```

Se `_lookup_local`/`_normalize_variants` tiverem nomes diferentes no arquivo, use os nomes
reais — o que os testes precisam garantir é que a variante aprovada devolvida tenha
`components` sem BUTTONS, e que a checagem 5 rode (ou não) conforme `agent_profile_kind`.

- [ ] **Step 6: Wire it in `broadcast/router.py`**

Em `backend/app/broadcast/router.py`, no bloco do `/start` que chama
`validate_template_for_broadcast` (por volta da linha 233), resolva o tipo do agente antes
e passe adiante:

```python
    # Tipo do agente elencado no disparo: um bot de botoes exige template com os
    # botoes do fluxo (checagem 5 do preflight). Fail-soft na resolucao — se nao
    # der para saber o tipo, o preflight roda como antes, sem a checagem extra.
    agent_profile_kind = None
    try:
        from app.agent_profiles.service import get_profile_kind
        agent_profile_kind = get_profile_kind(broadcast.get("agent_profile_id"))
    except Exception:
        agent_profile_kind = None

    preflight_errors = await validate_template_for_broadcast(
        broadcast.get("template_name"),
        broadcast.get("template_language_code", "pt_BR"),
        broadcast.get("template_variables") or {},
        channel,
        agent_profile_kind,
    )
```

- [ ] **Step 7: Run the templates and broadcast suites for regressions**

Run: `cd backend && python -m pytest tests/ -k "preflight or template or broadcast" -q`
Expected: PASS — nenhum teste existente quebrado. Os testes antigos chamam
`validate_template_for_broadcast` com quatro argumentos; o quinto tem default `None`,
então continuam valendo.

- [ ] **Step 8: Commit**

```bash
git add backend/app/templates/preflight.py backend/app/broadcast/router.py backend/tests/test_button_flow_preflight_2026_08_20.py
git commit -m "feat(button-flow): preflight barra template sem os botoes do fluxo"
```

---


## Task 11: Frontend — seletor de agente

**Files:**
- Create: `frontend/src/lib/agent-picker.ts`
- Create: `frontend/src/lib/agent-picker.test.ts`
- Modify: `frontend/src/lib/types.ts` (interface `AgentProfile`)
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx:692-735`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/agent-picker.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { agentesDisponiveis, ehBotDeBotoes } from "./agent-picker";
import type { AgentProfile } from "./types";

const valeria = { id: "a1", name: "ValerIA - Inbound", kind: "llm" } as AgentProfile;
const outbound = { id: "a2", name: "ValerIA - Outbound", kind: "llm" } as AgentProfile;
const bot = { id: "a3", name: "Bot Reativação", kind: "button_flow" } as AgentProfile;
const todos = [valeria, outbound, bot];

describe("agentesDisponiveis", () => {
  it("num canal de IA, oferece todos os agentes", () => {
    expect(agentesDisponiveis(todos, "ai")).toEqual(todos);
  });

  it("num canal humano, oferece SÓ bots de botões", () => {
    // O backend só abre exceção ao gate de canal humano para button_flow;
    // oferecer a ValerIA aqui seria mentir para o operador.
    expect(agentesDisponiveis(todos, "human")).toEqual([bot]);
  });

  it("trata mode ausente como 'ai' (default do banco)", () => {
    expect(agentesDisponiveis(todos, undefined)).toEqual(todos);
  });

  it("trata kind ausente como 'llm' (migração não aplicada)", () => {
    const legado = { id: "a4", name: "Antigo" } as AgentProfile;
    expect(agentesDisponiveis([legado], "human")).toEqual([]);
    expect(agentesDisponiveis([legado], "ai")).toEqual([legado]);
  });

  it("devolve lista vazia sem estourar quando não há agentes", () => {
    expect(agentesDisponiveis([], "human")).toEqual([]);
  });
});

describe("ehBotDeBotoes", () => {
  it("identifica o bot", () => {
    expect(ehBotDeBotoes(bot)).toBe(true);
    expect(ehBotDeBotoes(valeria)).toBe(false);
    expect(ehBotDeBotoes(undefined)).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/agent-picker.test.ts`
Expected: FAIL — `Cannot find module './agent-picker'`

- [ ] **Step 3: Write `agent-picker.ts`**

Create `frontend/src/lib/agent-picker.ts`:

```typescript
import type { AgentProfile } from "./types";

/**
 * Regra de quais agentes o modal de disparo pode oferecer, por modo do canal.
 *
 * Espelha exatamente o gate do backend (buffer/processor.py): num canal
 * `mode='human'` só um agente `kind='button_flow'` chega a rodar — o gate de canal
 * humano continua barrando o LLM. Oferecer a ValerIA ali criaria um disparo que
 * sai e depois nunca responde.
 *
 * `kind` ausente é tratado como "llm": até a migração 20260820 ser aplicada no
 * Supabase, nenhum perfil tem a coluna.
 */
export function agentesDisponiveis(
  perfis: AgentProfile[],
  modoDoCanal: string | undefined,
): AgentProfile[] {
  if ((modoDoCanal ?? "ai") !== "human") return perfis;
  return perfis.filter(ehBotDeBotoes);
}

export function ehBotDeBotoes(perfil: AgentProfile | undefined | null): boolean {
  return perfil?.kind === "button_flow";
}
```

- [ ] **Step 4: Add `kind` to `AgentProfile`**

Em `frontend/src/lib/types.ts`, na interface `AgentProfile`, acrescente:

```typescript
  /** 'llm' = orquestrador Gemini; 'button_flow' = bot determinístico de botões. */
  kind?: "llm" | "button_flow";
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/agent-picker.test.ts`
Expected: PASS (6 passed)

- [ ] **Step 6: Wire it into the modal**

Em `frontend/src/components/campaigns/create-broadcast-modal.tsx`:

Importe no topo:

```typescript
import { agentesDisponiveis, ehBotDeBotoes } from "@/lib/agent-picker";
```

Troque a condição que esconde o bloco inteiro em canal humano —
`{selectedChannel?.mode !== "human" && (` — por uma que use a lista filtrada. Calcule
antes do `return`:

```typescript
  // Em canal humano só o bot de botões roda (ver agent-picker.ts). Sem agente
  // disponível, o bloco some — é o comportamento antigo, agora pelo motivo certo.
  const perfisOferecidos = agentesDisponiveis(agentProfiles, selectedChannel?.mode);
```

e use `{perfisOferecidos.length > 0 && (` como condição do bloco. Dentro do `<select>`
de `agentMode === "specific"`, itere sobre `perfisOferecidos` em vez de `agentProfiles`,
e marque visualmente o bot:

```tsx
                        {perfisOferecidos.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}{ehBotDeBotoes(a) ? " (bot de botões)" : ""}
                          </option>
                        ))}
```

Em canal humano, "Agente padrão do canal" não faz sentido (o default é a ValerIA, que não
roda ali): esconda essa opção do rádio quando `selectedChannel?.mode === "human"`.

- [ ] **Step 7: Run the frontend suite for regressions**

Run: `cd frontend && npm test`
Expected: PASS — nenhum teste existente quebrado.

- [ ] **Step 8: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: sem erros.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/agent-picker.ts frontend/src/lib/agent-picker.test.ts frontend/src/lib/types.ts frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(button-flow): seletor de agente oferece o bot em canal humano"
```

---

## Task 12: Verificação final

**Files:** nenhum (só verificação)

- [ ] **Step 1: Run the entire backend suite**

Run: `cd backend && python -m pytest -q`
Expected: todos passando. Anote o número de testes. **Se qualquer teste falhar, conserte
antes de seguir** — não marque a task como completa com a suíte vermelha.

- [ ] **Step 2: Run the entire frontend suite**

Run: `cd frontend && npm test`
Expected: todos passando.

- [ ] **Step 3: Type-check both sides**

Run: `cd frontend && npx tsc --noEmit`
Expected: sem erros.

Run: `cd backend && python -c "import app.main; print('import ok')"`
Expected: `import ok` — garante que nenhum import novo criou ciclo.

- [ ] **Step 4: Confirm the code is inert before the migration**

Run: `cd backend && grep -rn "kind" app/agent_profiles/service.py`

Confirme que `get_profile_kind` devolve `'llm'` quando a coluna não existe ou o perfil
não é encontrado. Esse é o contrato que permite subir o código antes de aplicar o SQL:
sem nenhum perfil `button_flow`, `is_button_flow_conversation` sempre devolve False e o
comportamento do sistema não muda em nada.

- [ ] **Step 5: Write the operator handoff doc**

Create `docs/setup/bot-botoes-reativacao.md` com, no mínimo:

1. Rodar `supabase/migrations/20260820_button_flow_agent.sql` no Supabase (SQL Editor).
2. Criar e aprovar na Meta um template de reativação **UTILITY** com um componente
   BUTTONS contendo exatamente os três rótulos: `Quero comprar agora`,
   `Talvez em alguns meses`, `Não quero mais receber`.
3. Em `/campanhas`, criar o disparo escolhendo o canal, o agente **Bot Reativação** e
   esse template.
4. Teste ao vivo com **um** número antes do lote: clicar em cada um dos três botões em
   três conversas diferentes e conferir no CRM as tags, o opt-out e o handoff.
5. Só então disparar o lote.

- [ ] **Step 6: Commit**

```bash
git add docs/setup/bot-botoes-reativacao.md
git commit -m "docs(button-flow): passo a passo de ativacao para o operador"
```

---

## Fora deste plano

A **Fase 2 — re-disparo automático na data** (seção 10 da spec) é uma entrega separada,
depois desta estar em produção e validada com um lote real. Ela precisa de worker próprio,
template próprio e trava de volume — e disparo automático merece revisão própria.

Nesta fase, `leads.metadata.recontatar_em` é gravado e fica disponível para filtro manual.
