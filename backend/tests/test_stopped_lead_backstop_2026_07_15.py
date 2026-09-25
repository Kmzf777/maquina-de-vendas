"""Rede de segurança de PARADA no envio + cancelamento por identidade — 15/07/2026.

Caso real (lead 5511910402026): a cliente pediu ao vendedor humano (João) para a IA
parar, mas o pedido NUNCA virou estado no sistema (opt_out=false, ai_enabled=true).
A cadência da Valéria seguia viva porque a interrupção dependia 100% do cancelamento-
na-escrita ter alcançado a linha certa — sem uma segunda verificação no momento do
disparo. Além disso, o cancelamento resolvia UM lead por telefone (`.limit(1)`),
deixando gêmeos do 9º dígito com cadência viva, e preservava `ai_scheduled_return`
mesmo em paradas terminais.

Cobertura:
1. `_lead_stop_reason` (função pura de decisão) — opt_out, blacklist, wrong_number,
   ai_enabled=False e o caso "segue normal".
2. `_phone_identity_values` — resolve as duas formas (12/13 dígitos) do móvel BR e
   preserva BSUID.
3. `_preserved_job_types` — paradas terminais deixam de preservar `ai_scheduled_return`
   (mas SEMPRE preservam `handoff_rescue`, do qual o handoff depende).
3b. O RECORTE DE 25/09 NÃO ALCANÇA ESTE BACKSTOP. `_preserved_job_types` ganhou um
   segundo eixo — o `reason` — e com `client_replied` ele passa a preservar as
   cadências do João, porque responder deixou de MATÁ-LAS e passou a ADIÁ-LAS
   (`processar_resposta_joao`, spec 2026-09-25 §3.2). O recorte é SO desse motivo. Se
   um dia ele virar "preserva sempre", é exatamente este caso de 15/07 que reabre: a
   cliente pediu ao HUMANO para a IA parar, e o pedido chega aqui como `handoff` ou
   como opt-out — nunca como `client_replied`. Por isso a cobertura do eixo novo mora
   NESTE arquivo, e não só no do motor do João.
4. `process_due_followups` cancela QUALQUER job de lead marcado para parar ANTES de
   despachar — nem toque LLM, nem reopen, nem template de resgate saem.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.follow_up import scheduler as S
from app.follow_up.scheduler import _lead_stop_reason
from app.follow_up.cadence_joao import JOB_TYPES as JOAO_JOB_TYPES
from app.follow_up.service import _phone_identity_values, _preserved_job_types


# ─── _lead_stop_reason: função pura ───────────────────────────────────────────

def test_opt_out_para():
    assert _lead_stop_reason({"opt_out": True}) == "opt_out"


def test_blacklist_para():
    assert _lead_stop_reason({"metadata": {"blacklisted_at": "2026-07-15T12:00:00+00:00"}}) == "blacklisted"


def test_wrong_number_para():
    assert _lead_stop_reason({"metadata": {"wrong_number_at": "2026-07-15T12:00:00+00:00"}}) == "wrong_number"


def test_ai_desligada_para():
    assert _lead_stop_reason({"ai_enabled": False}) == "ai_disabled"


def test_lead_ativo_segue_normal():
    assert _lead_stop_reason({"opt_out": False, "ai_enabled": True, "metadata": {}}) is None


def test_lead_none_ou_sem_flags_segue_normal():
    # None (falha de releitura) e lead sem flags → fail-open: não para.
    assert _lead_stop_reason(None) is None
    assert _lead_stop_reason({"id": "L1"}) is None


# ─── _phone_identity_values: as duas formas do 9º dígito ──────────────────────

def test_phone_variants_injeta_9o_digito():
    col, values = _phone_identity_values("551110402026")  # 12 díg. (sem 9)
    assert col == "phone"
    assert set(values) == {"551110402026", "5511910402026"}


def test_phone_variants_remove_9o_digito():
    col, values = _phone_identity_values("5511910402026")  # 13 díg. (com 9)
    assert col == "phone"
    assert set(values) == {"5511910402026", "551110402026"}


def test_phone_variants_bsuid_inalterado():
    col, values = _phone_identity_values("BR.1648638289640153")
    assert col == "bsuid"
    assert values == ["BR.1648638289640153"]


# ─── _preserved_job_types: paridade terminal x não-terminal ───────────────────

def test_nao_terminal_preserva_scheduled_return():
    # A igualdade EXATA é de propósito: ela é o que impede um `job_type` de entrar na
    # lista de preservados sem ninguém notar — e cada `job_type` preservado a mais é uma
    # cadência que sobrevive a uma parada. Ela continua valendo em todo motivo que NÃO
    # seja `client_replied`; o que aquele motivo acrescenta está logo abaixo.
    assert _preserved_job_types(preserve_scheduled_return=True) == ["handoff_rescue", "ai_scheduled_return"]
    assert _preserved_job_types(True, "handoff") == ["handoff_rescue", "ai_scheduled_return"]


def test_terminal_dropa_scheduled_return_mas_preserva_rescue():
    preserved = _preserved_job_types(preserve_scheduled_return=False)
    assert "ai_scheduled_return" not in preserved
    assert "handoff_rescue" in preserved  # handoff depende do rescue sobreviver


# ─── O recorte de 25/09 não pode furar este backstop ─────────────────────────

@pytest.mark.parametrize("reason", [
    "handoff",                    # `encaminhar_humano` — o caminho do caso de 15/07
    "sem_interesse_atual",
    "cliente_ativo_sem_demanda",
    "lead_already_served",
    "optout",                     # apply_optout_side_effects, pela tool
    "optout_botao",               # idem, pelo botão do template
    "block_manual",               # idem, pelo botão "Bloquear" do CRM
])
def test_parada_terminal_continua_cancelando_as_cadencias_do_joao(reason):
    """O caso de 15/07 chega aqui como `handoff` ou como opt-out. NUNCA como
    `client_replied` — e é só esse que o recorte alcança.

    Quando a cliente pede ao vendedor HUMANO para a IA parar, quem transforma o pedido
    em estado é o vendedor, por um destes motivos. Se o recorte de 25/09 escorregar para
    "preserva sempre", os toques do João voltam a sair depois de uma parada explícita —
    o mesmo incidente, agora pela porta dos fundos.
    """
    preservados = set(_preserved_job_types(True, reason))
    assert not (JOAO_JOB_TYPES & preservados), sorted(JOAO_JOB_TYPES & preservados)
    preservados_terminal = set(_preserved_job_types(False, reason))
    assert not (JOAO_JOB_TYPES & preservados_terminal)


def test_so_o_client_replied_preserva_as_cadencias_do_joao():
    """O outro lado do recorte, ancorado aqui para que as duas metades vivam juntas:
    responder NÃO é uma parada, e por isso é o único motivo que preserva."""
    assert JOAO_JOB_TYPES <= set(_preserved_job_types(True, "client_replied"))


# ─── process_due_followups: backstop no DISPARO ───────────────────────────────

def _make_job(**overrides) -> dict:
    job = {
        "id": "job-1",
        "job_type": "standard",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 2,
        "leads": {"id": "lead-1", "phone": "5511910402026", "name": "Cliente"},
        "channels": {"id": "ch-1", "mode": "ai", "provider_config": {}},
        "conversations": {
            "id": "conv-1",
            "stage": "secretaria",
            "followup_enabled": True,
            "last_customer_message_at": None,
        },
        "metadata": {},
    }
    job.update(overrides)
    return job


async def _run_with_fresh_lead(fresh_lead):
    job = _make_job()
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", return_value=fresh_lead), \
         patch("app.agent.tools.execute_tool", new_callable=AsyncMock) as mock_tool, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler.fire_reopen_template", new_callable=AsyncMock) as mock_reopen, \
         patch("app.follow_up.scheduler._generate_followup_message", new_callable=AsyncMock) as mock_generate:
        await S.process_due_followups(now=datetime.now(timezone.utc))
    return mock_cancel, mock_reopen, mock_generate, mock_tool


@pytest.mark.asyncio
async def test_backstop_opt_out_cancela_sem_enviar():
    fresh = {"id": "lead-1", "phone": "5511910402026", "opt_out": True,
             "ai_enabled": True, "stage": "secretaria", "metadata": {}}
    mock_cancel, mock_reopen, mock_generate, mock_tool = await _run_with_fresh_lead(fresh)
    mock_cancel.assert_called_once_with("job-1", "opt_out")
    mock_reopen.assert_not_awaited()
    mock_generate.assert_not_called()
    mock_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_backstop_ai_desligada_cancela_sem_enviar():
    fresh = {"id": "lead-1", "phone": "5511910402026", "opt_out": False,
             "ai_enabled": False, "stage": "secretaria", "metadata": {}}
    mock_cancel, mock_reopen, mock_generate, _ = await _run_with_fresh_lead(fresh)
    mock_cancel.assert_called_once_with("job-1", "ai_disabled")
    mock_reopen.assert_not_awaited()
    mock_generate.assert_not_called()


@pytest.mark.asyncio
async def test_backstop_lead_ativo_nao_cancela_por_backstop():
    """Lead sem nenhuma flag de parada: o backstop NÃO age; cai no fluxo padrão que,
    sem last_customer_message_at, cancela como window_expired (não 'stopped')."""
    fresh = {"id": "lead-1", "phone": "5511910402026", "opt_out": False,
             "ai_enabled": True, "stage": "secretaria", "metadata": {}}
    mock_cancel, _, _, _ = await _run_with_fresh_lead(fresh)
    mock_cancel.assert_called_once_with("job-1", "window_expired")
