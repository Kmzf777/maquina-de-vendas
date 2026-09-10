"""O DISPARO do agente de botões: payload custom, preflight dos rótulos e o 131049.

Três buracos medidos na base de código em 09/09/2026, todos no caminho do primeiro
toque — o único caminho que existe para 1.208 leads sem janela de 24h aberta:

1. `grep -rn sub_type backend/app` devolvia ZERO. Sem payload custom, o webhook do
   quick reply devolve o PRÓPRIO RÓTULO como `button.payload` e o casamento do clique
   é comparação de string. Aqui fixamos o componente
   `{"type":"button","sub_type":"quick_reply","index":N,...}` — emitido SÓ quando o
   agent_profile do broadcast é `kind='button_flow'`, e nunca no lugar do casamento
   por rótulo, que precisa seguir valendo para os templates já disparados.

2. Os rótulos vivem em dois lugares (Meta e `button_flow/flows.py`) e divergir é
   silencioso: o lead clica e o fluxo trata como texto livre. O preflight passa a
   bloquear o /start quando o template do perfil `button_flow` não casa, rótulo a
   rótulo E na ordem, com nenhuma trilha.

3. `grep -rn 131049 backend/app` devolvia ZERO. 131049 é a Meta segurando a mensagem
   pelo cap de marketing DO USUÁRIO — não é falha e não é permanente (a doc manda
   esperar >=24h; retentar antes pode render mais 24h de suspensão). Vira estado
   próprio `marketing_capped` com `retry_after`, nunca `failed`.

E um quarto teste, de documentação: por que os templates se chamam `recuperacao_*` e
não `reativacao_*` (TRAVA A do _hot_lead_guardrail).
"""
import asyncio

import httpx
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch

import app.broadcast.worker as worker_mod
from app.broadcast.worker import (
    MARKETING_CAPPED_STATUS,
    _build_template_components,
    _broadcast_agent_kind,
    _hot_lead_guardrail,
    _is_marketing_cap_error,
    _resolve_plano_de_botoes,
    _sweep_marketing_capped,
    _toque_do_disparo,
    montar_payload_botao,
)
from app.button_flow import flows
from app.templates.intent import COLD_REACTIVATION, classify_template_intent
from app.templates.preflight import (
    indices_quick_reply,
    resolver_trilha_por_rotulos,
    rotulos_quick_reply,
    validate_template_for_broadcast,
)


# ─── helpers de dados ─────────────────────────────────────────────────────────

def _componentes_do_template(rotulos, *, body="Olá, {{1}}!"):
    """Components no formato em que a Meta devolve (e em que o banco guarda)."""
    return [
        {"type": "BODY", "text": body},
        {
            "type": "BUTTONS",
            "buttons": [{"type": "QUICK_REPLY", "text": r} for r in rotulos],
        },
    ]


def _rotulos(trilha):
    return list(flows.ROTULOS_TEMPLATE_POR_TRILHA[trilha])


def _ids(trilha):
    return [b.id for b in flows.BOTOES_POR_TRILHA[trilha]]


def _componentes_de_botao(components):
    return [c for c in (components or []) if c.get("type") == "button"]


# ═══════════════════════════════════════════════════════════════════════════════
# C15 — payload custom por botão
# ═══════════════════════════════════════════════════════════════════════════════

def test_disparo_comum_nao_ganha_componente_de_botao():
    """Sem trilha (todo broadcast que não é fluxo de botões) o payload não é emitido.

    É o que mantém os templates já disparados funcionando: eles não têm payload e o
    motor casa pelo rótulo normalizado.
    """
    comps = _build_template_components({"__params_type__": "positional", "1": "Ana"}, {})
    assert _componentes_de_botao(comps) == []
    assert [c["type"] for c in comps] == ["body"]


def test_payload_por_botao_na_ordem_dos_rotulos_da_trilha():
    comps = _build_template_components(
        {"__params_type__": "positional", "1": "Ana"}, {},
        button_flow_trilha=flows.TRILHA_ESTOQUE,
    )
    botoes = _componentes_de_botao(comps)
    assert [b["index"] for b in botoes] == ["0", "1", "2"]
    assert all(b["sub_type"] == "quick_reply" for b in botoes)
    payloads = [b["parameters"][0]["payload"] for b in botoes]
    assert [p.split("|")[1] for p in payloads] == _ids(flows.TRILHA_ESTOQUE)
    assert [p.split("|")[1] for p in payloads] == ["repor", "adiar", "optout"]
    assert all(p["type"] == "payload" for b in botoes for p in b["parameters"])


def test_payload_carrega_o_ID_e_nao_o_rotulo_da_trilha():
    """Trilha A rotula 'Retomar o pedido' e trilha B 'Preciso repor' — MESMO id `repor`.

    É exatamente esse desacoplamento que o payload custom compra: o motor decide por
    id, não por texto de marketing.
    """
    pedido = _componentes_de_botao(
        _build_template_components({}, {}, button_flow_trilha=flows.TRILHA_PEDIDO)
    )
    estoque = _componentes_de_botao(
        _build_template_components({}, {}, button_flow_trilha=flows.TRILHA_ESTOQUE)
    )
    assert pedido[0]["parameters"][0]["payload"].split("|")[1] == flows.ID_REPOR
    assert estoque[0]["parameters"][0]["payload"].split("|")[1] == flows.ID_REPOR
    # ...e a trilha viaja junto, para o nudge seguinte usar o rótulo certo.
    assert pedido[0]["parameters"][0]["payload"].split("|")[2] == flows.TRILHA_PEDIDO
    assert estoque[0]["parameters"][0]["payload"].split("|")[2] == flows.TRILHA_ESTOQUE


def test_trilha_de_cadastro_usa_manter_e_atualizar():
    """A trilha C não vende: os ids são outros e vêm dos dados, não de um literal."""
    botoes = _componentes_de_botao(
        _build_template_components({}, {}, button_flow_trilha=flows.TRILHA_CADASTRO)
    )
    ids = [b["parameters"][0]["payload"].split("|")[1] for b in botoes]
    assert ids == [flows.ID_MANTER, flows.ID_ATUALIZAR, flows.ID_OPTOUT]


def test_payload_convive_com_body_e_header():
    comps = _build_template_components(
        {
            "__params_type__": "positional", "1": "Ana",
            "__header_type__": "IMAGE", "__header_url__": "https://x/y.jpg",
        },
        {},
        button_flow_trilha=flows.TRILHA_ESTOQUE,
    )
    assert [c["type"] for c in comps] == ["header", "body", "button", "button", "button"]


def test_template_sem_variaveis_ainda_emite_os_botoes():
    """O early-return de `not template_variables` não pode comer o payload."""
    comps = _build_template_components({}, {}, button_flow_trilha=flows.TRILHA_ESTOQUE)
    assert len(_componentes_de_botao(comps)) == 3
    assert _build_template_components({}, {}) is None


def test_trilha_desconhecida_e_ignorada_em_vez_de_estourar():
    assert _build_template_components({}, {}, button_flow_trilha="inexistente") is None


def test_formato_do_payload_carrega_flow_id_e_toque():
    payload = montar_payload_botao(flows.ID_OPTOUT, flows.TRILHA_CADASTRO, 2)
    assert payload == f"{flows.FLOW_ID}|optout|cadastro|t2"
    # Cabe folgado no limite da Meta para payload de quick reply.
    assert len(payload) <= 128


def test_toque_do_disparo_default_e_override():
    assert _toque_do_disparo({}) == 1
    assert _toque_do_disparo({"template_variables": {"__flow_toque__": 2}}) == 2
    assert _toque_do_disparo({"template_variables": {"__flow_toque__": "x"}}) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Resolução da trilha (de onde a ORDEM dos payloads vem)
# ═══════════════════════════════════════════════════════════════════════════════

def _sb_template(components, kind="button_flow"):
    """Mock de Supabase que responde agent_profiles.kind e message_templates.components."""
    sb = MagicMock()

    def _table(name):
        t = MagicMock()
        if name == "agent_profiles":
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
                [{"kind": kind, "prompt_key": "bot_reativacao"}]
            )
        elif name == "message_templates":
            t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
                [{"components": components}] if components is not None else []
            )
        return t

    sb.table.side_effect = _table
    return sb


_BC_FLUXO = {
    "id": "bc-1", "template_name": "recuperacao_estoque_v1",
    "template_language_code": "pt_BR", "template_variables": {},
    "agent_profile_id": "prof-1",
}


def test_trilha_vem_dos_rotulos_aprovados_do_template():
    sb = _sb_template(_componentes_do_template(_rotulos(flows.TRILHA_ESTOQUE)))
    plano = _resolve_plano_de_botoes(sb, dict(_BC_FLUXO))
    assert plano.trilha == flows.TRILHA_ESTOQUE
    assert plano.indices == (0, 1, 2)


def test_rotulos_divergentes_nao_inventam_trilha():
    """Sem casar, NÃO emite payload — índice adivinhado trocaria o efeito dos botões."""
    sb = _sb_template(_componentes_do_template(["Sim", "Não", "Talvez"]))
    assert _resolve_plano_de_botoes(sb, dict(_BC_FLUXO)) is None


def test_template_ausente_no_banco_degrada_para_sem_payload():
    sb = _sb_template(None)
    assert _resolve_plano_de_botoes(sb, dict(_BC_FLUXO)) is None


def test_flow_trilha_forcada_e_conferida_contra_os_rotulos_aprovados():
    """Repro do desalinhamento entre código e docstring (revisão 09/09/2026).

    A docstring promete "deduzida dos RÓTULOS APROVADOS", mas o escape hatch
    `__flow_trilha__` devolvia ANTES de consultar o banco — sem conferir rótulo nem
    contagem de botões, e portanto sem nada que garantisse o índice do payload.
    Agora o banco é consultado sempre; o escape hatch só vale onde ele foi feito para
    valer: template aprovado cujos rótulos não casam com nenhuma trilha.
    """
    fora_do_padrao = _componentes_do_template(["Quero mais café", "Depois eu vejo", "Chega"])
    sb = _sb_template(fora_do_padrao)
    bc = dict(_BC_FLUXO, template_variables={"__flow_trilha__": flows.TRILHA_CADASTRO})

    plano = _resolve_plano_de_botoes(sb, bc)

    assert plano.trilha == flows.TRILHA_CADASTRO
    assert plano.indices == (0, 1, 2)
    sb.table.assert_any_call("message_templates")  # foi, sim, ao banco


def test_flow_trilha_forcada_que_conflita_com_os_rotulos_nao_emite_payload():
    """Conflito = alguém se enganou. Payload trocado é pior que payload nenhum."""
    sb = _sb_template(_componentes_do_template(_rotulos(flows.TRILHA_ESTOQUE)))
    bc = dict(_BC_FLUXO, template_variables={"__flow_trilha__": flows.TRILHA_CADASTRO})
    assert _resolve_plano_de_botoes(sb, bc) is None


def test_flow_trilha_forcada_com_numero_errado_de_botoes_nao_emite_payload():
    """Dois quick replies não endereçam três payloads — o terceiro cairia no vazio."""
    sb = _sb_template(_componentes_do_template(["Quero mais café", "Chega"]))
    bc = dict(_BC_FLUXO, template_variables={"__flow_trilha__": flows.TRILHA_CADASTRO})
    assert _resolve_plano_de_botoes(sb, bc) is None


def test_flow_trilha_forcada_vale_sozinha_quando_o_template_e_ilegivel():
    """Sem conseguir ler o template, o escape hatch é tudo o que resta (sequencial)."""
    sb = _sb_template(None)
    bc = dict(_BC_FLUXO, template_variables={"__flow_trilha__": flows.TRILHA_CADASTRO})
    plano = _resolve_plano_de_botoes(sb, bc)
    assert plano.trilha == flows.TRILHA_CADASTRO
    assert plano.indices == (0, 1, 2)


def test_kind_do_perfil_e_fail_open_quando_a_coluna_nao_existe():
    """A coluna `kind` só existe depois da migration 20260820 — erro aqui não trava disparo."""
    sb = MagicMock()
    sb.table.return_value.select.side_effect = Exception("column agent_profiles.kind does not exist")
    assert _broadcast_agent_kind(sb, "prof-1") is None
    assert _broadcast_agent_kind(sb, None) is None


# ═══════════════════════════════════════════════════════════════════════════════
# C16 — preflight: os rótulos do template × flows.py
# ═══════════════════════════════════════════════════════════════════════════════

def _sb_preflight(components, kind="button_flow"):
    """message_templates.select(...).eq(name).execute() + agent_profiles.select(kind)."""
    sb = MagicMock()

    def _table(name):
        t = MagicMock()
        if name == "agent_profiles":
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
                [{"kind": kind}]
            )
        else:
            t.select.return_value.eq.return_value.execute.return_value.data = [
                {"name": "recuperacao_estoque_v1", "language": "pt_BR",
                 "status": "approved", "components": components},
            ]
        return t

    sb.table.side_effect = _table
    return sb


def _preflight(components, *, kind="button_flow", agent_profile_id="prof-1"):
    sb = _sb_preflight(components, kind=kind)
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        return asyncio.run(validate_template_for_broadcast(
            "recuperacao_estoque_v1", "pt_BR",
            {"__params_type__": "positional", "1": "{{primeiro_nome}}"}, None,
            agent_profile_id=agent_profile_id,
        ))


@pytest.fixture(autouse=True)
def _preflight_on(monkeypatch):
    """A suíte roda com PREFLIGHT_TEMPLATE=off por hermeticidade; aqui o gate é o objeto."""
    monkeypatch.setenv("PREFLIGHT_TEMPLATE", "on")


@pytest.mark.parametrize("trilha", sorted(flows.ROTULOS_TEMPLATE_POR_TRILHA))
def test_preflight_aceita_o_template_de_cada_trilha(trilha):
    assert _preflight(_componentes_do_template(_rotulos(trilha))) == []


def test_preflight_bloqueia_template_sem_botoes():
    errors = _preflight([{"type": "BODY", "text": "Olá, {{1}}!"}])
    assert len(errors) == 1
    assert "QUICK_REPLY" in errors[0]


def test_preflight_bloqueia_rotulo_divergente_dizendo_o_esperado():
    errors = _preflight(_componentes_do_template(
        ["Preciso repor", "Ainda tenho estoque", "Nao tenho interesse"],
    ))
    assert len(errors) == 1
    # A mensagem tem que servir para o operador corrigir sem abrir o código.
    assert "Nao tenho interesse" in errors[0]
    assert "Parar mensagens" in errors[0]
    for trilha in flows.ROTULOS_TEMPLATE_POR_TRILHA:
        assert trilha in errors[0]


def test_preflight_bloqueia_ordem_trocada():
    """A ordem é carga útil: o payload endereça o botão por índice."""
    invertidos = list(reversed(_rotulos(flows.TRILHA_ESTOQUE)))
    errors = _preflight(_componentes_do_template(invertidos))
    assert len(errors) == 1


def test_preflight_ignora_caixa_e_acento_como_o_motor():
    """A comparação é a MESMA do casamento do clique (engine.normalizar)."""
    assert _preflight(_componentes_do_template(
        ["  PRECISO REPOR", "Ainda tenho estóque", "Parar Mensagens"],
    )) == []


def test_preflight_reprova_botao_que_nao_gera_webhook():
    """Botão URL não produz clique de volta — para o fluxo, ele não existe."""
    comps = _componentes_do_template(_rotulos(flows.TRILHA_ESTOQUE))
    comps[1]["buttons"][1] = {"type": "URL", "text": "Ainda tenho estoque", "url": "https://x"}
    errors = _preflight(comps)
    assert len(errors) == 1


def test_preflight_nao_olha_botoes_em_perfil_llm():
    """Campanha normal com template sem botão continua passando (checagem 5 não roda)."""
    assert _preflight([{"type": "BODY", "text": "Olá, {{1}}!"}], kind="llm") == []
    assert _preflight([{"type": "BODY", "text": "Olá, {{1}}!"}], agent_profile_id=None) == []


def test_helpers_de_rotulo_sao_puros():
    assert rotulos_quick_reply(_componentes_do_template(["A", "B"])) == ["A", "B"]
    assert rotulos_quick_reply(None) == []
    assert resolver_trilha_por_rotulos([]) is None
    assert resolver_trilha_por_rotulos(_rotulos(flows.TRILHA_PEDIDO)) == flows.TRILHA_PEDIDO
    assert indices_quick_reply(None) == []


# ═══════════════════════════════════════════════════════════════════════════════
# C16 rodava só no teste: o chamador real não passava o agent_profile_id
# ═══════════════════════════════════════════════════════════════════════════════
# Achado da revisão de 09/09/2026: app/broadcast/router.py chamava
# validate_template_for_broadcast com 4 posicionais. Sem o 5º, _agent_profile_kind(None)
# devolve None, nunca bate 'button_flow' e a checagem dos rótulos era pulada SEMPRE em
# produção — enquanto os 36 testes acima passavam, porque chamam a função direto.

def _sb_start_router(broadcast):
    """Supabase do /start: sem alerta de billing, o broadcast pedido e 3 leads pendentes."""
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = broadcast
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 3
    return sb


_BC_START = {
    "id": "b-1", "status": "draft", "channel_id": None,
    "template_name": "recuperacao_estoque_v1", "template_language_code": "pt_BR",
    "template_variables": {"__params_type__": "positional", "1": "{{primeiro_nome}}"},
    "agent_profile_id": "prof-1",
}


def _start(components):
    """Roda o /start DE VERDADE (preflight não mockado) contra estes components."""
    import app.broadcast.router as router_mod

    sb_router = _sb_start_router(dict(_BC_START))
    with patch.object(router_mod, "get_supabase", return_value=sb_router), \
         patch("app.templates.preflight.get_supabase", return_value=_sb_preflight(components)):
        try:
            return sb_router, asyncio.run(router_mod.start_broadcast("b-1")), None
        except HTTPException as exc:
            return sb_router, None, exc


def test_start_bloqueia_template_de_botoes_divergente():
    """O repro: rótulos errados num perfil button_flow têm que barrar o /start.

    Antes do conserto o /start liberava (status='running') e 1.208 leads recebiam uma
    mensagem cujos cliques o motor trata como texto livre.
    """
    sb_router, resultado, exc = _start(_componentes_do_template(["Sim", "Não", "Talvez"]))

    assert resultado is None
    assert exc is not None and exc.status_code == 400
    assert "não casam com nenhuma trilha" in exc.detail
    # status INTOCADO — o único update do /start é o status=running.
    sb_router.table.return_value.update.assert_not_called()


def test_start_libera_o_template_de_botoes_correto():
    """Contraprova: com os rótulos certos a rota segue liberando o disparo."""
    sb_router, resultado, exc = _start(_componentes_do_template(_rotulos(flows.TRILHA_ESTOQUE)))

    assert exc is None
    assert resultado["status"] == "started"
    assert sb_router.table.return_value.update.call_args[0][0] == {"status": "running"}


def test_a_checagem_de_botoes_depende_do_quinto_argumento():
    """A armadilha, nua: mesma chamada, mesmo template — só muda passar o perfil."""
    divergente = _componentes_do_template(["Sim", "Não", "Talvez"])
    assert _preflight(divergente, agent_profile_id=None) == []       # como era o router
    assert len(_preflight(divergente, agent_profile_id="prof-1")) == 1  # como é agora


# ═══════════════════════════════════════════════════════════════════════════════
# O índice do payload conta TODOS os botões, não só os quick replies
# ═══════════════════════════════════════════════════════════════════════════════

def _com_botao_url(rotulos, posicao=0):
    """Template aprovado com um botão URL misturado aos quick replies."""
    comps = _componentes_do_template(rotulos)
    comps[1]["buttons"].insert(
        posicao, {"type": "URL", "text": "Ver catálogo", "url": "https://x"},
    )
    return comps


def test_indices_quick_reply_contam_a_posicao_real_no_template():
    comps = _com_botao_url(_rotulos(flows.TRILHA_ESTOQUE))
    # Os rótulos casam a trilha normalmente...
    assert resolver_trilha_por_rotulos(rotulos_quick_reply(comps)) == flows.TRILHA_ESTOQUE
    # ...mas os botões NÃO estão em 0,1,2 — e era daí que o payload saía.
    assert indices_quick_reply(comps) == [1, 2, 3]


def test_preflight_bloqueia_botao_url_mesmo_com_os_rotulos_certos():
    """Repro do desalinhamento: rótulos certos + um URL na frente = payload deslocado."""
    errors = _preflight(_com_botao_url(_rotulos(flows.TRILHA_ESTOQUE)))
    assert len(errors) == 1
    assert "URL" in errors[0]
    assert "QUICK_REPLY" in errors[0]


def test_payload_sai_no_indice_real_quando_o_template_mistura_botoes():
    """Defesa em profundidade: o preflight não roda pela UI, então o worker se defende.

    Sem isto o payload de `optout` ia no index 2 — que neste template é o botão
    "Ainda tenho estoque". Quem dissesse "ainda tenho" seria dado como opt-out.
    """
    sb = _sb_template(_com_botao_url(_rotulos(flows.TRILHA_ESTOQUE)))
    plano = _resolve_plano_de_botoes(sb, dict(_BC_FLUXO))
    assert plano.indices == (1, 2, 3)

    botoes = _componentes_de_botao(_build_template_components(
        {}, {}, button_flow_trilha=plano.trilha, button_flow_indices=plano.indices,
    ))
    assert [b["index"] for b in botoes] == ["1", "2", "3"]
    por_indice = {b["index"]: b["parameters"][0]["payload"].split("|")[1] for b in botoes}
    assert por_indice == {"1": flows.ID_REPOR, "2": flows.ID_ADIAR, "3": flows.ID_OPTOUT}


# ═══════════════════════════════════════════════════════════════════════════════
# C17 — 131049 vira reagendamento, não falha
# ═══════════════════════════════════════════════════════════════════════════════

def test_classificacao_do_131049():
    assert _is_marketing_cap_error({"code": 131049}) is True
    assert _is_marketing_cap_error({"code": "131049"}) is True
    assert _is_marketing_cap_error({
        "message": "This message was not delivered to maintain healthy ecosystem engagement",
    }) is True
    # Vizinhos que TÊM tratamento próprio e não podem ser confundidos:
    assert _is_marketing_cap_error({"code": 131026, "message": "Message undeliverable"}) is False
    assert _is_marketing_cap_error({"code": 131042, "message": "Business eligibility"}) is False
    assert _is_marketing_cap_error({"code": 132000}) is False
    assert _is_marketing_cap_error({}) is False


# ─── harness de lote (molde: test_broadcast_template_error_pause_2026_07_10) ───

def _make_send_sb(*, kind="llm", template_components=None, defer_ok=True):
    """Supabase de lote. `kind` decide se o broadcast é fluxo de botões."""
    claim_chain = MagicMock()
    claim_chain.eq.return_value = claim_chain
    claim_chain.lt.return_value = claim_chain
    claim_chain.filter.return_value = claim_chain
    claim_chain.execute.return_value = MagicMock(data=[{"id": "bl-x"}])

    defer_chain = MagicMock()
    defer_chain.eq.return_value = defer_chain
    if defer_ok:
        defer_chain.execute.return_value = MagicMock(data=[{"id": "bl-x"}])
    else:
        # Migration 20260909 não aplicada: o UPDATE estoura no PostgREST.
        defer_chain.execute.side_effect = Exception("column retry_after does not exist")

    updates: list[dict] = []

    def _bl_update(payload):
        updates.append(payload)
        return defer_chain if "retry_after" in payload else claim_chain

    mock_bl = MagicMock()
    mock_bl.update.side_effect = _bl_update
    mock_bl.select.return_value.eq.return_value.eq.return_value.is_.return_value.or_.return_value.limit.return_value.execute.return_value.data = []

    mock_bc = MagicMock()
    mock_bc.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "running"}

    mock_ap = MagicMock()
    mock_ap.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"kind": kind, "prompt_key": "bot_reativacao"},
    ]
    mock_tpl = MagicMock()
    mock_tpl.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
        [{"components": template_components}] if template_components else []
    )

    tables = {
        "broadcast_leads": mock_bl, "broadcasts": mock_bc,
        "agent_profiles": mock_ap, "message_templates": mock_tpl,
    }
    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: tables.get(name, MagicMock())
    return mock_sb, mock_bc, updates


def _meta_http_error(code, message="erro"):
    resp = httpx.Response(
        400, json={"error": {"message": message, "code": code}},
        request=httpx.Request("POST", "https://graph.facebook.com/x"),
    )
    return httpx.HTTPStatusError("400", request=resp.request, response=resp)


_BROADCAST_LOTE = {
    "id": "bc-uuid", "name": "Recuperação piloto", "status": "running", "channel_id": "ch-uuid",
    "template_name": "recuperacao_estoque_v1", "template_language_code": "pt_BR",
    "template_variables": {"__params_type__": "positional", "1": "{{primeiro_nome}}"},
    "agent_profile_id": "prof-1", "send_interval_min": 0, "send_interval_max": 0,
}


def _bl(i):
    return {"id": f"bl-{i}", "leads": {"id": f"lead-{i}", "phone": f"553499999000{i}", "wa_id": None, "name": "T"}}


def _run_batch(provider, leads, mock_sb, broadcast=None):
    patches = dict(
        get_supabase=patch("app.broadcast.worker.get_supabase", return_value=mock_sb),
        pending=patch("app.broadcast.worker.get_pending_broadcast_leads", return_value=leads),
        channel=patch("app.broadcast.worker.get_channel_by_id", return_value={"id": "ch-uuid", "mode": "human"}),
        provider=patch("app.broadcast.worker.get_provider", return_value=provider),
        blacklist=patch("app.broadcast.worker.is_lead_blacklisted", return_value=False),
        cliente=patch("app.broadcast.worker.lead_is_customer", return_value=False),
        contato_vivo=patch("app.broadcast.worker.lead_recently_engaged", return_value=False),
        dedup=patch("app.broadcast.worker._template_dedup_guardrail", return_value=None),
        resolve=patch("app.broadcast.worker.resolve_send_target", side_effect=lambda lead, fallback, **k: fallback),
        render=patch("app.broadcast.worker._render_template_body", new=AsyncMock(return_value="txt")),
        mark_sent=patch("app.broadcast.worker.mark_broadcast_lead_sent"),
        mark_failed=patch("app.broadcast.worker.mark_broadcast_lead_failed"),
        inc_sent=patch("app.broadcast.worker.increment_broadcast_sent"),
        inc_failed=patch("app.broadcast.worker.increment_broadcast_failed"),
        requeue=patch("app.broadcast.worker.requeue_broadcast_lead"),
        wamid=patch("app.broadcast.worker.save_broadcast_lead_wamid"),
        note=patch("app.broadcast.worker.record_dispatch_note"),
        conv=patch("app.broadcast.worker.get_or_create_conversation", return_value={"id": "conv-1"}),
        upd_conv=patch("app.broadcast.worker.update_conversation"),
        upd_lead=patch("app.broadcast.worker.update_lead"),
        save_msg=patch("app.broadcast.worker.save_message"),
        trigger=patch("app.automation.triggers.fire_trigger", new_callable=AsyncMock),
        alert=patch("app.alerts.service.create_system_alert"),
        sleep=patch("asyncio.sleep", new_callable=AsyncMock),
    )
    mocks = {}
    started = []
    try:
        for name, p in patches.items():
            mocks[name] = p.start()
            started.append(p)
        asyncio.run(worker_mod.process_single_broadcast(dict(broadcast or _BROADCAST_LOTE)))
    finally:
        for p in started:
            p.stop()
    return mocks


@pytest.fixture(autouse=True)
def _clear_streaks():
    worker_mod._template_error_streaks.clear()
    yield
    worker_mod._template_error_streaks.clear()


def test_131049_reagenda_em_vez_de_falhar():
    provider = AsyncMock()
    provider.send_template = AsyncMock(side_effect=_meta_http_error(
        131049, "This message was not delivered to maintain healthy ecosystem engagement",
    ))
    mock_sb, mock_bc, updates = _make_send_sb()

    mocks = _run_batch(provider, [_bl(1)], mock_sb)

    # NÃO é falha: nada de failed, nada de contador, nada de retry imediato.
    mocks["mark_failed"].assert_not_called()
    mocks["inc_failed"].assert_not_called()
    mocks["requeue"].assert_not_called()
    # É um estado próprio, com data de volta no futuro.
    adiamentos = [u for u in updates if u.get("status") == MARKETING_CAPPED_STATUS]
    assert len(adiamentos) == 1
    assert adiamentos[0]["claimed_at"] is None
    assert adiamentos[0]["retry_after"] > worker_mod.datetime.now(worker_mod.timezone.utc).isoformat()
    # E não pausa a campanha (o cap é POR USUÁRIO; os outros leads seguem).
    assert {"status": "paused"} not in [c[0][0] for c in mock_bc.update.call_args_list]


def test_131049_nao_alimenta_o_circuit_breaker_de_template():
    """Três caps seguidos não são um template quebrado — a campanha não pode pausar."""
    provider = AsyncMock()
    provider.send_template = AsyncMock(side_effect=[_meta_http_error(131049) for _ in range(3)])
    mock_sb, mock_bc, _ = _make_send_sb()

    mocks = _run_batch(provider, [_bl(1), _bl(2), _bl(3)], mock_sb)

    assert worker_mod._template_error_streaks.get("bc-uuid") is None
    assert {"status": "paused"} not in [c[0][0] for c in mock_bc.update.call_args_list]
    mocks["alert"].assert_not_called()


def test_sem_a_migration_o_131049_cai_no_tratamento_antigo():
    """Fail-soft: sem `retry_after` o lead não pode ficar preso em 'processing'."""
    provider = AsyncMock()
    provider.send_template = AsyncMock(side_effect=_meta_http_error(131049))
    mock_sb, _, _ = _make_send_sb(defer_ok=False)

    mocks = _run_batch(provider, [_bl(1)], mock_sb)

    mocks["mark_failed"].assert_called_once()
    mocks["inc_failed"].assert_called_once()


def test_erro_comum_continua_falhando_normalmente():
    provider = AsyncMock()
    provider.send_template = AsyncMock(side_effect=_meta_http_error(131026, "Message undeliverable"))
    mock_sb, _, updates = _make_send_sb()

    mocks = _run_batch(provider, [_bl(1)], mock_sb)

    mocks["mark_failed"].assert_called_once()
    assert [u for u in updates if u.get("status") == MARKETING_CAPPED_STATUS] == []


def test_sweep_adota_o_131049_que_chegou_pelo_webhook():
    """O caminho comum: a Meta aceita o send e só reporta a retenção pelo status webhook.

    meta_router grava `failed` + o title da Meta; o varredor converte em adiamento e
    desfaz o contador de falha (senão a mesma pessoa conta como falha hoje e envio amanhã).
    """
    mock_sb, _, updates = _make_send_sb()
    mock_sb.table("broadcast_leads").select.return_value.eq.return_value.eq.return_value.is_.return_value.or_.return_value.limit.return_value.execute.return_value.data = [
        {"id": "bl-9", "error_message": "This message was not delivered to maintain healthy ecosystem engagement"},
        {"id": "bl-8", "error_message": "Message undeliverable"},
    ]

    _sweep_marketing_capped(mock_sb, "bc-uuid")

    adiamentos = [u for u in updates if u.get("status") == MARKETING_CAPPED_STATUS]
    assert len(adiamentos) == 1  # o 131026 NÃO é adotado
    # Lead sem sent_at/wamid nunca foi contado como enviado (a falha veio do send
    # síncrono): só o contador de falha é desfeito.
    mock_sb.rpc.assert_called_once_with("decrement_broadcast_failed", {"broadcast_id_param": "bc-uuid"})


def _linha_capada(**extra):
    linha = {
        "id": "bl-9",
        "error_message": "This message was not delivered to maintain healthy ecosystem engagement",
    }
    linha.update(extra)
    return linha


def test_sweep_desfaz_TAMBEM_o_contador_de_envio_do_caminho_assincrono():
    """Repro do contador que não fechava (revisão 09/09/2026).

    Caminho assíncrono — o provável: a Meta devolveu HTTP 200 + wamid, o worker já
    chamou increment_broadcast_sent, e só DEPOIS o webhook reportou a retenção como
    falha. Desfazer só a falha deixava a pessoa contada como enviada hoje e contada de
    novo no reenvio de amanhã: `sent` do broadcast passa do total de leads.
    """
    mock_sb, _, updates = _make_send_sb()
    mock_sb.table("broadcast_leads").select.return_value.eq.return_value.eq.return_value.is_.return_value.or_.return_value.limit.return_value.execute.return_value.data = [
        _linha_capada(sent_at="2026-09-09T12:00:00+00:00", wamid="wamid.aceito"),
    ]

    _sweep_marketing_capped(mock_sb, "bc-uuid")

    rpcs = [c[0][0] for c in mock_sb.rpc.call_args_list]
    assert rpcs == ["decrement_broadcast_failed", "decrement_broadcast_sent"]
    assert all(c[0][1] == {"broadcast_id_param": "bc-uuid"} for c in mock_sb.rpc.call_args_list)
    # E a marca do envio que ninguém recebeu sai da linha: sem isso o lead ficaria
    # "enviado" para efeito de painel e um webhook atrasado do MESMO wamid o marcaria
    # failed outra vez, refazendo a contabilidade que acabamos de desfazer.
    adiamento = [u for u in updates if u.get("status") == MARKETING_CAPPED_STATUS][0]
    assert adiamento["sent_at"] is None
    assert adiamento["wamid"] is None


def test_sweep_nao_desfaz_envio_que_nunca_foi_contado():
    """Lead que falhou no send síncrono (sem wamid): mexer em `sent` inventaria um -1."""
    mock_sb, _, updates = _make_send_sb()
    mock_sb.table("broadcast_leads").select.return_value.eq.return_value.eq.return_value.is_.return_value.or_.return_value.limit.return_value.execute.return_value.data = [
        _linha_capada(sent_at=None, wamid=None),
    ]

    _sweep_marketing_capped(mock_sb, "bc-uuid")

    assert [c[0][0] for c in mock_sb.rpc.call_args_list] == ["decrement_broadcast_failed"]
    adiamento = [u for u in updates if u.get("status") == MARKETING_CAPPED_STATUS][0]
    assert "sent_at" not in adiamento and "wamid" not in adiamento


def test_sweep_nao_derruba_o_lote_se_a_rpc_de_envio_nao_existir():
    """Fail-soft: contador errado é ruído de painel; parar a varredura prende leads."""
    mock_sb, _, updates = _make_send_sb()
    mock_sb.table("broadcast_leads").select.return_value.eq.return_value.eq.return_value.is_.return_value.or_.return_value.limit.return_value.execute.return_value.data = [
        _linha_capada(sent_at="2026-09-09T12:00:00+00:00", wamid="wamid.aceito"),
    ]
    mock_sb.rpc.side_effect = Exception("function decrement_broadcast_sent does not exist")

    _sweep_marketing_capped(mock_sb, "bc-uuid")

    assert len([u for u in updates if u.get("status") == MARKETING_CAPPED_STATUS]) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Integração do lote: quem ganha payload e flow_state
# ═══════════════════════════════════════════════════════════════════════════════

def test_lote_de_fluxo_de_botoes_envia_payload_e_semeia_o_estado():
    provider = AsyncMock()
    provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.ok"}]})
    mock_sb, _, _ = _make_send_sb(
        kind="button_flow",
        template_components=_componentes_do_template(_rotulos(flows.TRILHA_ESTOQUE)),
    )

    mocks = _run_batch(provider, [_bl(1)], mock_sb)

    componentes = provider.send_template.call_args.kwargs["components"]
    botoes = _componentes_de_botao(componentes)
    assert [b["parameters"][0]["payload"].split("|")[1] for b in botoes] == _ids(flows.TRILHA_ESTOQUE)
    # flow_state semeado NO ENVIO — o lead que responde em texto já tem a trilha certa.
    estados = [
        c.kwargs["flow_state"] for c in mocks["upd_conv"].call_args_list
        if "flow_state" in c.kwargs
    ]
    assert len(estados) == 1
    assert estados[0]["flow"] == flows.FLOW_ID
    assert estados[0]["node"] == flows.NO_INTERESSE
    assert estados[0]["trilha"] == flows.TRILHA_ESTOQUE
    assert estados[0]["nudged"] is False


def test_lote_comum_nao_emite_payload_nem_toca_flow_state():
    provider = AsyncMock()
    provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.ok"}]})
    mock_sb, _, _ = _make_send_sb(kind="llm")

    mocks = _run_batch(provider, [_bl(1)], mock_sb)

    assert _componentes_de_botao(provider.send_template.call_args.kwargs["components"]) == []
    assert all("flow_state" not in c.kwargs for c in mocks["upd_conv"].call_args_list)


def test_perfil_de_fluxo_com_template_divergente_dispara_sem_payload():
    """Defesa em profundidade do preflight: rótulo errado NÃO vira payload adivinhado."""
    provider = AsyncMock()
    provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.ok"}]})
    mock_sb, _, _ = _make_send_sb(
        kind="button_flow",
        template_components=_componentes_do_template(["Sim", "Não", "Talvez"]),
    )

    _run_batch(provider, [_bl(1)], mock_sb)

    assert _componentes_de_botao(provider.send_template.call_args.kwargs["components"]) == []


def test_lote_com_botao_url_no_template_usa_os_indices_reais():
    """Ponta a ponta do desalinhamento: o lote inteiro tem que endereçar 1,2,3."""
    provider = AsyncMock()
    provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.ok"}]})
    mock_sb, _, _ = _make_send_sb(
        kind="button_flow",
        template_components=_com_botao_url(_rotulos(flows.TRILHA_ESTOQUE)),
    )

    _run_batch(provider, [_bl(1)], mock_sb)

    botoes = _componentes_de_botao(provider.send_template.call_args.kwargs["components"])
    assert [b["index"] for b in botoes] == ["1", "2", "3"]
    assert [b["parameters"][0]["payload"].split("|")[1] for b in botoes] == _ids(flows.TRILHA_ESTOQUE)


# ═══════════════════════════════════════════════════════════════════════════════
# TRAVA A — por que os templates se chamam `recuperacao_*`
# ═══════════════════════════════════════════════════════════════════════════════
# Documenta o comportamento (não o altera): _hot_lead_guardrail rejeita QUALQUER lead
# com venda em `sales` quando o disparo é cold_reactivation, e o gatilho é o NOME do
# template conter "reativ" (templates/intent.py:_COLD_SUBSTRINGS). 208 dos 1.208 leads
# da coorte têm venda — a parte mais valiosa da lista. Um template chamado
# `reativacao_*` os apagaria da campanha em silêncio, um a um.

def test_template_recuperacao_nao_cai_na_trava_de_lead_quente():
    lead = {"id": "lead-quente"}
    intent = classify_template_intent("recuperacao_estoque_v1", "bot_reativacao")
    assert intent != COLD_REACTIVATION
    with patch("app.broadcast.worker.lead_is_customer", return_value=True):
        assert _hot_lead_guardrail(lead, intent) is None


def test_o_mesmo_template_chamado_reativacao_bloquearia_os_208_melhores():
    lead = {"id": "lead-quente"}
    intent = classify_template_intent("reativacao_estoque_v1", "bot_reativacao")
    assert intent == COLD_REACTIVATION
    with patch("app.broadcast.worker.lead_is_customer", return_value=True):
        motivo = _hot_lead_guardrail(lead, intent)
    assert motivo is not None and "cliente consolidado" in motivo


def test_disparar_o_fluxo_sob_a_persona_outbound_reativaria_a_trava():
    """Armadilha de configuração: a persona do disparo também liga a trava."""
    assert classify_template_intent("recuperacao_estoque_v1", "valeria_outbound") == COLD_REACTIVATION
