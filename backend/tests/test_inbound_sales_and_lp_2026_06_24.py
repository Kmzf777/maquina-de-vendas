"""Regressao da auditoria do lead 5511989581656 (Claudenir) — 2026-06-24.

Cobre:
  1. Bug da mensagem fantasma: get_or_create_conversation aceita agent_profile_id;
     LP cria a conversa com a persona OUTBOUND (nao cai no inbound default).
  2. Regra do Silencio agora GLOBAL (testada em test_outbound_falhas_2_3_5_6).
  3. Inbound atacado: pitch precoce removido + WIIFM inserido.
  4. base.py: regra global de contorno de desculpas (brush-off) + handoff com CTA imperativo.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

TZ_BR = timezone(timedelta(hours=-3))


def _now():
    return datetime.now(TZ_BR)


# --- 1. Roteamento LP: conversa nasce com agent_profile_id outbound ---------

def test_get_or_create_conversation_seta_agent_profile_na_criacao():
    from app.conversations import service
    captured = {}
    sb = MagicMock()
    # sem conversa existente
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    def _insert(row):
        captured["row"] = row
        return MagicMock(execute=MagicMock(return_value=MagicMock(data=[{**row, "id": "conv-new"}])))
    sb.table.return_value.insert.side_effect = _insert
    # leads.select (...).single().execute() → metadata vazio (sem handoff_summary)
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data={"metadata": {}})

    from unittest.mock import patch
    with patch.object(service, "get_supabase", return_value=sb):
        service.get_or_create_conversation("lead-1", "ch-1", agent_profile_id="prof-out")

    assert captured["row"].get("agent_profile_id") == "prof-out"


def test_lp_resolve_profile_por_prompt_key_env_agnostico():
    """F1: a LP resolve o profile por prompt_key em runtime (sem UUID hardcoded)."""
    from app.lp_webhook.service import LP_PROFILE_PROMPT_KEY
    assert LP_PROFILE_PROMPT_KEY == "valeria_outbound"

    # get_profile_id_by_prompt_key devolve o id do profile com aquela persona
    from unittest.mock import patch
    from app.agent_profiles import service as aps
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"id": "prof-out-env"}]
    )
    with patch.object(aps, "get_supabase", return_value=sb):
        assert aps.get_profile_id_by_prompt_key("valeria_outbound") == "prof-out-env"

    # Sem profile no banco → None (fail-open: cai no default do canal)
    sb2 = MagicMock()
    sb2.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    with patch.object(aps, "get_supabase", return_value=sb2):
        assert aps.get_profile_id_by_prompt_key("valeria_outbound") is None


# --- 3. Inbound atacado: pitch precoce removido + WIIFM ----------------------

def test_inbound_atacado_sem_pitch_precoce():
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    # Pitch de origem removido dos exemplos/etapa
    assert "da fazenda ate a xicara" not in ATACADO_PROMPT
    # Fragmentacao "cada cafe em uma mensagem separada" removida (governada pela Regra do Silencio)
    assert "uma mensagem separada (fragmentacao)" not in ATACADO_PROMPT


def test_inbound_atacado_tem_wiifm():
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    assert "WIIFM" in ATACADO_PROMPT
    low = ATACADO_PROMPT.lower()
    assert "necessidade real" in low or "necessidade que o lead" in low


# --- 4. base.py: brush-off global + handoff CTA imperativo ------------------

def test_base_tem_regra_brushoff_global():
    """Brush-off vale em todas as personas (regra global no corpo compartilhado)."""
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "BRUSH-OFF" in s or "CONTORNO DE DESCULPAS" in s
    assert "TURNAROUND" in s
    # Nao aceitar passivamente o "vou pensar" de primeira
    assert "vou pensar" in s.lower() or "vou analisar" in s.lower()


def test_d1_rapport_revenda_sem_pitch_de_margem():
    """D1: o rapport de revenda nao pode mais despejar argumento de margem/fidelizacao
    (vazava pitch precoce no inbound). Deve focar em curiosidade pelo negocio do lead."""
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "a margem e boa e o cliente fideliza" not in s
    assert "diferenca no ticket medio" not in s
    low = s.lower()
    # Instrucao de curiosidade no lugar do pitch
    assert "como o cafe entra no seu negocio hoje" in low or "curiosidade genuina pelo negocio" in low


def test_base_handoff_cta_imperativo():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    low = s.lower()
    # CTA imperativo de dar um oi agora
    assert "da um oi pra ele agora" in low
    # Linguagem passiva proibida explicitamente na regra de handoff
    assert "quando fizer sentido" in low and "proibido" in low
