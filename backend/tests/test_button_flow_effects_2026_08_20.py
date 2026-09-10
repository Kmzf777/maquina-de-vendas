"""Efeitos do bot no CRM. Reusa as funções existentes — nada de regra reimplementada."""
import dataclasses
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.button_flow import effects, flows
from app.button_flow.engine import Efeitos


@pytest.fixture
def lead() -> dict:
    """Um lead NOVO por teste.

    Era um dict de módulo compartilhado, e `aplicar` o muta: `atualizar_metadata`
    faz `lead["metadata"] = meta` de propósito (dois carimbos no mesmo turno não
    podem se apagar). Com a fixture compartilhada, o `metadata` vazado de um teste
    entrava no seguinte e o resultado passava a depender da ORDEM de execução —
    exatamente o tipo de teste que só quebra quando alguém roda `-k` ou paraleliza.
    """
    return {"id": "lead-1", "phone": "5511999999999", "name": "Fulano", "metadata": {}}


# Card em `stage='novo'` no funil Reativação Bling: é onde os 1.208 deals da coorte
# estão (scripts/reativacao/lote_completo.py), sem um movimento desde a importação.
def _deal(pipeline: str | None = None) -> dict:
    return {"id": "deal-1", "title": "Fulano - Reativação",
            "pipeline_id": pipeline or effects.PIPELINE_RECUPERACAO,
            "stage_id": "stage-novo", "category": None}


# Prefixo literal do padrão que o dashboard casa em messages.role='system'
# (supabase/migrations/20260712_dashboard_rpcs.sql, dashboard_kpis.handoff_msgs e
# dashboard_funnel_conversion.with_handoff):
#     content LIKE '[encaminhar\_humano] Lead encaminhado%'
# O \_ do SQL é só o underscore escapado; o literal é o texto abaixo.
MARCADOR_DO_DASHBOARD = "[encaminhar_humano] Lead encaminhado"

# Rótulos do trio ANTIGO, medido em ~1.300 envios e aposentado no relabel de
# 09/09/2026 (commit 31ccb5ce). Nenhum lead da coorte nova vê qualquer um deles: uma
# observação de auditoria que diga "clicou em 'Quero comprar agora'" descreve um
# clique que não aconteceu — e é ela que o João lê antes de abordar o lead.
ROTULOS_APOSENTADOS = (
    "Quero comprar agora", "Talvez em alguns meses", "Não quero mais receber",
    "Sair da lista", "Mais pra frente", "Continuar atendimento", "Tirar duvidas",
    "Nao tenho interesse",
)


def _mensagens_de_sistema(save) -> list[str]:
    return [c.args[2] for c in save.call_args_list if c.args[1] == "system"]


# Sentinela: `deal=None` é um caso REAL (lead sem card aberto) e precisa ser
# distinguível de "não pedi nada, me dá o padrão".
_CARD_PADRAO = object()


@contextmanager
def _crm_mockado(*, deal=_CARD_PADRAO):
    """Todas as portas de escrita/leitura do módulo, de uma vez.

    Existe porque os testes de varredura abaixo chamam `aplicar` com efeitos
    combinados: sem o conjunto completo, um efeito não patcheado bateria no Supabase
    de verdade em vez de falhar o teste. `get_open_deal`/`move_deal_to_stage_key`
    entraram junto quando os desfechos passaram a mover o card — sem elas cada
    desfecho gastaria ~1s tentando resolver a URL fake do conftest.

    Por padrão o lead tem um card no funil Reativação Bling (o caso real dos 1.208).
    """
    with patch("app.button_flow.effects.add_tags_to_lead") as add, \
         patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.apply_optout_side_effects") as side, \
         patch("app.button_flow.effects.append_lead_observation") as obs, \
         patch("app.button_flow.effects.save_message") as save, \
         patch("app.button_flow.effects.get_open_deal",
               return_value=_deal() if deal is _CARD_PADRAO else deal) as aberto, \
         patch("app.button_flow.effects.move_deal_to_stage_key",
               return_value=True) as mover:
        yield SimpleNamespace(add=add, upd=upd, side=side, obs=obs, save=save,
                              deal=aberto, mover=mover)


def _stages_movidos(crm) -> list[str]:
    """Keys de etapa para onde o card foi mandado, na ordem."""
    return [c.args[1] for c in crm.mover.call_args_list]


def test_tags_sao_aplicadas_pelo_helper_existente(lead):
    with patch("app.button_flow.effects.add_tags_to_lead") as add:
        ok = effects.aplicar(Efeitos(tags=(flows.TAG_QUENTE,)), lead=lead, conversation_id="c1")
    assert ok is True
    add.assert_called_once_with("lead-1", [flows.TAG_QUENTE])


def test_optout_desliga_ia_e_dispara_os_efeitos_colaterais(lead):
    with _crm_mockado() as crm:
        ok = effects.aplicar(
            Efeitos(tags=(flows.TAG_RECUSOU,), optout=True), lead=lead, conversation_id="c1"
        )

    assert ok is True
    crm.upd.assert_called_once()
    gravado = crm.upd.call_args.kwargs
    assert gravado["ai_enabled"] is False
    assert gravado["opt_out"] is True
    crm.side.assert_called_once_with("lead-1", "5511999999999", reason="optout")


def test_optout_de_lead_sem_telefone_nao_quebra_o_cancelamento():
    """Sem o `or ""`, o cancelamento de follow-ups receberia None e explodiria."""
    sem_fone = {"id": "lead-1", "metadata": {}}
    with _crm_mockado() as crm:
        ok = effects.aplicar(Efeitos(optout=True), lead=sem_fone, conversation_id="c1")

    assert ok is True
    crm.side.assert_called_once_with("lead-1", "", reason="optout")


def test_falha_ao_gravar_optout_bloqueia_o_avanco(lead):
    """Única exceção ao fail-soft: continuar disparando p/ quem pediu p/ sair é o pior desfecho."""
    with _crm_mockado() as crm:
        crm.upd.side_effect = RuntimeError("boom")
        ok = effects.aplicar(Efeitos(optout=True), lead=lead, conversation_id="c1")

    assert ok is False
    crm.side.assert_not_called()
    assert not _stages_movidos(crm), "sem opt-out gravado, o card não pode ir p/ Descadastrado"


def test_falha_de_tag_nao_bloqueia(lead):
    """Fail-soft: o lead já recebeu a resposta, não pode ficar preso por uma tag."""
    with patch("app.button_flow.effects.add_tags_to_lead", side_effect=RuntimeError("boom")):
        ok = effects.aplicar(Efeitos(tags=("X",)), lead=lead, conversation_id="c1")
    assert ok is True


def test_silenciar_ia_desliga_a_ia_sem_carimbar_handoff(lead):
    """Sem isto, no número da ValerIA o LLM assume a conversa que o bot acabou de largar."""
    with _crm_mockado() as crm:
        ok = effects.aplicar(
            Efeitos(tags=(flows.TAG_HUMANO,), silenciar_ia=True),
            lead=lead, conversation_id="c1",
        )

    assert ok is True
    crm.upd.assert_called_once_with("lead-1", ai_enabled=False)
    assert not any("metadata" in c.kwargs for c in crm.upd.call_args_list), \
        "silenciar_ia nao pode carimbar metadata.handoff"
    assert not any(t.startswith(MARCADOR_DO_DASHBOARD)
                   for t in _mensagens_de_sistema(crm.save)), \
        "texto livre nao e transbordo: contar como handoff inflaria o KPI do dashboard"
    assert not _stages_movidos(crm), \
        "duas incompreensões seguidas não são desfecho: o card fica na etapa de recência"


def test_handoff_desliga_ia_e_carimba_metadata(lead):
    with _crm_mockado() as crm:
        ok = effects.aplicar(
            Efeitos(tags=(flows.TAG_QUENTE,), handoff=True), lead=lead, conversation_id="c1"
        )

    assert ok is True
    chamadas = {c.kwargs.get("ai_enabled") for c in crm.upd.call_args_list}
    assert False in chamadas
    carimbo = [c for c in crm.upd.call_args_list if "metadata" in c.kwargs]
    assert carimbo, "handoff precisa carimbar metadata.handoff (cascata de qualificados)"
    assert carimbo[0].kwargs["metadata"]["handoff"]["vendedor"]
    crm.obs.assert_called_once()


def test_handoff_grava_o_marcador_que_o_dashboard_conta(lead):
    """Sem esta mensagem o lead é entregue ao vendedor e mesmo assim some do KPI.

    Nem o KPI de handoffs nem a conversão do funil olham `metadata.handoff`: os dois
    casam `content LIKE '[encaminhar\\_humano] Lead encaminhado%'` em
    messages.role='system'. Quem mudar o texto do marcador quebra este teste — e o
    que quebra de verdade é a contagem de transbordos do dashboard.
    """
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1")

    save = crm.save
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
    """O metadata do lead carrega marcadores de outros fluxos (catalog_shown, rastreio).

    O dict que o CHAMADOR passou continua intocado — nada de merge in-place num dict
    que não é nosso —, mas o `lead` em memória passa a apontar para o metadata já
    gravado. Isso é deliberado (ver `atualizar_metadata`) e é o que sustenta o teste
    seguinte: dois carimbos no mesmo `aplicar` sem um apagar o outro.
    """
    metadata_do_chamador = {"catalog_shown": True, "catalog_shown_at": "2026-01-01"}
    lead = {"id": "lead-1", "phone": "5511999999999", "metadata": metadata_do_chamador}
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1")

    upd = crm.upd
    gravado = [c for c in upd.call_args_list if "metadata" in c.kwargs][0].kwargs["metadata"]
    assert gravado["catalog_shown"] is True
    assert gravado["catalog_shown_at"] == "2026-01-01"
    assert "handoff" in gravado
    assert "handoff" not in metadata_do_chamador, "merge in-place no dict de quem chamou"
    assert lead["metadata"]["handoff"] == gravado["handoff"]


def test_dois_carimbos_no_mesmo_turno_nao_se_apagam():
    """`pretexto_contestado` e `handoff` gravam o MESMO campo (leads.metadata).

    Se cada um partisse da cópia original do chamador, o segundo update sobrescreveria
    o primeiro — silenciosamente, porque os dois retornam sucesso. O carimbo perdido
    seria justamente `metadata.handoff`, que `follow_up.should_proactive_handoff` lê
    para não reentregar sozinho um lead já entregue.
    """
    lead = {"id": "lead-1", "phone": "5511999999999", "metadata": {"id_bling": "9"}}
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(pretexto_contestado=True, handoff=True, recontato_dias=30),
                        lead=lead, conversation_id="c1")

    ultimo = [c.kwargs["metadata"] for c in crm.upd.call_args_list
              if "metadata" in c.kwargs][-1]
    assert ultimo["pretexto_contestado"] is True
    assert "handoff" in ultimo
    assert "recontatar_em" in ultimo
    assert ultimo["id_bling"] == "9", "o metadata pré-existente do lead sobrevive"


def test_recontato_grava_data_futura_em_metadata(lead):
    """Em DIAS, não em meses (relabel de 09/09/2026).

    O menu do nível 2 passou a oferecer 30/60/90 dias porque o intervalo médio entre
    compras desta coorte é 78-122 dias. Converter para "mês" e multiplicar por 30 de
    volta só reintroduziria arredondamento em cima do número que o lead escolheu.
    """
    for prazo in flows.PRAZOS:
        with _crm_mockado() as crm:
            effects.aplicar(Efeitos(tags=(prazo.tag,), recontato_dias=prazo.dias),
                            lead=lead, conversation_id="c1")

        meta = crm.upd.call_args.kwargs["metadata"]
        quando = datetime.fromisoformat(meta["recontatar_em"])
        dias = (quando - datetime.now(timezone.utc)).days
        assert prazo.dias - 1 <= dias <= prazo.dias, f"{prazo.id}: veio {dias} dias"


def test_recontato_nao_tira_o_lead_do_atendimento(lead):
    """Quem pediu tempo continua sendo atendido: adiar não é recusa nem transbordo.

    Foi a leitura contrária que criou a dívida atual — "Nao tenho interesse" tratado
    como fim de linha para gente que só queria dizer "agora não" (41% continuaram
    conversando, 2 compraram depois).
    """
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(recontato_dias=30), lead=lead, conversation_id="c1")

    assert not any("ai_enabled" in c.kwargs for c in crm.upd.call_args_list)
    assert not any(t.startswith(MARCADOR_DO_DASHBOARD)
                   for t in _mensagens_de_sistema(crm.save))


def test_sem_efeitos_nao_toca_no_banco(lead):
    with patch("app.button_flow.effects.update_lead") as upd, \
         patch("app.button_flow.effects.add_tags_to_lead") as add:
        assert effects.aplicar(Efeitos(), lead=lead, conversation_id="c1") is True
    upd.assert_not_called()
    add.assert_not_called()


def test_aplicar_conhece_todos_os_campos_de_efeitos(lead):
    """Incidente de 09/09/2026: `engine.Efeitos.recontato_meses` virou `recontato_dias`
    (commit 31ccb5ce) e effects.py continuou lendo o nome antigo.

    Como a leitura está no caminho COMUM de `aplicar` (`if efeitos.recontato_meses`),
    o AttributeError derrubava todos os efeitos de todo turno — inclusive o opt-out,
    que é fail-CLOSED: o lead pedia para sair, a gravação estourava antes de começar e
    o nó nem avançava. Nenhum teste de campo isolado pegava isso; o que pegou foi a
    suíte inteira ficando vermelha de uma vez.

    Este teste falha no dia em que Efeitos ganhar um campo que `aplicar` não conhece.
    """
    valores = {"tags": ("X",), "optout": True, "handoff": True, "recontato_dias": 30,
               "silenciar_ia": True, "pretexto_contestado": True}
    nomes = {f.name for f in dataclasses.fields(Efeitos)}
    assert nomes <= set(valores), f"campo novo em Efeitos sem cobertura aqui: {nomes - set(valores)}"

    for nome in nomes:
        with _crm_mockado():
            ok = effects.aplicar(Efeitos(**{nome: valores[nome]}),
                                 lead=lead, conversation_id="c1")
        assert ok is True, nome

    with _crm_mockado():
        assert effects.aplicar(Efeitos(**{n: valores[n] for n in nomes}),
                               lead=lead, conversation_id="c1") is True


def test_registros_de_auditoria_nao_citam_rotulo_aposentado(lead):
    """O que o João lê antes de abordar o lead é a observação e a mensagem de sistema.

    Se elas dizem "clicou em 'Quero comprar agora'" — rótulo que saiu do fluxo em
    09/09/2026 — o vendedor abre a conversa acreditando num clique que nunca existiu,
    e o mesmo texto vai para o carimbo `metadata.handoff`, que é o registro de
    auditoria do transbordo.
    """
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(tags=(flows.TAG_QUENTE,), handoff=True),
                        lead=lead, conversation_id="c1")
        effects.aplicar(Efeitos(tags=(flows.TAG_RECUSOU,), optout=True),
                        lead=lead, conversation_id="c1")
        effects.aplicar(Efeitos(tags=(flows.TAG_HUMANO,), silenciar_ia=True),
                        lead=lead, conversation_id="c1")
        effects.aplicar(Efeitos(recontato_dias=90), lead=lead, conversation_id="c1")

    # args[1]: `append_lead_observation(lead_id, texto)` — args[0] é o id do lead, e
    # varrer o id atrás de rótulo aposentado não testava nada.
    textos = [c.args[1] for c in crm.obs.call_args_list]
    textos += [c.args[2] for c in crm.save.call_args_list]
    textos += [json.dumps(c.kwargs["metadata"], ensure_ascii=False)
               for c in crm.upd.call_args_list if "metadata" in c.kwargs]
    assert textos, "nenhum registro de auditoria gravado — o fluxo ficaria sem rastro"

    for texto in textos:
        for rotulo in ROTULOS_APOSENTADOS:
            assert rotulo not in texto, f"{rotulo!r} não existe mais no fluxo: {texto!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Evidência de opt-out — colunas de 20260909_recuperacao_stages_optout.sql
# ═══════════════════════════════════════════════════════════════════════════
# Um clique real de opt-out, como o runner o entrega: payload custom do fluxo,
# título como o lead viu e o wamid — a única parte da prova que a Meta confirma
# de forma independente.
CLIQUE_PARAR = {
    "origem": "clique",
    "button_payload": f"{flows.FLOW_ID}|{flows.ID_OPTOUT}|{flows.TRILHA_ESTOQUE}|t1",
    "button_label": flows.BTN_OPTOUT.titulo,
    "wamid": "wamid.HBgNNTUzNDk4ODg2MTQ0MRUCABIYFjNBMEE",
}


def _campos_do_optout(crm) -> dict:
    """kwargs do UPDATE que gravou opt_out=true."""
    return [c.kwargs for c in crm.upd.call_args_list if c.kwargs.get("opt_out")][-1]


def test_optout_de_clique_grava_as_tres_colunas_de_evidencia(lead):
    """REPRO: até 09/09/2026 ninguém escrevia opt_out_at/_channel/_evidence.

    `_aplicar_optout` fazia só `update_lead(ai_enabled=False, opt_out=True)` — o
    "booleano nu" que a própria migration (20260909_recuperacao_stages_optout.sql:78-97)
    declara indefensável na ANPD: não responde QUANDO a pessoa pediu, POR ONDE pediu
    nem QUAL a prova. Pior: o backfill dos 48 retroativos
    (scripts/recuperacao/honrar_optouts_pendentes.sql) preenche a evidência DELES, e o
    opt-out novo, do agente rodando hoje, nasceria mais pobre que o histórico.
    """
    antes = datetime.now(timezone.utc)
    with _crm_mockado() as crm:
        ok = effects.aplicar(Efeitos(tags=(flows.TAG_RECUSOU,), optout=True),
                             lead=lead, conversation_id="c1", evidencia=CLIQUE_PARAR)

    assert ok is True
    campos = _campos_do_optout(crm)
    assert campos["ai_enabled"] is False
    assert campos["opt_out"] is True
    assert campos["opt_out_channel"] == effects.CANAL_BOTAO

    quando = datetime.fromisoformat(campos["opt_out_at"])
    assert antes <= quando <= datetime.now(timezone.utc), "opt_out_at tem que ser agora, em UTC"
    assert quando.tzinfo is not None, "timestamptz sem tz vira ambiguidade de fuso no banco"

    prova = campos["opt_out_evidence"]
    assert prova["button_payload"] == CLIQUE_PARAR["button_payload"]
    assert prova["button_label"] == flows.BTN_OPTOUT.titulo
    assert prova["wamid"] == CLIQUE_PARAR["wamid"]
    assert prova["conversation_id"] == "c1"
    assert prova["source"] == "button_flow"
    assert prova["registrado_em"] == campos["opt_out_at"]
    # jsonb precisa ser serializável — um objeto solto aqui explodiria só no PostgREST.
    json.dumps(prova, ensure_ascii=False)


def test_optout_de_texto_classificado_grava_canal_de_texto(lead):
    """A classe SAIR da camada 2 não é clique: o canal é `whatsapp_texto`.

    Vocabulário do COMMENT da coluna (migration:108). Registrar 'whatsapp_button'
    para quem digitou "me tira dessa lista" seria descrever uma prova que não existe.
    """
    evidencia = {"origem": "classe", "classe": "SAIR",
                 "texto": "me tira dessa lista por favor", "wamid": "wamid.TXT"}
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(optout=True), lead=lead,
                        conversation_id="c1", evidencia=evidencia)

    campos = _campos_do_optout(crm)
    assert campos["opt_out_channel"] == effects.CANAL_TEXTO
    assert campos["opt_out_evidence"]["texto"] == "me tira dessa lista por favor"
    assert campos["opt_out_evidence"]["classe"] == "SAIR"


def test_canal_explicito_do_chamador_vence(lead):
    """Chamador que não é o bot (CRM manual, e-mail, telefone) informa o canal."""
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(optout=True), lead=lead, conversation_id="c1",
                        evidencia={"canal": "manual_crm", "by": "joao@canastra"})

    campos = _campos_do_optout(crm)
    assert campos["opt_out_channel"] == "manual_crm"
    assert campos["opt_out_evidence"]["by"] == "joao@canastra"


def test_optout_sem_evidencia_nao_inventa_canal(lead):
    """Sem origem não dá para saber o canal — e chutar é pior que a lacuna.

    O `opt_out` em si e o `opt_out_at` continuam gravados: a data é nossa, o canal
    é do turno. `opt_out_channel` fora do UPDATE = coluna intocada.
    """
    with _crm_mockado() as crm:
        ok = effects.aplicar(Efeitos(optout=True), lead=lead, conversation_id="c1")

    assert ok is True
    campos = _campos_do_optout(crm)
    assert campos["opt_out"] is True
    assert "opt_out_at" in campos
    assert "opt_out_channel" not in campos


def test_coluna_de_evidencia_ausente_nao_derruba_o_optout(lead):
    """REPRO: migration 20260909 ainda NÃO aplicada no Supabase (estado de hoje).

    O UPDATE com opt_out_at/_channel/_evidence volta PGRST204 ("column not found") e,
    se a gravação parasse aí, `aplicar` devolveria False (fail-CLOSED) — o lead pediria
    para sair, o nó não avançaria e ele continuaria elegível a disparo. Fail-CLOSED vale
    para o opt-out, NUNCA para a evidência: degrada para o update nu e honra o pedido.
    """
    class PGRST204(Exception):
        pass

    def falha_so_com_evidencia(lead_id, **campos):
        if "opt_out_evidence" in campos:
            raise PGRST204("PGRST204: column leads.opt_out_evidence does not exist")
        return {"id": lead_id}

    with _crm_mockado() as crm:
        crm.upd.side_effect = falha_so_com_evidencia
        ok = effects.aplicar(Efeitos(optout=True), lead=lead,
                             conversation_id="c1", evidencia=CLIQUE_PARAR)

    assert ok is True, "sem as colunas novas o opt-out TEM que ser gravado assim mesmo"
    assert crm.upd.call_args_list[-1].kwargs == {"ai_enabled": False, "opt_out": True}
    crm.side.assert_called_once_with("lead-1", "5511999999999", reason="optout")
    # A nota é a evidência LEGÍVEL do registro; sem coluna ela é a única que sobra.
    assert any("[OPT-OUT]" in c.args[1] for c in crm.obs.call_args_list)


def test_falha_de_transporte_nas_duas_tentativas_ainda_bloqueia(lead):
    """A degradação não pode virar um jeito de o fail-CLOSED nunca disparar."""
    with _crm_mockado() as crm:
        crm.upd.side_effect = RuntimeError("GOAWAY")
        ok = effects.aplicar(Efeitos(optout=True), lead=lead,
                             conversation_id="c1", evidencia=CLIQUE_PARAR)

    assert ok is False
    assert crm.upd.call_count == 2, "tenta com evidência e, na falha, sem ela"
    crm.side.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# Desfecho move o card — as 3 etapas de 20260909 eram etapas mortas
# ═══════════════════════════════════════════════════════════════════════════
def test_handoff_move_o_card_para_quer_repor(lead):
    """REPRO: `quer_repor` era criada pela migration e ninguém a alimentava.

    É A conversão do agente: a etapa nasceu com conversion_event='qualified', então
    cada entrada vira uma linha deduplicada em conversion_events (automation/triggers).
    Sem o move, a métrica do agente é zero por construção.
    """
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(tags=(flows.TAG_QUENTE,), handoff=True),
                        lead=lead, conversation_id="c1")

    assert _stages_movidos(crm) == [effects.STAGE_QUER_REPOR[0]]
    chamada = crm.mover.call_args
    assert chamada.args[0] == "lead-1"
    assert chamada.args[2] == effects.STAGE_QUER_REPOR[1], "label é o fallback de resolução"


def test_recontato_move_o_card_para_recontato_agendado(lead):
    with _crm_mockado() as crm:
        effects.aplicar(Efeitos(recontato_dias=90), lead=lead, conversation_id="c1")

    assert _stages_movidos(crm) == [effects.STAGE_RECONTATO[0]]


def test_recontato_sem_data_gravada_nao_move_o_card(lead):
    """Card em "Recontato agendado" promete uma fila COM data.

    Se `metadata.recontatar_em` não gravou, mover o card criaria um lead esquecido
    parecendo agendado — o worker de re-disparo lê a data, não a etapa.
    """
    with _crm_mockado() as crm:
        crm.upd.side_effect = RuntimeError("boom")
        effects.aplicar(Efeitos(recontato_dias=30), lead=lead, conversation_id="c1")

    assert not _stages_movidos(crm)


def test_optout_move_o_card_para_descadastrado_antes_da_blacklist(lead):
    """REPRO: `descadastrado` também era etapa morta — e a ORDEM é o que a mantém viva.

    `apply_optout_side_effects` chama `move_lead_deals_to_blacklist`
    (leads/service.py:1458), que joga TODOS os deals do lead para o funil Blacklist.
    Movendo depois dele, a guarda de funil de `_mover_deal` já não reconheceria o card
    e a etapa nunca receberia ninguém.
    """
    ordem: list[str] = []

    def moveu(*_a, **_k):
        ordem.append("descadastrado")
        return True

    with _crm_mockado() as crm:
        crm.mover.side_effect = moveu
        crm.side.side_effect = lambda *_a, **_k: ordem.append("blacklist")
        effects.aplicar(Efeitos(tags=(flows.TAG_RECUSOU,), optout=True),
                        lead=lead, conversation_id="c1", evidencia=CLIQUE_PARAR)

    assert ordem == ["descadastrado", "blacklist"]
    assert crm.mover.call_args.args[1] == effects.STAGE_DESCADASTRADO[0]


def test_card_em_outro_funil_nao_e_movido(lead):
    """Um lead da coorte pode ter card no funil do João ou na Blacklist.

    Mover o card errado é pior do que não mover nenhum — e `move_deal_to_stage_key`
    sozinho não protege: sem a key, ele cai em fallback por LABEL exato
    (leads/service.py:1217), e "Descadastrado" é rótulo que qualquer funil pode ganhar.
    """
    outro = _deal(pipeline="8988e852-2836-4add-b023-4db4d6cd0e6e")  # Blacklist
    with _crm_mockado(deal=outro) as crm:
        ok = effects.aplicar(Efeitos(handoff=True, recontato_dias=30, optout=True),
                             lead=lead, conversation_id="c1", evidencia=CLIQUE_PARAR)

    assert ok is True
    crm.mover.assert_not_called()


def test_lead_sem_card_aberto_nao_quebra_o_desfecho(lead):
    with _crm_mockado(deal=None) as crm:
        ok = effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1")

    assert ok is True
    crm.mover.assert_not_called()


def test_falha_ao_mover_o_card_nao_desfaz_o_desfecho(lead):
    """Fail-soft: opt-out e handoff já foram gravados nas colunas do lead."""
    with _crm_mockado() as crm:
        crm.deal.side_effect = RuntimeError("supabase fora do ar")
        ok = effects.aplicar(Efeitos(handoff=True, optout=True), lead=lead,
                             conversation_id="c1", evidencia=CLIQUE_PARAR)

    assert ok is True
    crm.side.assert_called_once()


def test_fixture_do_lead_e_isolada_por_teste(lead):
    """`aplicar` MUTA o lead: `atualizar_metadata` faz `lead["metadata"] = meta`.

    Era um dict de módulo compartilhado entre todos os testes; o carimbo de um teste
    (handoff, recontatar_em, pretexto_contestado) vazava para o seguinte e o resultado
    passava a depender da ordem de execução. Este teste documenta a mutação e prova
    que ela parte de um metadata vazio.
    """
    assert lead["metadata"] == {}, "fixture chegou suja: alguém compartilhou o dict de novo"
    with _crm_mockado():
        effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1")
    assert "handoff" in lead["metadata"]
