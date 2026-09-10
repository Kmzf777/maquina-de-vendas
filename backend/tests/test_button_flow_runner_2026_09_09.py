"""Runner + gate do agente de recuperação — 2026-09-09.

O gate vive em `buffer/processor.py` entre o gate de reação isolada e o de canal
humano, e essa posição É o desenho: antes do `mode='human'` para o bot rodar no
número do João (a troca de número no handoff perde 26% dos leads — 131 de 500,
Diagnóstico 01/09 p.5), e antes de `VALERIA_ENABLED`/`lead.ai_enabled` para não
precisar ligar `ai_enabled` nos 1.208 leads do Bling. Um teste que só olhasse o
runner isolado não pegaria uma regressão de POSIÇÃO — por isso os dois testes de
gate dirigem `process_buffered_messages` de ponta a ponta.

Cobre:
  1. clique positivo entrega o produto e transborda (o turno que decide o projeto);
  2. texto livre classificado como SAIR grava `opt_out=true` (hoje há 52 opt-outs
     não honrados em produção — é essa dívida que não pode se repetir);
  3. autoresponder do próprio cliente (28% das "respostas") não gasta o nudge;
  4. clique com mais de 7 dias reinicia limpo em vez de retomar o nó (30% dos
     cliques chegam fora da janela; máximo observado 43 dias);
  5. o gate dispara em canal `mode='human'` e ignora perfil `llm`;
  6. classificador quebrado degrada para a regra de nudge, nunca estoura;
  7. `effects.aplicar` devolvendo False (opt-out não gravado) não avança o nó;
  8. o guarda "o João já mexeu no card" compara `stage_id` — a ÚNICA coluna de
     etapa que `get_open_deal` projeta (leads/service.py:1074). Comparando `stage`
     ele era código morto e o bot respondia por cima do vendedor;
  9. preço só do setor ATACADO: `products` é particionada por setor e o mesmo SKU
     existe em dois com preços diferentes;
 10. o caminho do bot roda DENTRO do `lead_run_lock`, com re-coalescing de texto
     livre — mas um CLIQUE nunca é descartado.
"""
import sys
import types
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.button_flow import effects, engine, flows, runner


AGORA = datetime.now(timezone.utc)


def _lead(**over) -> dict:
    base = {
        "id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
        "name": "Roner Silva", "ai_enabled": False, "human_control": False,
        "metadata": {"produto_top1": "Café Clássico 1kg"},
    }
    base.update(over)
    return base


def _conversa(estado=None, **over) -> dict:
    conv = {"id": "C1", "stage": "atacado", "agent_profile_id": "P-BOT",
            "flow_state": estado}
    conv.update(over)
    return conv


CANAL_JOAO = {"id": "a3a607b1", "mode": "human", "provider_config": {},
              "agent_profiles": {"id": "P-LLM", "kind": "llm"}}


def _estado(no=flows.NO_INTERESSE, *, nudged=False, idade_dias=0.0, **over) -> dict:
    estado = {
        "flow": flows.FLOW_ID,
        "node": no,
        "nudged": nudged,
        "trilha": flows.TRILHA_ESTOQUE,
        "campaign_id": "camp-1",
        "sent_at": "2026-09-01T17:00:00+00:00",
        "updated_at": (AGORA - timedelta(days=idade_dias)).isoformat(),
    }
    estado.update(over)
    return estado


def _provider() -> MagicMock:
    p = MagicMock()
    p.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.out"}]})
    p.send_interactive_buttons = AsyncMock(return_value={"messages": [{"id": "wamid.out"}]})
    p.send_contact = AsyncMock(return_value={"messages": [{"id": "wamid.card"}]})
    return p


PRODUTOS = [
    {"name": "Café Clássico 1kg", "price_formatted": "R$ 97,70", "sector": "atacado"},
    {"name": "Café Microlote 500g", "price_formatted": "R$ 61,90", "sector": "atacado"},
]

# Shape REAL de get_open_deal: `select("id, title, pipeline_id, stage_id, category")`
# (app/leads/service.py:1074). NÃO existe coluna `stage` na projeção — um teste que
# injetasse {"id": ..., "stage": ...} testaria um dict impossível em produção e
# deixaria o guarda passar como se estivesse vivo.
DEAL_ABERTO = {"id": "D1", "title": "Lead", "pipeline_id": "P",
               "stage_id": "S-QUER-REPOR", "category": None}

# Sentinela: por padrão a releitura do flow_state devolve None (conversa não
# encontrada) e o runner cai no estado que veio em memória — o caminho fail-soft.
_SEM_RELEITURA = object()


def _patch_runner(stack: ExitStack, *, produtos=None, deal=None, historico=None,
                  estado_no_banco=_SEM_RELEITURA):
    """Neutraliza todo o I/O do runner. Devolve o dict de mocks."""
    p = lambda name, **kw: stack.enter_context(patch.object(runner, name, **kw))
    mocks = {
        "get_open_deal": p("get_open_deal", new=MagicMock(return_value=deal)),
        "get_history": p("get_history", new=MagicMock(return_value=historico or [])),
        "save_message": p("save_message", new=MagicMock(return_value={})),
        "update_conversation": p("update_conversation", new=MagicMock(return_value={})),
        "get_conversation": p("get_conversation", new=MagicMock(
            return_value=None if estado_no_banco is _SEM_RELEITURA
            else {"id": "C1", "flow_state": estado_no_banco},
        )),
    }
    stack.enter_context(patch(
        "app.agent.catalog._fetch_active_products",
        MagicMock(return_value=PRODUTOS if produtos is None else produtos),
    ))
    return mocks


def _patch_crm(stack: ExitStack) -> dict:
    """Mocka só as folhas de escrita do CRM — `effects.aplicar` roda de verdade."""
    e = lambda name, **kw: stack.enter_context(
        patch.object(effects, name, new=MagicMock(**kw))
    )
    mocks = {
        "update_lead": e("update_lead"),
        "add_tags_to_lead": e("add_tags_to_lead"),
        "append_lead_observation": e("append_lead_observation"),
        "save_message": e("save_message"),
        "apply_optout_side_effects": e("apply_optout_side_effects"),
    }
    # Sem estes dois, o desfecho tenta mover o card e vai ao Supabase DE VERDADE
    # (`effects._mover_deal`): a suíte fica lenta e depende de rede. None = "lead sem
    # card aberto", que é o caminho fail-soft já coberto por effects.
    mocks["get_open_deal"] = e("get_open_deal", return_value=None)
    mocks["move_deal_to_stage_key"] = e("move_deal_to_stage_key", return_value=False)
    return mocks


def _assert_optout_gravado(crm) -> None:
    """`opt_out=true` + `ai_enabled=false` gravados no lead.

    Checa as duas colunas que importam em vez de casar a chamada inteira: as colunas
    de evidência (`opt_out_at`, `opt_out_evidence`, `opt_out_channel`) são da frente
    de `effects`/migration 20260909 e podem crescer sem que isto aqui seja o teste
    que quebra.
    """
    chamadas = [
        c for c in crm["update_lead"].call_args_list
        if c.args[:1] == ("L1",) and c.kwargs.get("opt_out") is True
    ]
    assert chamadas, f"opt_out não gravado: {crm['update_lead'].call_args_list}"
    assert chamadas[0].kwargs.get("ai_enabled") is False, chamadas[0]


def _injetar_modulo(stack: ExitStack, nome: str, **atributos) -> None:
    """Planta um módulo de outra frente em sys.modules (import lazy do runner)."""
    modulo = types.ModuleType(nome)
    for chave, valor in atributos.items():
        setattr(modulo, chave, valor)
    stack.enter_context(patch.dict(sys.modules, {nome: modulo}))


def _estado_gravado(mocks) -> dict:
    return mocks["update_conversation"].call_args.kwargs["flow_state"]


@pytest.fixture
def ligado(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.setenv("RECUPERACAO_CLASSIFIER_ENABLED", "on")
    monkeypatch.setenv("RECUPERACAO_JANELA_RETOMA_DIAS", "7")
    runner.limpar_cache_de_perfis()


# ── 1. O clique que decide o projeto ────────────────────────────────────────
@pytest.mark.asyncio
async def test_clique_positivo_entrega_produto_com_preco_e_transborda(ligado):
    provider = _provider()
    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        crm = _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "Preciso repor", "title": "Preciso repor"},
            wamid="wamid.in",
        )

    corpo = provider.send_text.await_args.args[1]
    assert "Café Clássico 1kg" in corpo and "R$ 97,70" in corpo, (
        "69,5% dos leads nunca viram preço nem foto; quem recebeu algo concreto chegou "
        f"ao vendedor em 73-75% contra 56,5%. Corpo enviado: {corpo!r}"
    )
    assert "?" not in corpo, "zero perguntas depois da entrega (autópsia dos 14 leads mortos)"
    provider.send_contact.assert_not_awaited(), "no número do próprio João o cartão é absurdo"

    crm["add_tags_to_lead"].assert_called_once_with("L1", [flows.TAG_QUENTE])
    marcadores = [c.args[2] for c in crm["save_message"].call_args_list]
    assert any("[encaminhar_humano]" in m for m in marcadores), (
        "é o marcador de sistema, e não metadata.handoff, que o dashboard conta"
    )
    assert _estado_gravado(mocks)["node"] == flows.NO_ENCERRADO


@pytest.mark.asyncio
async def test_clique_positivo_sem_sku_ativo_nao_cota_preco(ligado):
    """Produto fora dos 32 SKUs: reconhece pelo nome, NÃO inventa preço.

    Foi a improvisação de preço que perdeu as 500 unidades da Ritz (drip cotado a
    R$ 27,70 contra R$ 2,49/sachê reais).
    """
    provider = _provider()
    lead = _lead(metadata={"produto_top1": "Drip Coffee personalizado"})
    with ExitStack() as stack:
        _patch_runner(stack)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=lead, conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Retomar o pedido", message_type="button",
            metadata={"payload": "Retomar o pedido", "title": "Retomar o pedido"},
        )

    corpo = provider.send_text.await_args.args[1]
    assert "Drip Coffee personalizado" in corpo
    assert "R$" not in corpo


# A tabela `products` é particionada por setor: o MESMO nome de SKU existe em
# atacado e em consumo, com preços diferentes. `match_products` só olha `name`.
CATALOGO_DOIS_SETORES = [
    {"name": "Café Clássico 1kg", "price_formatted": "R$ 97,70", "sector": "Atacado"},
    {"name": "Café Clássico 1kg", "price_formatted": "R$ 149,90", "sector": "Consumo"},
    {"name": "Café Microlote 500g", "price_formatted": "R$ 61,90", "sector": "Atacado"},
]
CATALOGO_SO_VAREJO = [
    {"name": "Café Clássico 1kg", "price_formatted": "R$ 149,90", "sector": "Consumo"},
]


@pytest.mark.asyncio
async def test_preco_vem_do_setor_atacado_mesmo_com_o_sku_em_dois_setores(ligado):
    """Sem filtrar setor, o mesmo SKU casava 2x, len != 1, e a maior alavanca da
    spec virava silenciosamente o texto SEM preço."""
    provider = _provider()
    with ExitStack() as stack:
        _patch_runner(stack, produtos=CATALOGO_DOIS_SETORES)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )

    corpo = provider.send_text.await_args.args[1]
    assert "R$ 97,70" in corpo, corpo
    assert "149,90" not in corpo, "preço de varejo para cliente de atacado"


@pytest.mark.asyncio
async def test_sku_so_no_varejo_nao_e_cotado(ligado):
    """Casaria sozinho e o bot COTARIA varejo para uma coorte 97,2% B2B (ticket
    médio R$ 1.506,48). É o incidente Ritz por outra rota: SKU certo, setor errado.
    Na dúvida, entregar sem preço."""
    provider = _provider()
    with ExitStack() as stack:
        _patch_runner(stack, produtos=CATALOGO_SO_VAREJO)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )

    corpo = provider.send_text.await_args.args[1]
    assert "Café Clássico 1kg" in corpo, "o item continua sendo reconhecido pelo nome"
    assert "R$" not in corpo, corpo


# ── 2. Opt-out por texto livre ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_texto_de_saida_classificado_grava_optout(ligado):
    provider = _provider()
    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        crm = _patch_crm(stack)
        _injetar_modulo(stack, "app.button_flow.classifier",
                        classificar=AsyncMock(return_value=engine.CLASSE_SAIR))
        _injetar_modulo(stack, "app.button_flow.autoreply",
                        parece_autoresponder=lambda *_a, **_k: False)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="me tira dessa lista por favor",
            message_type="text", metadata=None,
        )

    _assert_optout_gravado(crm)
    crm["apply_optout_side_effects"].assert_called_once()
    assert _estado_gravado(mocks)["node"] == flows.NO_ENCERRADO
    assert provider.send_text.await_args.args[1] == flows.MSG_OPTOUT


# ── 3. Autoresponder ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_autoresponder_nao_responde_e_nao_gasta_o_nudge(ligado):
    """28% das 'respostas' da base são o robô do WhatsApp Business do próprio cliente."""
    provider = _provider()
    historico = [{"role": "assistant", "content": "olá",
                  "created_at": (AGORA - timedelta(seconds=40)).isoformat()}]
    with ExitStack() as stack:
        mocks = _patch_runner(stack, historico=historico)
        crm = _patch_crm(stack)
        _injetar_modulo(stack, "app.button_flow.autoreply",
                        parece_autoresponder=lambda *_a, **_k: True)
        classificar = AsyncMock(return_value=engine.CLASSE_QUENTE)
        _injetar_modulo(stack, "app.button_flow.classifier", classificar=classificar)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Olá! Agradecemos seu contato, responderemos em breve.",
            message_type="text", metadata=None,
        )

    provider.send_text.assert_not_awaited()
    provider.send_interactive_buttons.assert_not_awaited()
    classificar.assert_not_awaited(), "robô de saudação não vale um turno de LLM"
    mocks["update_conversation"].assert_not_called(), "o nó e o nudge ficam onde estavam"
    metadata = crm["update_lead"].call_args.kwargs["metadata"]
    assert metadata["auto_reply"]["origem"] == "button_flow"


@pytest.mark.asyncio
async def test_detector_real_de_autoresponder_esta_plugado(ligado):
    """Integração com a camada 1.5 de verdade — sem stub de módulo.

    Um teste que só usa o módulo injetado passaria mesmo se o runner chamasse a
    função com o kwarg errado; este quebra se o contrato
    `parece_autoresponder(texto, *, segundos_desde_nosso_envio=...)` mudar.
    """
    provider = _provider()
    historico = [{"role": "assistant", "content": "olá",
                  "created_at": (AGORA - timedelta(seconds=30)).isoformat()}]
    with ExitStack() as stack:
        mocks = _patch_runner(stack, historico=historico)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider,
            texto="Olá! Agradecemos seu contato. Responderemos em breve.",
            message_type="text", metadata=None,
        )

    provider.send_text.assert_not_awaited()
    provider.send_interactive_buttons.assert_not_awaited()
    mocks["update_conversation"].assert_not_called()


# ── 4. Idade do clique ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_clique_com_mais_de_7_dias_reinicia_limpo(ligado):
    """No nó de prazo, um clique de nível 1 seria IGNORADO. Depois do reinício, vale."""
    provider = _provider()
    estado = _estado(flows.NO_PRAZO, nudged=True, idade_dias=43)
    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(estado), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )

    assert "Café Clássico 1kg" in provider.send_text.await_args.args[1]
    gravado = _estado_gravado(mocks)
    assert gravado["node"] == flows.NO_ENCERRADO
    assert gravado["campaign_id"] == "camp-1", "o vínculo com a onda tem que sobreviver"
    assert gravado["sent_at"] == "2026-09-01T17:00:00+00:00"


@pytest.mark.asyncio
async def test_clique_de_prazo_muito_antigo_reoferece_os_botoes(ligado):
    """Reiniciado, um 'Em 60 dias' não significa mais nada — mas o lead tocou em algo
    nosso e não pode ficar sem resposta."""
    provider = _provider()
    estado = _estado(flows.NO_PRAZO, nudged=True, idade_dias=40)
    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(estado), channel=CANAL_JOAO,
            provider=provider, texto="Em 60 dias", message_type="button",
            metadata={"payload": "snooze60", "title": "Em 60 dias"},
        )

    titulos = [t for _id, t in provider.send_interactive_buttons.await_args.args[2]]
    assert titulos == list(flows.ROTULOS_TEMPLATE_POR_TRILHA[flows.TRILHA_ESTOQUE])
    gravado = _estado_gravado(mocks)
    assert gravado["node"] == flows.NO_INTERESSE and gravado["nudged"] is True


@pytest.mark.asyncio
async def test_clique_dentro_da_janela_retoma_o_no(ligado):
    """3 dias é tarde, mas não é reinício: o nó de prazo tem que ser retomado."""
    provider = _provider()
    estado = _estado(flows.NO_PRAZO, idade_dias=3)
    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(estado), channel=CANAL_JOAO,
            provider=provider, texto="Em 30 dias", message_type="button",
            metadata={"payload": "snooze30", "title": "Em 30 dias"},
        )

    assert _estado_gravado(mocks)["node"] == flows.NO_ENCERRADO
    assert "30 dias" in provider.send_text.await_args.args[1]


# ── 5. Guardas de não-rodar ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_human_control_tira_o_bot_de_cena_e_anota_uma_vez(ligado):
    provider = _provider()
    conversa = _conversa(_estado())
    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        crm = _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(human_control=True), conversation=conversa, channel=CANAL_JOAO,
            provider=provider, texto="oi", message_type="text", metadata=None,
        )
        provider.send_text.assert_not_awaited()
        assert crm["append_lead_observation"].call_count == 1
        assert _estado_gravado(mocks)["notificado_humano"] is True

        # 2ª mensagem na mesma conversa: log, sem encher o histórico de notas iguais.
        await runner.run_button_flow(
            lead=_lead(human_control=True), conversation=conversa, channel=CANAL_JOAO,
            provider=provider, texto="e aí", message_type="text", metadata=None,
        )
        assert crm["append_lead_observation"].call_count == 1


@pytest.mark.asyncio
async def test_deal_movido_de_etapa_tira_o_bot_de_cena(ligado):
    """Com o shape REAL de get_open_deal — que só traz `stage_id`.

    O guarda comparava `deal["stage"]`, coluna que a projeção de
    `app/leads/service.py:1074` nunca traz: o valor era sempre None e a comparação
    nunca disparava. Sobrava só `human_control`, e o bot respondia por cima do João
    na thread do número dele.
    """
    provider = _provider()
    estado = _estado(deal_stage_id="S-NOVO")
    with ExitStack() as stack:
        _patch_runner(stack, deal=DEAL_ABERTO)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(estado), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )

    provider.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_estado_grava_a_referencia_de_etapa_que_o_deal_realmente_tem(ligado):
    """Sem esta gravação o guarda acima fica sem referência — ou seja, morto.

    Com `deal["stage"]` (inexistente na projeção) o `if` nunca era verdadeiro e
    `flow_state` saía SEM chave de etapa nenhuma, turno após turno.
    """
    provider = _provider()
    with ExitStack() as stack:
        mocks = _patch_runner(stack, deal=DEAL_ABERTO)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )

    gravado = _estado_gravado(mocks)
    assert gravado["deal_stage_id"] == "S-QUER-REPOR", (
        f"sem referência de etapa o guarda do próximo turno é código morto: {gravado}"
    )


@pytest.mark.asyncio
async def test_estado_antigo_com_rotulo_de_etapa_nao_bloqueia_o_bot(ligado):
    """A chave velha `deal_stage` (rótulo humano) é ignorada, não comparada.

    Comparar "novo" contra um UUID de `stage_id` daria diferente SEMPRE e tiraria o
    bot de cena para sempre naquela conversa.
    """
    provider = _provider()
    estado = _estado(deal_stage="novo")
    with ExitStack() as stack:
        _patch_runner(stack, deal=DEAL_ABERTO)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(estado), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )

    provider.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_kill_switch_desligado_nao_roda_nada(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "off")
    provider = _provider()
    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )

    provider.send_text.assert_not_awaited()
    mocks["update_conversation"].assert_not_called()


# ── 6. Degradação do classificador ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_falha_do_classificador_cai_na_regra_de_nudge(ligado):
    """Sem camada 2 o fluxo continua funcionando como máquina de estados pura."""
    provider = _provider()

    async def _explode(*_a, **_k):
        raise RuntimeError("LLM fora do ar")

    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        _patch_crm(stack)
        _injetar_modulo(stack, "app.button_flow.classifier", classificar=_explode)
        _injetar_modulo(stack, "app.button_flow.autoreply",
                        parece_autoresponder=lambda *_a, **_k: False)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="vocês entregam em Alagoas?",
            message_type="text", metadata=None,
        )

    provider.send_interactive_buttons.assert_awaited_once()
    gravado = _estado_gravado(mocks)
    assert gravado["nudged"] is True and gravado["node"] == flows.NO_INTERESSE


@pytest.mark.asyncio
async def test_classificador_desligado_por_env_nao_e_chamado(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.setenv("RECUPERACAO_CLASSIFIER_ENABLED", "off")
    provider = _provider()
    classificar = AsyncMock(return_value=engine.CLASSE_SAIR)
    with ExitStack() as stack:
        _patch_runner(stack)
        crm = _patch_crm(stack)
        _injetar_modulo(stack, "app.button_flow.classifier", classificar=classificar)
        _injetar_modulo(stack, "app.button_flow.autoreply",
                        parece_autoresponder=lambda *_a, **_k: False)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="me tira da lista", message_type="text", metadata=None,
        )

    classificar.assert_not_awaited()
    for chamada in crm["update_lead"].call_args_list:
        assert chamada.kwargs.get("opt_out") is not True


# ── 7. Fail-CLOSED do opt-out ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_efeitos_bloqueados_nao_avancam_o_no_nem_enviam(ligado):
    """`aplicar` False = opt-out não gravado. Confirmar 'não te mando mais nada' aí
    faria o lead perder o motivo de tocar no botão de novo — e a gravação nunca
    seria retentada."""
    provider = _provider()
    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        stack.enter_context(patch.object(effects, "aplicar", MagicMock(return_value=False)))
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Parar mensagens", message_type="button",
            metadata={"payload": "optout", "title": "Parar mensagens"},
        )

    provider.send_text.assert_not_awaited()
    mocks["update_conversation"].assert_not_called()


# ── 8. O gate, dirigindo o pipeline inteiro ─────────────────────────────────
def _patch_pipeline(stack: ExitStack, *, channel: dict, conversation: dict,
                    texto: str, metadata: dict | None, message_type: str | None,
                    inbound_mais_novo: bool = False, buffer_pendente: bool = False,
                    lock_registro: MagicMock | None = None):
    """Mocks canônicos de process_buffered_messages (molde:
    test_transcricao_canal_humano_2026_09_08.py:85-121)."""
    from app.buffer import processor

    p = lambda name, *args, **kw: stack.enter_context(patch.object(processor, name, *args, **kw))

    p("get_or_create_lead", return_value=_lead())
    p("get_channel_by_id", return_value=channel)
    p("get_or_create_conversation", return_value=conversation)
    p("get_provider", return_value=MagicMock())
    p("update_conversation", MagicMock())
    p("get_supabase", MagicMock())
    p("run_with_retry", MagicMock(return_value=MagicMock(data={"unread_count": 0})))
    p("_wamid_already_processed", return_value=False)
    p("_is_recent_duplicate", return_value=False)
    p("save_message", MagicMock(return_value={"created_at": "2026-09-09T12:00:00Z"}))
    p("_update_last_msg", MagicMock())
    p("advance_deal_on_reply", MagicMock())
    p("_resolve_media", new=AsyncMock(return_value=(texto, None, message_type, None, metadata)))
    # Réguas do re-coalescing: sem mock elas bateriam no Supabase/Redis mockados e
    # devolveriam MagicMock (truthy), abortando todo turno em silêncio.
    p("_has_newer_inbound", MagicMock(return_value=inbound_mais_novo))
    p("_has_pending_buffered_inbound", new=AsyncMock(return_value=buffer_pendente))

    rodar = AsyncMock()
    dentro_do_lock = {"valor": False}

    @asynccontextmanager
    async def _lock_espiao(lead_id):
        if lock_registro is not None:
            lock_registro(lead_id)
        dentro_do_lock["valor"] = True
        try:
            yield True
        finally:
            dentro_do_lock["valor"] = False

    async def _registra_se_estava_travado(**kwargs):
        rodar.travado = dentro_do_lock["valor"]

    rodar.side_effect = _registra_se_estava_travado
    rodar.travado = None
    p("lead_run_lock", _lock_espiao)

    stack.enter_context(patch("app.broadcast.service.record_broadcast_reply", MagicMock()))
    stack.enter_context(patch("app.campaigns.worker.handle_campaign_reply", MagicMock()))
    stack.enter_context(patch("app.automation.triggers.fire_trigger", new=AsyncMock()))
    stack.enter_context(patch("app.leads.service.get_open_deal", MagicMock(return_value=None)))

    stack.enter_context(patch.object(processor, "run_button_flow", new=rodar))
    return rodar


@pytest.mark.asyncio
async def test_gate_dispara_em_canal_mode_human(ligado):
    """O bloqueio de `mode='human'` mata todo o resto do pipeline — o gate tem que
    estar ANTES dele, senão o bot simplesmente não existe no número do João."""
    from app.buffer import processor

    with ExitStack() as stack:
        rodar = _patch_pipeline(
            stack, channel=CANAL_JOAO, conversation=_conversa(_estado()),
            texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )
        stack.enter_context(patch.object(
            runner, "get_agent_profile",
            MagicMock(return_value={"id": "P-BOT", "kind": "button_flow"}),
        ))
        await processor.process_buffered_messages(
            "5534988861441", "Preciso repor", "a3a607b1", wamid="wamid.in",
        )

    rodar.assert_awaited_once()
    assert rodar.await_args.kwargs["metadata"]["payload"] == "repor"


@pytest.mark.asyncio
async def test_gate_nao_dispara_para_perfil_llm(ligado):
    from app.buffer import processor

    with ExitStack() as stack:
        rodar = _patch_pipeline(
            stack, channel=CANAL_JOAO, conversation=_conversa(_estado()),
            texto="oi", message_type="text", metadata=None,
        )
        stack.enter_context(patch.object(
            runner, "get_agent_profile",
            MagicMock(return_value={"id": "P-BOT", "kind": "llm"}),
        ))
        await processor.process_buffered_messages(
            "5534988861441", "oi", "a3a607b1", wamid="wamid.in",
        )

    rodar.assert_not_awaited()


def test_gate_e_fail_open_quando_o_perfil_nao_resolve(ligado):
    """Coluna `kind` ainda não migrada, banco fora, perfil apagado: segue o fluxo
    normal. Fail-closed aqui sequestraria conversas humanas por erro de leitura."""
    with patch.object(runner, "get_agent_profile", MagicMock(side_effect=RuntimeError)):
        assert runner.is_button_flow_conversation(_conversa(), CANAL_JOAO) is False


def test_gate_nao_toca_no_banco_com_o_kill_switch_desligado(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "off")
    runner.limpar_cache_de_perfis()
    perfil = MagicMock()
    with patch.object(runner, "get_agent_profile", perfil):
        assert runner.is_button_flow_conversation(_conversa(), CANAL_JOAO) is False
    perfil.assert_not_called()


def test_gate_usa_o_perfil_do_canal_quando_a_conversa_nao_tem(ligado):
    canal = dict(CANAL_JOAO, agent_profiles={"id": "P-BOT", "kind": "button_flow"})
    assert runner.is_button_flow_conversation(_conversa(agent_profile_id=None), canal) is True


# ── 9. Serialização por lead: o gate roda DENTRO do lead_run_lock ───────────
def _perfil_bot(stack: ExitStack) -> None:
    stack.enter_context(patch.object(
        runner, "get_agent_profile",
        MagicMock(return_value={"id": "P-BOT", "kind": "button_flow"}),
    ))


@pytest.mark.asyncio
async def test_gate_roda_o_bot_dentro_do_lead_run_lock(ligado):
    """O gate vive ANTES do lock do turno da IA (que só existe depois dos gates de
    canal humano / VALERIA_ENABLED / ai_enabled, os três fatais para este caminho).
    Então o caminho do bot adquire a MESMA trava por conta própria — senão dois
    flushes do mesmo lead rodam o fluxo em paralelo e duplicam efeito de CRM
    (a race do lead 5544991611703, app/buffer/lead_lock.py).
    """
    from app.buffer import processor

    registro = MagicMock()
    with ExitStack() as stack:
        rodar = _patch_pipeline(
            stack, channel=CANAL_JOAO, conversation=_conversa(_estado()),
            texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
            lock_registro=registro,
        )
        _perfil_bot(stack)
        await processor.process_buffered_messages(
            "5534988861441", "Preciso repor", "a3a607b1", wamid="wamid.in",
        )

    rodar.assert_awaited_once()
    registro.assert_called_once_with("L1")  # a trava é por LEAD, não por conversa
    assert rodar.travado is True, "o fluxo rodou FORA do lock — a trava seria decorativa"


@pytest.mark.asyncio
async def test_texto_livre_com_inbound_mais_novo_aborta_o_turno_stale(ligado):
    """Mesma disciplina do turno da IA: o worker posterior classifica o texto
    completo, então este turno não gasta um turno de LLM nem o nudge.
    """
    from app.buffer import processor

    with ExitStack() as stack:
        rodar = _patch_pipeline(
            stack, channel=CANAL_JOAO, conversation=_conversa(_estado()),
            texto="quero 20kg", message_type="text", metadata=None,
            inbound_mais_novo=True,
        )
        _perfil_bot(stack)
        await processor.process_buffered_messages(
            "5534988861441", "quero 20kg", "a3a607b1", wamid="wamid.in",
        )

    rodar.assert_not_awaited()


@pytest.mark.asyncio
async def test_texto_livre_com_irma_ainda_no_buffer_aborta_o_turno_stale(ligado):
    """`_has_newer_inbound` é cego para o que ainda está no buffer Redis (a irmã
    fica ~15s lá antes de ir ao banco) — as duas réguas valem aqui também.
    """
    from app.buffer import processor

    with ExitStack() as stack:
        rodar = _patch_pipeline(
            stack, channel=CANAL_JOAO, conversation=_conversa(_estado()),
            texto="quero 20kg", message_type="text", metadata=None,
            buffer_pendente=True,
        )
        _perfil_bot(stack)
        await processor.process_buffered_messages(
            "5534988861441", "quero 20kg", "a3a607b1", wamid="wamid.in",
        )

    rodar.assert_not_awaited()


@pytest.mark.asyncio
async def test_clique_nunca_e_descartado_pelo_re_coalescing(ligado):
    """A exceção deliberada: o turno da IA pode abortar porque o worker posterior
    relê o histórico e responde tudo; aqui não há esse resgate — o worker posterior
    traz o texto DELE e a identidade do botão morre com o turno abortado. O clique
    é o sinal que o projeto existe para capturar (35,7% viraram venda).
    """
    from app.buffer import processor

    with ExitStack() as stack:
        rodar = _patch_pipeline(
            stack, channel=CANAL_JOAO, conversation=_conversa(_estado()),
            texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
            inbound_mais_novo=True, buffer_pendente=True,
        )
        _perfil_bot(stack)
        await processor.process_buffered_messages(
            "5534988861441", "Preciso repor", "a3a607b1", wamid="wamid.in",
        )

    rodar.assert_awaited_once()
    assert rodar.await_args.kwargs["metadata"]["payload"] == "repor"


@pytest.mark.asyncio
async def test_clique_com_midia_na_mesma_janela_tambem_nao_e_descartado(ligado):
    """O clique sobrevive só no metadata quando a mídia toma o slot de
    `message_type` (_resolve_media). A regra de "é clique" tem que ser a mesma do
    runner — por isso ela é UMA função, `e_clique_de_botao`.
    """
    from app.buffer import processor

    with ExitStack() as stack:
        rodar = _patch_pipeline(
            stack, channel=CANAL_JOAO, conversation=_conversa(_estado()),
            texto="Preciso repor", message_type="image",
            metadata={"payload": "repor", "title": "Preciso repor"},
            inbound_mais_novo=True,
        )
        _perfil_bot(stack)
        await processor.process_buffered_messages(
            "5534988861441", "Preciso repor", "a3a607b1", wamid="wamid.in",
        )

    rodar.assert_awaited_once()


# ── 10. Releitura do estado dentro do lock (o que torna a trava útil) ───────
@pytest.mark.asyncio
async def test_segundo_toque_serializado_nao_duplica_efeito_de_crm(ligado):
    """Duplo toque no mesmo botão: o 2º worker carrega um `conversation` lido ANTES
    de entrar na fila do lock. Com o estado velho na mão ele reexecutaria a MESMA
    transição — 2º handoff, 2ª tag, 2ª mensagem. Relendo o flow_state dentro do
    lock, o motor vê `encerrado` e ignora.
    """
    provider = _provider()
    estado_em_memoria = _estado()  # o que o worker leu ANTES do lock
    estado_no_banco = _estado(flows.NO_ENCERRADO)  # o que o 1º turno já gravou
    with ExitStack() as stack:
        mocks = _patch_runner(stack, estado_no_banco=estado_no_banco)
        crm = _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(estado_em_memoria), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )

    provider.send_text.assert_not_awaited()
    crm["add_tags_to_lead"].assert_not_called()
    mocks["update_conversation"].assert_not_called()


@pytest.mark.asyncio
async def test_optout_ainda_vence_com_o_estado_ja_encerrado_no_banco(ligado):
    """A releitura não pode virar um jeito novo de perder opt-out: 52 pessoas em
    produção clicaram "Nao tenho interesse" e seguem com opt_out=false.
    """
    provider = _provider()
    with ExitStack() as stack:
        _patch_runner(stack, estado_no_banco=_estado(flows.NO_ENCERRADO))
        crm = _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Parar mensagens", message_type="button",
            metadata={"payload": "optout", "title": "Parar mensagens"},
        )

    _assert_optout_gravado(crm)
    assert provider.send_text.await_args.args[1] == flows.MSG_OPTOUT


@pytest.mark.asyncio
async def test_releitura_indisponivel_cai_no_estado_em_memoria(ligado):
    """Fail-soft: banco fora não pode custar o turno — um estado levemente velho é
    melhor que um lead sem resposta.
    """
    provider = _provider()
    with ExitStack() as stack:
        mocks = _patch_runner(stack)
        stack.enter_context(patch.object(
            runner, "get_conversation", MagicMock(side_effect=RuntimeError("db fora")),
        ))
        _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )

    assert "Café Clássico 1kg" in provider.send_text.await_args.args[1]
    assert _estado_gravado(mocks)["node"] == flows.NO_ENCERRADO


# ── 11. Evidência do opt-out atravessa o seam runner → effects ──────────────
#
# `effects.aplicar` ganhou o parâmetro `evidencia` numa frente e o runner é o
# chamador de OUTRA. Enquanto o runner não o passava, todo opt-out real nascia com
# `opt_out_channel=NULL` e `opt_out_evidence` sem origem — o "booleano nu" que a
# migration 20260909 declara indefensável na ANPD — e nenhum teste via: os de
# `effects` chamam `aplicar` direto COM evidência, e os do runner só olhavam
# `opt_out`/`ai_enabled`. Estes dois testes são o seam.
def _evidencia_gravada(crm) -> dict:
    chamadas = [
        c for c in crm["update_lead"].call_args_list
        if c.args[:1] == ("L1",) and c.kwargs.get("opt_out") is True
    ]
    assert chamadas, f"opt_out não gravado: {crm['update_lead'].call_args_list}"
    return chamadas[0].kwargs


@pytest.mark.asyncio
async def test_optout_por_clique_grava_a_prova_do_botao(ligado):
    provider = _provider()
    with ExitStack() as stack:
        _patch_runner(stack)
        crm = _patch_crm(stack)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="Parar mensagens", message_type="button",
            metadata={"payload": "optout", "title": "Parar mensagens"},
            wamid="wamid.HBgM01",
        )

    campos = _evidencia_gravada(crm)
    assert campos["opt_out_channel"] == effects.CANAL_BOTAO
    assert campos["opt_out_at"]
    prova = campos["opt_out_evidence"]
    assert prova["origem"] == "clique"
    assert prova["button_payload"] == "optout"
    assert prova["button_label"] == "Parar mensagens"
    # A única parte da prova que a Meta confirma de forma independente.
    assert prova["wamid"] == "wamid.HBgM01"
    assert prova["conversation_id"] == "C1"


@pytest.mark.asyncio
async def test_optout_por_texto_classificado_guarda_a_frase_do_lead(ligado):
    """A frase é a prova, e ela só existe no parâmetro `texto`: quando a camada 2
    classifica, o runner troca o `engine.Texto` por um `engine.Classificado`, que
    carrega apenas a classe.
    """
    provider = _provider()
    with ExitStack() as stack:
        _patch_runner(stack)
        crm = _patch_crm(stack)
        _injetar_modulo(stack, "app.button_flow.classifier",
                        classificar=AsyncMock(return_value=engine.CLASSE_SAIR))
        _injetar_modulo(stack, "app.button_flow.autoreply",
                        parece_autoresponder=lambda *_a, **_k: False)
        await runner.run_button_flow(
            lead=_lead(), conversation=_conversa(_estado()), channel=CANAL_JOAO,
            provider=provider, texto="me tira dessa lista por favor",
            message_type="text", metadata=None, wamid="wamid.HBgM02",
        )

    campos = _evidencia_gravada(crm)
    assert campos["opt_out_channel"] == effects.CANAL_TEXTO
    prova = campos["opt_out_evidence"]
    assert prova["origem"] == "classe"
    assert prova["classe"] == engine.CLASSE_SAIR
    assert prova["texto"] == "me tira dessa lista por favor"
    assert prova["wamid"] == "wamid.HBgM02"


def test_evidencia_de_texto_longo_e_truncada():
    """O jsonb é aberto de propósito, mas a prova é a frase — não o buffer inteiro."""
    prova = runner._evidencia_do_turno(
        engine.Classificado(engine.CLASSE_SAIR), "x" * 3000, "wamid.1")
    assert len(prova["texto"]) == runner._MAX_TEXTO_EVIDENCIA
    assert prova["origem"] == "classe"
