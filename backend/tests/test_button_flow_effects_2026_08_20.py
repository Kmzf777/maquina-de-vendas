"""Efeitos do bot no CRM. Reusa as funções existentes — nada de regra reimplementada."""
from datetime import datetime, timezone
from unittest.mock import patch

from app.button_flow import effects, flows
from app.button_flow.engine import Efeitos

LEAD = {"id": "lead-1", "phone": "5511999999999", "name": "Fulano", "metadata": {}}

# Prefixo literal do padrão que o dashboard casa em messages.role='system'
# (supabase/migrations/20260712_dashboard_rpcs.sql, dashboard_kpis.handoff_msgs e
# dashboard_funnel_conversion.with_handoff):
#     content LIKE '[encaminhar\_humano] Lead encaminhado%'
# O \_ do SQL é só o underscore escapado; o literal é o texto abaixo.
MARCADOR_DO_DASHBOARD = "[encaminhar_humano] Lead encaminhado"


def _mensagens_de_sistema(save) -> list[str]:
    return [c.args[2] for c in save.call_args_list if c.args[1] == "system"]


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


def test_optout_de_lead_sem_telefone_nao_quebra_o_cancelamento():
    """Sem o `or ""`, o cancelamento de follow-ups receberia None e explodiria."""
    sem_fone = {"id": "lead-1", "metadata": {}}
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead"), \
         patch("app.button_flow.effects.apply_optout_side_effects") as side, \
         patch("app.button_flow.effects.append_lead_observation"), \
         patch("app.button_flow.effects.save_message"):
        ok = effects.aplicar(Efeitos(optout=True), lead=sem_fone, conversation_id="c1")

    assert ok is True
    side.assert_called_once_with("lead-1", "", reason="optout")


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


def test_silenciar_ia_desliga_a_ia_sem_carimbar_handoff():
    """Sem isto, no número da ValerIA o LLM assume a conversa que o bot acabou de largar."""
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.append_lead_observation"), \
         patch("app.button_flow.effects.save_message") as save:
        ok = effects.aplicar(
            Efeitos(tags=(flows.TAG_HUMANO,), silenciar_ia=True),
            lead=LEAD, conversation_id="c1",
        )

    assert ok is True
    upd.assert_called_once_with("lead-1", ai_enabled=False)
    assert not any("metadata" in c.kwargs for c in upd.call_args_list), \
        "silenciar_ia nao pode carimbar metadata.handoff"
    assert not any(t.startswith(MARCADOR_DO_DASHBOARD) for t in _mensagens_de_sistema(save)), \
        "texto livre nao e transbordo: contar como handoff inflaria o KPI do dashboard"


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


def test_handoff_grava_o_marcador_que_o_dashboard_conta():
    """Sem esta mensagem o lead é entregue ao vendedor e mesmo assim some do KPI.

    Nem o KPI de handoffs nem a conversão do funil olham `metadata.handoff`: os dois
    casam `content LIKE '[encaminhar\\_humano] Lead encaminhado%'` em
    messages.role='system'. Quem mudar o texto do marcador quebra este teste — e o
    que quebra de verdade é a contagem de transbordos do dashboard.
    """
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead"), \
         patch("app.button_flow.effects.append_lead_observation"), \
         patch("app.button_flow.effects.save_message") as save:
        effects.aplicar(Efeitos(handoff=True), lead=LEAD, conversation_id="c1")

    marcadores = [c for c in save.call_args_list
                  if c.args[1] == "system" and c.args[2].startswith(MARCADOR_DO_DASHBOARD)]
    assert marcadores, f"nenhum marcador de handoff em {_mensagens_de_sistema(save)}"
    # Exatamente UM: dashboard_kpis.handoff_msgs faz count(*) de mensagens, então um
    # marcador repetido contaria o mesmo transbordo duas vezes.
    assert len(marcadores) == 1
    marcador = marcadores[0]
    assert marcador.args[0] == "lead-1"
    # O RPC junta messages -> conversations; sem conversation_id o marcador fica órfão.
    assert marcador.kwargs["conversation_id"] == "c1"


def test_carimbo_do_handoff_preserva_o_resto_do_metadata():
    """O metadata do lead carrega marcadores de outros fluxos (catalog_shown, rastreio)."""
    lead = {"id": "lead-1", "phone": "5511999999999",
            "metadata": {"catalog_shown": True, "catalog_shown_at": "2026-01-01"}}
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.append_lead_observation"), \
         patch("app.button_flow.effects.save_message"):
        effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1")

    gravado = [c for c in upd.call_args_list if "metadata" in c.kwargs][0].kwargs["metadata"]
    assert gravado["catalog_shown"] is True
    assert gravado["catalog_shown_at"] == "2026-01-01"
    assert "handoff" in gravado
    # O dict do chamador não pode ser mutado: quem nos passou o lead pode reusá-lo.
    assert "handoff" not in lead["metadata"]


def test_recontato_grava_data_futura_em_metadata():
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.append_lead_observation"), \
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
