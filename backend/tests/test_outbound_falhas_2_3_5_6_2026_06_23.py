"""Regressao das falhas #2, #3, #5 e #6 da auditoria do lead 5519997774170 (2026-06-23).

#2 (silencio): base.py proibe empilhar ack+afirmacao+pergunta no mesmo turno.
#3 (pitch precoce): atacado ETAPA 0 entende a necessidade antes de despejar produto.
#5 (preenchimento): base.py nao endossa "perfeito"/"entendo"/"show"/"que bacana" soltos.
#6 (follow-up mecanico): 1o follow-up sem 1h cravado + abertura nao generica.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

TZ_BR = timezone(timedelta(hours=-3))


def _now():
    return datetime.now(TZ_BR)


# --- Falha #2: regra do silencio (LEI UNIVERSAL desde 2026-06-24) ---------

def test_silencio_presente_no_outbound():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(lead_name=None, lead_company=None, now=_now(), is_outbound=True)
    assert "REGRA DO SILENCIO" in s
    low = s.lower()
    assert "fique em silencio" in low or "silencio absoluto" in low
    # Proibe empilhar ack + afirmacao + pergunta no mesmo turno
    assert "empilhar" in low


def test_silencio_agora_global_no_inbound():
    """A regra do silencio virou LEI UNIVERSAL — deve estar presente TAMBEM no Inbound.
    O bloco <outbound_voice> (anti-preenchimento) continua exclusivo do Outbound."""
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(lead_name=None, lead_company=None, now=_now())  # is_outbound=False (default)
    assert "REGRA DO SILENCIO" in s, "silencio deveria ser global (inbound tambem)"
    assert "<outbound_voice>" not in s, "o bloco outbound NAO pode vazar pro inbound"


# --- Falha #3: entender necessidade antes do produto ----------------------

def test_atacado_etapa0_entende_necessidade_antes_do_produto():
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    # A instrucao antiga de ir direto ao produto saiu
    assert "Va direto ao produto" not in ATACADO_PROMPT
    low = ATACADO_PROMPT.lower()
    assert "entenda a necessidade real" in low
    # Proibe justificativa logica precoce de venda
    assert "nunca abra com justificativa logica" in low or "justificativa logica de venda" in low


# --- Falha #5: sem palavras de preenchimento soltas (ESCOPO OUTBOUND) -----

def test_anti_preenchimento_no_outbound():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(lead_name=None, lead_company=None, now=_now(), is_outbound=True)
    # Proibicao explicita dos jargoes como bolha-ack solta no bloco outbound
    assert '"perfeito", "entendo", "show", "que bacana"' in s


def test_anti_preenchimento_nao_afeta_inbound():
    """Isolamento: o Inbound mantem a secao de acks original, sem o reforco outbound."""
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(lead_name=None, lead_company=None, now=_now())  # is_outbound=False
    # A proibicao estrita outbound NAO aparece no inbound
    assert '"perfeito", "entendo", "show", "que bacana"' not in s
    # O vocabulario original compartilhado permanece intacto
    assert '"perfeito", "com certeza", "entendo", "bacana"' in s


# --- Falha #6: follow-up sem 1h cravado e sem abertura generica ------------

def test_seq1_followup_tem_jitter_nao_cravado_em_1h():
    """O 1o follow-up sorteia o intervalo (nao e mais hardcoded em 1h)."""
    from app.follow_up import service

    assert service._SEQ1_MIN_MINUTES != 60, "1o follow-up nao pode ser cravado em 1h"

    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"id": "conv"}])
    sb.table.return_value.insert.side_effect = lambda jobs: MagicMock(execute=MagicMock())

    with patch.object(service, "get_supabase", return_value=sb), \
         patch.object(service.random, "randint", return_value=120) as rnd:
        service.schedule_followup("conv", "lead", "ch")

    rnd.assert_called_once_with(service._SEQ1_MIN_MINUTES, service._SEQ1_MAX_MINUTES)


def test_followup_instruction_proibe_abertura_generica():
    from app.follow_up.scheduler import _FOLLOWUP_REENGAGE_INSTRUCTION, _build_followup_system_prompt
    low = _FOLLOWUP_REENGAGE_INSTRUCTION.lower()
    # Bane abertura/pergunta vazia
    assert "tudo joia" in low
    assert "proibido" in low
    # Bane abrir pelo nome do lead
    assert "nome do lead no começo" in low or "nome do lead no comeco" in low
    # O tom da seq=1 nao referencia mais o "1h" cravado
    assert "(1h após" not in _build_followup_system_prompt(1)
