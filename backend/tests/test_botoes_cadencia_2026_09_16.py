"""§11 do desenho do registro de nos — ramificacao por BOTAO de template.

O QUE ESTES TESTES PROVAM
─────────────────────────
Template com dois botoes ("Continuar" / "Parar atendimento"). O lead clica em Parar
atendimento e o sistema entende apenas "respondeu alguma coisa": `is_optout_reply` so
reconhece DUAS frases exatas ("parar mensagens", "nao tenho interesse"), e o rotulo real
do botao nao e nenhuma delas. Sem `leads.opt_out`, sem funil Blacklist, sem cancelar
follow-up — e a esteira reinscreve o lead dias depois.

A causa era uma assinatura: `handle_campaign_reply(lead_id)` recebia SO o id. O dado
existe (`webhook/meta_parser.py` preserva `payload`/`title` e marca `parsed_type='button'`)
e era descartado na fronteira.

A correcao MUDA A DECISAO DE LUGAR: sai de um frozenset global de duas frases e passa a
ser DECLARADA NO NO (`on_reply_por_botao`). O teste 1 e a prova dessa mudanca — o
frozenset continua cego ao rotulo e, ainda assim, o opt-out e gravado.
"""
import contextlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.campaigns.worker import (
    _normalize_reply,
    handle_campaign_reply,
    is_optout_reply,
)

LEAD = {"id": "lead-1", "phone": "5534988861441", "opt_out": False}
AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def _no(tipo: str = "send", **cfg) -> dict:
    return {"type": tipo, "config": cfg}


def _matricula(node: dict, mid: str = "e1", **extra) -> dict:
    linha = {"id": mid, "campaign_id": "camp1", "lead_id": "lead-1", "campaign_nodes": node}
    linha.update(extra)
    return linha


GATILHO_CANCEL = [{"type": "trigger", "config": {"on_reply": "cancel"}, "next_node_id": "n1"}]
GATILHO_RESET = [{"type": "trigger", "config": {"on_reply": "reset"}, "next_node_id": "n1"}]
GATILHO_MUDO = [{"type": "trigger", "config": {}, "next_node_id": "n1"}]


class _Espioes(dict):
    """dict com acesso por atributo — `espioes.cancel` em vez de `espioes["cancel"]`."""

    def __getattr__(self, nome):
        try:
            return self[nome]
        except KeyError as exc:                       # pragma: no cover - erro de teste
            raise AttributeError(nome) from exc


@contextlib.contextmanager
def _ambiente(matriculas, gatilho=None, lead=None, **sobrepoe):
    """Isola TODA a borda de I/O do caminho de resposta.

    Os alvos de patch espelham os ja usados por `test_esteiras_on_reply.py`
    (`app.campaigns.service.list_nodes`, `app.campaigns.worker.cancel_enrollment`...):
    o modulo importa `cancel/pause/reset` no topo e resolve `list_nodes`/`get_lead` por
    import preguicoso dentro da funcao.
    """
    lead = LEAD if lead is None else lead
    with contextlib.ExitStack() as pilha:
        def p(alvo, **kw):
            return pilha.enter_context(patch(alvo, **kw))

        espioes = _Espioes(
            cancel=p("app.campaigns.worker.cancel_enrollment"),
            pause=p("app.campaigns.worker.pause_enrollment"),
            reset=p("app.campaigns.worker.reset_enrollment"),
            list_nodes=p("app.campaigns.service.list_nodes",
                         return_value=gatilho if gatilho is not None else []),
            update_enrollment=p("app.campaigns.service.update_enrollment",
                                **sobrepoe.get("update_enrollment", {})),
            get_lead=p("app.leads.service.get_lead", return_value=lead),
            update_lead=p("app.leads.service.update_lead",
                          **sobrepoe.get("update_lead", {})),
            efeitos=p("app.leads.service.apply_optout_side_effects"),
            observacao=p("app.leads.service.append_lead_observation"),
            save_message=p("app.leads.service.save_message"),
        )
        p("app.campaigns.service.get_active_enrollments_for_lead", return_value=matriculas)
        yield espioes


def _roda(node, texto=None, tipo=None, gatilho=None, lead=None, metadata=None, **sobrepoe):
    linha = _matricula(node)
    if metadata is not None:
        linha["metadata"] = metadata
    with _ambiente([linha], gatilho, lead, **sobrepoe) as espioes:
        handle_campaign_reply("lead-1", texto, tipo)
    espioes["matricula"] = linha
    return espioes


# ─── 1. O TESTE CENTRAL ──────────────────────────────────────────────────────────


class TestADecisaoMudouDeLugar:
    def test_1_frozenset_continua_cego_e_mesmo_assim_o_no_grava_o_optout(self):
        """A prova da §11: `is_optout_reply` NAO reconhece "Parar atendimento" (e nao
        deve — mexer nele e outro raio de impacto), e o no que DECLARA o rotulo grava o
        opt-out de verdade assim mesmo."""
        assert is_optout_reply("Parar atendimento") is False
        assert is_optout_reply("Continuar") is False

        e = _roda(
            _no("send", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="Parar atendimento", tipo="button",
        )

        e.update_lead.assert_called_once_with("lead-1", ai_enabled=False, opt_out=True)
        e.efeitos.assert_called_once()
        e.cancel.assert_called_once_with("e1")
        e.pause.assert_not_called()

    def test_1b_sem_o_mapa_o_mesmo_clique_apenas_pausa(self):
        """Contraprova: o mesmo texto, no mesmo no, sem a declaracao — o comportamento
        antigo (pausar) e o que acontece. Nada aqui e magica do texto."""
        e = _roda(_no("send"), texto="Parar atendimento", tipo="button", gatilho=GATILHO_MUDO)

        e.update_lead.assert_not_called()
        e.efeitos.assert_not_called()
        e.pause.assert_called_once_with("e1")


# ─── 2. PRECEDENCIA, UM TESTE POR NIVEL ──────────────────────────────────────────


class TestPrecedencia:
    """botao[resposta normalizada]  ->  on_reply do NO  ->  on_reply do GATILHO."""

    def test_2a_nivel_botao_vence_o_no_e_o_gatilho(self):
        e = _roda(
            _no("send", on_reply="pause", on_reply_por_botao={"continuar": "reset"}),
            texto="Continuar", tipo="button", gatilho=GATILHO_CANCEL,
        )
        e.reset.assert_called_once_with("e1", "n1")
        e.pause.assert_not_called()
        e.cancel.assert_not_called()

    def test_2b_nivel_no_vence_o_gatilho_quando_nenhum_botao_casa(self):
        e = _roda(
            _no("send", on_reply="pause", on_reply_por_botao={"continuar": "reset"}),
            texto="pode me mandar o preco do atacado?", tipo="text", gatilho=GATILHO_CANCEL,
        )
        e.pause.assert_called_once_with("e1")
        e.cancel.assert_not_called()
        e.reset.assert_not_called()

    def test_2c_nivel_gatilho_vale_quando_o_no_nao_declara_nada(self):
        e = _roda(
            _no("send", on_reply_por_botao={"continuar": "reset"}),
            texto="oi, tudo bem?", tipo="text", gatilho=GATILHO_CANCEL,
        )
        e.cancel.assert_called_once_with("e1")
        e.pause.assert_not_called()
        e.reset.assert_not_called()


# ─── 3. QUEM NAO CASA BOTAO CAI NA ESCADA DE BAIXO ───────────────────────────────


class TestRespostaQueNaoCasaBotao:
    def test_3a_cai_na_politica_do_no(self):
        e = _roda(
            _no("send", on_reply="reset", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="quero falar com alguem", tipo="text", gatilho=GATILHO_MUDO,
        )
        e.reset.assert_called_once_with("e1", "n1")
        e.update_lead.assert_not_called()

    def test_3b_sem_politica_no_no_cai_na_do_gatilho(self):
        e = _roda(
            _no("wait", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="quero falar com alguem", tipo="text", gatilho=GATILHO_CANCEL,
        )
        e.cancel.assert_called_once_with("e1")
        e.update_lead.assert_not_called()

    def test_3c_mapa_declarado_mas_resposta_ausente_nao_consulta_o_mapa(self):
        """Chamador antigo (`texto=None`) com no que declara botoes: sem texto nao ha
        rotulo a casar, e a escada de baixo decide."""
        e = _roda(_no("send", on_reply="cancel", on_reply_por_botao={"x": "optout"}))
        e.cancel.assert_called_once_with("e1")
        e.update_lead.assert_not_called()

    def test_3d_mapa_com_lixo_no_lugar_do_dicionario_nao_derruba_nada(self):
        """A tela grava o campo; um dia ela grava string. Fail-soft: cai na escada."""
        e = _roda(
            _no("send", on_reply="pause", on_reply_por_botao="parar atendimento"),
            texto="Parar atendimento", tipo="button",
        )
        e.pause.assert_called_once_with("e1")
        e.update_lead.assert_not_called()


# ─── 4. `optout` ESCREVE OS MESMOS CAMPOS E CANCELA ──────────────────────────────


class TestPoliticaOptout:
    def test_4a_espelha_registrar_optout_campo_a_campo(self):
        """Os MESMOS campos de `agent/tools.py::registrar_optout`: `leads.opt_out`,
        `ai_enabled=False`, `apply_optout_side_effects` (funil Blacklist + cancelamento
        dos follow-ups) e a observacao no card. Duas definicoes de "esta na blacklist"
        divergindo e exatamente o que `is_lead_blacklisted` nao pode ter."""
        e = _roda(
            _no("send", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="Parar atendimento", tipo="button",
        )

        e.update_lead.assert_called_once_with("lead-1", ai_enabled=False, opt_out=True)
        args, kwargs = e.efeitos.call_args
        assert args[0] == "lead-1" and args[1] == "5534988861441"
        assert kwargs["reason"] == "optout_botao"
        assert "OPT-OUT DEFINITIVO" in e.observacao.call_args[0][1]

    def test_4b_cancela_a_matricula(self):
        e = _roda(
            _no("send", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="Parar atendimento", tipo="button", gatilho=GATILHO_MUDO,
        )
        e.cancel.assert_called_once_with("e1")
        e.pause.assert_not_called()
        e.reset.assert_not_called()

    def test_4c_marcador_do_historico_nao_contamina_a_metrica_do_llm(self):
        """O QA diario conta `[registrar_optout]%` para medir o COMPORTAMENTO DO LLM.
        Opt-out de botao entra como `[optout_botao]`."""
        e = _roda(
            _no("send", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="Parar atendimento", tipo="button",
        )
        conteudo = e.save_message.call_args[0][2]
        assert "[optout_botao]" in conteudo
        assert "[registrar_optout]" not in conteudo

    def test_4d_lead_ja_na_blacklist_nao_e_regravado_mas_a_matricula_cancela(self):
        """Idempotencia do opt-out; a matricula, essa, tem de sair do ar de qualquer
        forma — e ela que manda o proximo toque."""
        e = _roda(
            _no("send", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="Parar atendimento", tipo="button",
            lead={"id": "lead-1", "phone": "5534988861441", "opt_out": True},
        )
        e.update_lead.assert_not_called()
        e.cancel.assert_called_once_with("e1")

    def test_4e_falha_ao_gravar_o_optout_ainda_cancela_a_matricula(self):
        """Fail-soft com prioridade certa: quem pediu para parar para de receber mesmo
        que o Supabase esteja fora do ar."""
        e = _roda(
            _no("send", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="Parar atendimento", tipo="button",
            update_lead={"side_effect": RuntimeError("supabase fora do ar")},
        )
        e.cancel.assert_called_once_with("e1")

    def test_4f_optout_tambem_vale_declarado_como_politica_do_no(self):
        """`optout` e um valor de `politica_resposta` como outro qualquer — o mapa de
        botoes e so o nivel mais especifico onde ele pode aparecer."""
        e = _roda(_no("send", on_reply="optout"), texto="nao quero mais nada", tipo="text")
        e.update_lead.assert_called_once_with("lead-1", ai_enabled=False, opt_out=True)
        e.cancel.assert_called_once_with("e1")

    def test_4g_optout_no_gatilho_vale_para_a_esteira_inteira(self):
        e = _roda(
            _no("wait"), texto="chega", tipo="text",
            gatilho=[{"type": "trigger", "config": {"on_reply": "optout"},
                      "next_node_id": "n1"}],
        )
        e.update_lead.assert_called_once_with("lead-1", ai_enabled=False, opt_out=True)
        e.cancel.assert_called_once_with("e1")


# ─── 5. A CONDICAO `clicou_botao` ────────────────────────────────────────────────


def _condicao(cfg_extra: dict, metadata) -> tuple:
    """Roda `engine._execute_condition` isolado e devolve (mock_update, mock_complete)."""
    from app.automation import engine

    enrollment = {"id": "e1", "lead_id": "lead-1", "metadata": metadata, "step_count": 3}
    node = {
        "id": "n9", "type": "condition", "yes_node_id": "ramo-sim", "no_node_id": "ramo-nao",
        "config": {"condition_type": "clicou_botao", **cfg_extra},
    }
    with (
        patch.object(engine, "get_supabase", MagicMock()),
        patch.object(engine, "_update") as upd,
        patch.object(engine, "_complete") as comp,
    ):
        engine._execute_condition(enrollment, node, {"phone": "5534988861441"}, AGORA)
    return upd, comp


def _ramo(upd) -> str:
    assert upd.call_count == 1, upd.call_args_list
    return upd.call_args[1]["current_node_id"]


CLIQUE_PARAR = {"ultima_resposta": {"texto": "Parar atendimento", "tipo": "button",
                                    "em": "2026-09-16T12:00:00+00:00"}}


class TestCondicaoClicouBotao:
    def test_5a_clique_certo_vai_para_o_ramo_sim(self):
        upd, comp = _condicao({"botao": "Parar atendimento"}, CLIQUE_PARAR)
        assert _ramo(upd) == "ramo-sim"
        comp.assert_not_called()

    @pytest.mark.parametrize("metadata", [
        {"ultima_resposta": {"texto": "Continuar", "tipo": "button"}},   # outro botao
        {"ultima_resposta": {"texto": "quanto custa?", "tipo": "text"}},  # texto livre
        {"ultima_resposta": {}},                                          # sem texto
        {},                                                               # sem resposta
        None,                                                             # sem metadata
    ])
    def test_5b_qualquer_outra_coisa_vai_para_o_ramo_nao(self, metadata):
        upd, _ = _condicao({"botao": "Parar atendimento"}, metadata)
        assert _ramo(upd) == "ramo-nao"

    def test_5c_condicao_sem_botao_configurado_responde_nao(self):
        """Condicao incompleta cai sempre no ramo NAO — caminho que o dono desenhou e
        ve no canvas. Nunca `yes` por vacuidade."""
        upd, _ = _condicao({}, CLIQUE_PARAR)
        assert _ramo(upd) == "ramo-nao"

    def test_5d_o_motor_nao_distingue_clique_de_digitacao(self):
        """Aceito de proposito (§11.5): quem digita "continuar" quer continuar."""
        upd, _ = _condicao(
            {"botao": "Continuar"},
            {"ultima_resposta": {"texto": "continuar", "tipo": "text"}},
        )
        assert _ramo(upd) == "ramo-sim"

    def test_5e_a_condicao_avanca_o_passo_como_as_outras(self):
        upd, _ = _condicao({"botao": "Parar atendimento"}, CLIQUE_PARAR)
        assert upd.call_args[1]["step_count"] == 4

    @pytest.mark.parametrize("metadata", [None, {}, {"ultima_resposta": {"texto": ""}}])
    def test_5f_vazio_contra_vazio_nao_e_SIM_por_vacuidade(self, metadata):
        """A armadilha: condicao sem `botao` configurado E matricula que ainda nao
        recebeu resposta nenhuma sao AMBOS a string vazia depois de normalizados. Sem o
        `bool(alvo)`, "" == "" manda toda matricula virgem para o ramo SIM — o ramo do
        clique — na primeira vez que o fluxo passar pela condicao."""
        upd, _ = _condicao({}, metadata)
        assert _ramo(upd) == "ramo-nao"

    @pytest.mark.parametrize("digitado", [
        "nao vou continuar agora",   # o alvo e SUBSTRING da resposta
        "continuar mandando preco",  # idem, no comeco
    ])
    def test_5g_igualdade_e_nunca_substring(self, digitado):
        """Mesma doutrina de `is_optout_reply`: substring transformaria "não vou
        continuar agora" no clique em "Continuar"."""
        upd, _ = _condicao(
            {"botao": "Continuar"}, {"ultima_resposta": {"texto": digitado, "tipo": "text"}},
        )
        assert _ramo(upd) == "ramo-nao"


# ─── 6. COMPATIBILIDADE COM O CHAMADOR ANTIGO ────────────────────────────────────


class TestChamadorAntigo:
    def test_6a_sem_texto_a_politica_continua_valendo(self):
        e = _roda(_no("send", on_reply="cancel"))
        e.cancel.assert_called_once_with("e1")
        e.pause.assert_not_called()

    def test_6b_sem_texto_nao_ha_escrita_de_metadata(self):
        """Compatibilidade nao pode custar um UPDATE por matricula a mais."""
        e = _roda(_no("wait"), gatilho=GATILHO_MUDO)
        e.update_enrollment.assert_not_called()
        e.pause.assert_called_once_with("e1")

    def test_6c_a_assinatura_aceita_um_argumento_so(self):
        import inspect
        params = inspect.signature(handle_campaign_reply).parameters
        assert params["texto"].default is None
        assert params["tipo"].default is None


# ─── 7. NORMALIZACAO DO ROTULO ───────────────────────────────────────────────────


class TestNormalizacao:
    @pytest.mark.parametrize("digitado", [
        "PARAR ATENDIMENTO", "Parar atendimento!", "parar  atendimento",
        "  Parar Atendimento  ", "Párar atendimento",
    ])
    def test_7a_variacoes_casam_a_mesma_chave(self, digitado):
        e = _roda(
            _no("send", on_reply_por_botao={"parar atendimento": "optout"}),
            texto=digitado, tipo="button",
        )
        e.update_lead.assert_called_once_with("lead-1", ai_enabled=False, opt_out=True)
        e.cancel.assert_called_once_with("e1")

    def test_7b_a_chave_declarada_tambem_e_normalizada(self):
        """O rotulo vem digitado por gente na tela — "Parar atendimento" tem de casar
        tanto quanto a forma ja normalizada."""
        e = _roda(
            _no("send", on_reply_por_botao={"Parar Atendimento!": "optout"}),
            texto="parar atendimento", tipo="button",
        )
        e.update_lead.assert_called_once_with("lead-1", ai_enabled=False, opt_out=True)

    def test_7c_igualdade_e_nunca_substring(self):
        """Mesma doutrina de `is_optout_reply`: "nao quero parar atendimento agora" NAO
        e o clique no botao."""
        e = _roda(
            _no("send", on_reply="pause", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="nao quero parar atendimento agora", tipo="text",
        )
        e.update_lead.assert_not_called()
        e.pause.assert_called_once_with("e1")

    def test_7d_normalize_reply_e_o_mesmo_de_sempre(self):
        assert _normalize_reply("PARAR ATENDIMENTO") == "parar atendimento"
        assert _normalize_reply("Parar atendimento!") == "parar atendimento"
        assert _normalize_reply("parar  atendimento") == "parar atendimento"
        assert _normalize_reply(None) == ""


# ─── 8. A RESPOSTA CHEGA ATE A MATRICULA ─────────────────────────────────────────


class TestUltimaRespostaNaMatricula:
    def test_8a_grava_texto_tipo_e_hora(self):
        e = _roda(_no("send", on_reply="pause"), texto="Continuar", tipo="button")
        assert e.update_enrollment.call_count == 1
        (mid,), kwargs = e.update_enrollment.call_args
        assert mid == "e1"
        registro = kwargs["metadata"]["ultima_resposta"]
        assert registro["texto"] == "Continuar"
        assert registro["tipo"] == "button"
        assert registro["em"]

    def test_8b_grava_em_TODAS_as_matriculas_ativas(self):
        """Um lead pode estar em duas esteiras ao mesmo tempo (`is_already_enrolled` e
        por CAMPANHA). Tratar so a primeira linha deixa a outra armada."""
        linhas = [
            _matricula(_no("send", on_reply="pause"), mid="e1"),
            _matricula(_no("wait"), mid="e2", campaign_id="camp2"),
        ]
        with _ambiente(linhas, gatilho=GATILHO_MUDO) as e:
            handle_campaign_reply("lead-1", "Continuar", "button")

        assert [c[0][0] for c in e.update_enrollment.call_args_list] == ["e1", "e2"]
        assert [c[0][0] for c in e.pause.call_args_list] == ["e1", "e2"]

    def test_8c_preserva_o_que_ja_havia_no_metadata(self):
        e = _roda(
            _no("send", on_reply="pause"), texto="Continuar", tipo="button",
            metadata={"deal_id": "d-9", "ultima_resposta": {"texto": "velho"}},
        )
        gravado = e.update_enrollment.call_args[1]["metadata"]
        assert gravado["deal_id"] == "d-9"
        assert gravado["ultima_resposta"]["texto"] == "Continuar"

    def test_8d_falha_na_escrita_nao_impede_a_politica(self):
        e = _roda(
            _no("send", on_reply_por_botao={"parar atendimento": "optout"}),
            texto="Parar atendimento", tipo="button",
            update_enrollment={"side_effect": RuntimeError("jsonb explodiu")},
        )
        e.update_lead.assert_called_once_with("lead-1", ai_enabled=False, opt_out=True)
        e.cancel.assert_called_once_with("e1")

    def test_8e_erro_numa_matricula_nao_desarma_as_outras(self):
        linhas = [
            _matricula(_no("send", on_reply="pause"), mid="e1"),
            _matricula(_no("send", on_reply="pause"), mid="e2"),
        ]
        with _ambiente(linhas) as e:
            e.pause.side_effect = [RuntimeError("boom"), None]
            handle_campaign_reply("lead-1", "Continuar", "button")
        assert [c[0][0] for c in e.pause.call_args_list] == ["e1", "e2"]


# ─── 9. A SEMANTICA LEGADA DE `cancel` NO NO CONTINUA DE PE ──────────────────────


class TestCancelamentoCondicional:
    def test_9a_send_text_com_on_reply_cancel_continua_pausando(self):
        """`system_cadence` grava `on_reply='cancel'` em nos `send_text` que HOJE
        pausam. Honra-lo agora mudaria campanha existente."""
        e = _roda(_no("send_text", on_reply="cancel"), texto="oi", tipo="text")
        e.pause.assert_called_once_with("e1")
        e.cancel.assert_not_called()

    def test_9b_gatilho_com_cancel_cancela_em_qualquer_tipo_de_no(self):
        e = _roda(_no("wait"), texto="oi", tipo="text", gatilho=GATILHO_CANCEL)
        e.cancel.assert_called_once_with("e1")

    def test_9c_cancel_declarado_num_BOTAO_vale_tambem_em_send_text(self):
        """`on_reply_por_botao` e campo NOVO: nenhuma campanha o tem, entao a restricao
        legada (que existe so para nao mudar dado antigo) nao se aplica a ele. Rotulo
        declarado a mao e intencao explicita."""
        e = _roda(
            _no("send_text", on_reply_por_botao={"parar": "cancel"}),
            texto="Parar", tipo="button",
        )
        e.cancel.assert_called_once_with("e1")
        e.pause.assert_not_called()


# ─── 10. O REGISTRO DECLARA AS TRES PECAS ────────────────────────────────────────


class TestRegistroDeNos:
    def test_10a_politica_resposta_ganhou_optout(self):
        from app.campaigns.node_registry import VALORES_FIXOS
        valores = {v for v, _rot in VALORES_FIXOS["politica_resposta"]}
        assert valores == {"pause", "cancel", "reset", "optout"}

    @pytest.mark.parametrize("tipo", ["send", "send_text"])
    def test_10b_on_reply_por_botao_existe_nos_dois_nos_de_envio(self, tipo):
        from app.campaigns.node_registry import REGISTRO
        campos = {c.chave: c for c in REGISTRO[(tipo, None)].campos}
        assert campos["on_reply_por_botao"].vocab == "mapa"
        # default None, nao {}: dict literal em dataclass frozen e compartilhado por
        # todos os nos, e gravar {} em todo no novo seria ruido no config.
        assert campos["on_reply_por_botao"].default is None

    def test_10c_clicou_botao_esta_na_paleta_com_o_campo_que_o_motor_le(self):
        from app.campaigns.node_registry import REGISTRO
        tipo = REGISTRO[("condition", "clicou_botao")]
        assert tipo.na_paleta
        assert {c.chave for c in tipo.campos} == {"botao"}
