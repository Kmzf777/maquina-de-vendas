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

def test_silencio_global_inbound_e_outbound():
    """A regra do silencio e LEI UNIVERSAL — presente para as duas personas."""
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "REGRA DO SILENCIO" in s
    low = s.lower()
    assert "fique em silencio" in low or "silencio absoluto" in low
    assert "empilhar" in low
    # O mecanismo outbound-only (is_outbound / <outbound_voice>) foi removido
    assert "<outbound_voice>" not in s


# --- Falha #3: entender necessidade antes do produto ----------------------

def test_atacado_etapa0_entende_necessidade_antes_do_produto():
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    # A instrucao antiga de ir direto ao produto saiu
    assert "Va direto ao produto" not in ATACADO_PROMPT
    low = ATACADO_PROMPT.lower()
    assert "entenda a necessidade real" in low
    # Proibe justificativa logica precoce de venda
    assert "nunca abra com justificativa logica" in low or "justificativa logica de venda" in low


# --- Falha #5 / D2: anti-preenchimento agora GLOBAL (lei universal) --------

def test_anti_preenchimento_global_inbound_e_outbound():
    """D2: a proibicao de jargao-ack solto vale para TODAS as personas (inbound + outbound),
    incluindo 'tudo joia'."""
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(lead_name=None, lead_company=None, now=_now())  # default = qualquer persona
    assert '"perfeito", "entendo", "show", "que bacana", "que legal", "tudo joia"' in s
    # "show" deixou de ser um ack permitido na lista VARIE
    assert '"saquei", "boa", "show", "fechou"' not in s
    # BLACK-LIST 2026-06-24: o vocabulario natural NAO endossa mais as palavras banidas.
    # A antiga linha de "Vocabulario" que as listava foi removida (era a contradicao que
    # fazia o modelo usar "perfeito"/"bacana" apesar da regra anti-preenchimento).
    assert '"perfeito", "com certeza", "entendo", "bacana"' not in s
    assert '"com certeza", "claro", "fechou", "saquei", "boa"' in s


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
