"""Camada 2 do bot de botões: o classificador estreito (6 classes, zero prosa).

Ele existe porque 60% dos respondentes DIGITAM em vez de clicar (broadcast de
29/07: 24 cliques contra 36 textos livres), e porque hoje há 52 pessoas em produção
que pediram para sair e seguem com `opt_out = false`.

O que estes testes travam, em ordem de custo do erro:
  1. nenhuma falha do LLM escapa — timeout, quota, JSON quebrado e classe inventada
     têm que virar RUIDO, a única classe sem efeito destrutivo;
  2. as regras de desempate que custaram dinheiro real (Rafael Monteiro, R$ 2.490;
     Verde Vale, R$ 1.178,90) não dependem só de o modelo ter lido o prompt — as que
     protegem a única classe irreversível (SAIR) são determinísticas;
  3. o prompt continua estreito: sem persona, sem catálogo, com os exemplos verbatim
     do dataset;
  4. os cinco pedidos EXPLÍCITOS de saída do dossiê continuam virando opt-out — a
     rede de proteção do item 2 não pode engolir um pedido legítimo (risco #1, LGPD).

A API do Gemini NUNCA é chamada aqui: `app.button_flow.classifier.generate` é o
único ponto de saída e é sempre mockado.
"""
import asyncio
import json

import pytest
from unittest.mock import AsyncMock, patch

from app.button_flow import classifier, engine
from tests.gemini_fakes import fake_text


# ── Infra dos testes ────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _sem_supabase(monkeypatch):
    """Corta os dois caminhos que tocariam o banco: budget guard e token_usage.

    Os dois entram por import tardio dentro da função, então o patch no atributo do
    módulo é suficiente — e é justamente o que garante que nenhum teste desta suíte
    faça I/O de rede por causa da contabilidade.
    """
    monkeypatch.setattr("app.agent.budget_guard.is_exceeded", lambda: False)
    registradas: list[dict] = []
    monkeypatch.setattr(
        "app.agent.token_tracker.track_token_usage",
        lambda **kwargs: registradas.append(kwargs),
    )
    return registradas


def _resposta(classe: str):
    """Saída canônica do modelo em json_mode: {"classe": "..."}."""
    return fake_text(json.dumps({"classe": classe}))


def _patch_generate(*resultados):
    return patch(
        "app.button_flow.classifier.generate",
        new=AsyncMock(side_effect=list(resultados)),
    )


# ── As 6 classes, com os gatilhos REAIS do dossiê §6.5 ──────────────────────
_GATILHOS = [
    # SAIR — os cinco pedidos explícitos de saída registrados na base.
    ("para de me mandar isso", engine.CLASSE_SAIR),
    ("descadastrar meu numero", engine.CLASSE_SAIR),
    ("me tira da lista", engine.CLASSE_SAIR),
    ("nao quero mais receber", engine.CLASSE_SAIR),
    ("STOP PROMOTIONS", engine.CLASSE_SAIR),
    # QUENTE — do "quero voltar" ao pedido já colado com CNPJ.
    ("Quero voltar a parceria", engine.CLASSE_QUENTE),
    ("Me manda a tabela", engine.CLASSE_QUENTE),
    ("quanto ta hoje o classico 2kg?", engine.CLASSE_QUENTE),
    (
        "Pedido divina terra Plaza / CNPJ 15-737-471-0002-35 / "
        "Cafe canastra suave 250gr 10 uni",
        engine.CLASSE_QUENTE,
    ),
    # ADIAR — o slot mais valioso do menu: não é não, é "agora não".
    ("por essa semana ainda esta ok o estoque", engine.CLASSE_ADIAR),
    ("acabamos de receber reposicao", engine.CLASSE_ADIAR),
    ("mais pra frente", engine.CLASSE_ADIAR),
    ("vou ver e te falo", engine.CLASSE_ADIAR),
    # ENGANO — contesta o pretexto do template; aborta o script comercial.
    ("nao fiz nenhum pedido", engine.CLASSE_ENGANO),
    ("eu nunca comprei esse cafe", engine.CLASSE_ENGANO),
    ("numero errado amigo", engine.CLASSE_ENGANO),
    ("esse celular nao e mais da magda", engine.CLASSE_ENGANO),
    # PERGUNTA — dúvida operacional, vai para o João.
    ("qual o pedido minimo?", engine.CLASSE_PERGUNTA),
    ("voces entregam em Alagoas?", engine.CLASSE_PERGUNTA),
    # RUIDO — saudação solta e mídia sem contexto.
    ("bom dia", engine.CLASSE_RUIDO),
    ("audio", engine.CLASSE_RUIDO),
]


_GATILHOS_SAIR = [t for t, c in _GATILHOS if c == engine.CLASSE_SAIR]
_GATILHOS_VIA_LLM = [(t, c) for t, c in _GATILHOS if c != engine.CLASSE_SAIR]


@pytest.mark.parametrize("texto,classe", _GATILHOS_VIA_LLM)
async def test_gatilhos_reais_atravessam_ate_a_classe(texto, classe):
    """Cada gatilho do dossiê chega ao motor como a classe correspondente.

    Cobre o caminho inteiro: montagem, json_mode, parse e rede de proteção. Os
    gatilhos de SAIR saíram desta lista porque não chegam mais ao modelo — estão em
    `test_pedido_explicito_de_saida_nao_depende_do_llm`.
    """
    with _patch_generate(_resposta(classe)) as m_gen:
        assert await classifier.classificar(texto) == classe
    assert m_gen.await_count == 1


async def test_toda_classe_do_motor_e_alcancavel():
    """Nenhuma das 6 classes do engine fica órfã — a matriz do motor cobre todas."""
    for classe in engine.CLASSES:
        with _patch_generate(_resposta(classe)):
            assert await classifier.classificar("texto qualquer do lead") == classe


# ── Desempates que custaram dinheiro real ───────────────────────────────────
@pytest.mark.parametrize("texto", [
    # Rafael Monteiro: recebeu opt-out e comprou R$ 2.490 dez dias depois.
    "Eu ja sou cliente de voces. Faco meus pedidos com o Joao",
    # Verde Vale: recebeu opt-out e comprou R$ 1.178,90.
    "acabamos de receber reposicao",
    "obrigado",
    "Obrigada, acabei de repor",
    "ja compro com o Joao",
])
async def test_sair_sem_pedido_de_parada_vira_adiar(texto):
    """Duvida entre SAIR e ADIAR -> ADIAR, mesmo que o modelo tenha dito SAIR.

    O prompt carrega a regra, mas opt-out é o único efeito IRREVERSÍVEL do fluxo:
    ele não pode depender de o modelo ter obedecido. Rebaixar não fecha porta —
    o nó de prazo segue oferecendo "Parar mensagens" a um toque.
    """
    with _patch_generate(_resposta(engine.CLASSE_SAIR)):
        assert await classifier.classificar(texto) == engine.CLASSE_ADIAR


# Fórmulas educadas de descadastro. NENHUMA delas estava na lista verbatim de ~19
# substrings do detector antigo, e todas carregam "obrigad" — a marca NUNCA-SAIR que
# casa em qualquer posição. Resultado do bug: `classificar()` devolvia ADIAR e o bot
# respondia "Beleza! Quando faz sentido eu te chamar de novo?" com botões de 30/60/90
# dias para quem tinha acabado de pedir para parar. São o repro literal do defeito.
_CORTESIA_MAIS_PEDIDO_DE_PARADA = [
    "Obrigado, mas pode parar de enviar essas mensagens",
    "Obrigada! Nao tenho interesse, pode me excluir do cadastro",
    "Obrigado, ja compro com o Joao. Pode me remover dessas mensagens",
    "Obrigado pelo contato, mas prefiro nao receber mais nada de voces",
    "Bom dia, obrigado. Favor cancelar meu cadastro de mensagens",
    "Obrigado. Nao autorizo mais o envio de mensagens publicitarias",
    "ja sou cliente, pode parar com essas mensagens",
    # As três que a lista verbatim já cobria — continuam cobertas.
    "obrigado, mas me tira da lista",
    "ja sou cliente sim, mas para de me mandar isso por favor",
    "Obrigado. Nao quero mais receber essas mensagens",
]


@pytest.mark.parametrize("texto", _CORTESIA_MAIS_PEDIDO_DE_PARADA)
async def test_pedido_explicito_de_saida_sobrevive_a_cortesia(texto):
    """A rede de proteção não pode virar filtro de opt-out.

    "obrigado" e "ja sou cliente" MODULAM o julgamento; não o invertem. Havendo verbo
    de parada dirigido ao envio, SAIR vence — foi por não honrar pedidos assim que 52
    leads seguem elegíveis a disparo em produção (risco #1 da spec, LGPD).
    """
    with _patch_generate(_resposta(engine.CLASSE_SAIR)):
        assert await classifier.classificar(texto) == engine.CLASSE_SAIR


@pytest.mark.parametrize("texto", _CORTESIA_MAIS_PEDIDO_DE_PARADA)
def test_cortesia_nao_inverte_pedido_de_parada_na_rede_de_protecao(texto):
    """O mesmo repro no nível da unidade: `_proteger_saida` não rebaixa mais.

    Antes, cada um destes textos passava por `_NUNCA_E_SAIR` (marca "obrigad" ou
    "ja sou cliente") sem casar com nenhuma das ~19 substrings quase verbatim, e saía
    como ADIAR.
    """
    assert classifier.pediu_para_parar(texto) is True
    assert classifier._proteger_saida(engine.CLASSE_SAIR, texto) == engine.CLASSE_SAIR


@pytest.mark.parametrize("texto", _GATILHOS_SAIR + _CORTESIA_MAIS_PEDIDO_DE_PARADA)
async def test_pedido_explicito_de_saida_nao_depende_do_llm(texto, monkeypatch):
    """Fail-CLOSED: com o kill-switch diário armado o opt-out ainda é honrado.

    Só existia curto-circuito determinístico CONTRA o opt-out. Com o teto de budget
    estourado (FinOps P0, 12/07) ou o Gemini fora, `classificar("me tira da lista")`
    devolvia RUIDO e o lead seguia elegível ao próximo disparo — durante um dia
    inteiro de kill-switch isso valeria para 100% dos turnos de texto livre.

    O mock devolve QUENTE de propósito: se a classe sair SAIR, veio do detector.
    """
    monkeypatch.setattr("app.agent.budget_guard.is_exceeded", lambda: True)
    with _patch_generate(_resposta(engine.CLASSE_QUENTE)) as m_gen:
        assert await classifier.classificar(texto) == engine.CLASSE_SAIR
    assert m_gen.await_count == 0, "pedido de parada não gasta token nem depende de infra"


@pytest.mark.parametrize("texto", ["me tira da lista", "nao quero mais receber"])
async def test_provedor_fora_ainda_honra_o_optout(texto):
    """Provedor fora do ar não pode transformar pedido de saída em RUIDO."""
    with _patch_generate(RuntimeError("503 UNAVAILABLE")) as m_gen:
        assert await classifier.classificar(texto) == engine.CLASSE_SAIR
    assert m_gen.await_count == 0


@pytest.mark.parametrize("texto", [
    # Os dois casos que pagaram a rede de proteção: continuam ADIAR.
    "Eu ja sou cliente de voces. Faco meus pedidos com o Joao",
    "acabamos de receber reposicao",
    # ADIAR travestido de negativa de envio: "ainda não", não "nunca mais".
    "nao me manda o pedido ainda, semana que vem eu vejo",
    # Reclamação de entrega, não descadastro.
    "nao recebi o pedido ainda",
    "nao vou receber o pedido essa semana",
    # "sair" e "para" como preposição/verbo de outra coisa.
    "vou sair agora, me manda a lista depois",
    "me manda para o meu whatsapp a lista de precos",
    # "cancelar" mirando o pedido, não o envio.
    "quero cancelar meu pedido",
    "me tira uma duvida do envio",
])
def test_detector_nao_inventa_pedido_de_parada(texto):
    """O detector roda ANTES do LLM: um falso positivo aqui é opt-out irreversível.

    Por isso "para" só vale como verbo colado a "de"/"com", a recusa de envio exige
    qualificador de definitividade ("mais"/"nada") e só o infinitivo "receber" conta.
    """
    assert classifier.pediu_para_parar(texto) is False


@pytest.mark.parametrize("texto", ["Não", "nao", "não.", "NAO!", " n ", "nn"])
async def test_nao_isolado_e_ruido_sem_gastar_token(texto):
    """"Nao" sozinho quase nunca é recusa nesta base.

    Dos ~11 leads que clicaram "Nao" no template outbound, 4 viraram lead válido: o
    "Nao" respondia à pergunta do template ("falo com {{1}}?") e queria dizer "o nome
    do cadastro está errado" — a importação do Bling gravou razão social e handles em
    `leads.name`. RUIDO reoferece os botões, que é a pergunta certa; SAIR
    descadastraria justamente quem está engajado. Decidido sem LLM: é a regra que
    menos pode depender de modelo.
    """
    with _patch_generate(_resposta(engine.CLASSE_SAIR)) as m_gen:
        assert await classifier.classificar(texto) == engine.CLASSE_RUIDO
    assert m_gen.await_count == 0, "negativa isolada não deve custar uma chamada"


@pytest.mark.parametrize("texto", ["", "   ", "\n", "👍", "🙏🏼🙏🏼", "..."])
async def test_texto_sem_conteudo_e_ruido_sem_chamar_llm(texto):
    """Áudio não transcrito, figurinha e emoji solto são RUIDO por definição.

    Sem caractere alfanumérico não há o que classificar — e um turno de mídia sem
    legenda é comum o bastante para não valer uma chamada cada.
    """
    with _patch_generate(_resposta(engine.CLASSE_QUENTE)) as m_gen:
        assert await classifier.classificar(texto) == engine.CLASSE_RUIDO
    assert m_gen.await_count == 0


# ── Falha do LLM: sempre RUIDO, nunca exceção ───────────────────────────────
@pytest.mark.parametrize("resultado,esperado", [
    # prosa sem JSON e sem nome de classe: nada aproveitável.
    (fake_text("desculpe, nao consigo classificar isso"), engine.CLASSE_RUIDO),
    (fake_text(None), engine.CLASSE_RUIDO),                      # resposta vazia
    (fake_text(""), engine.CLASSE_RUIDO),
    # JSON válido com classe inventada: o campo é a resposta e ela não existe.
    (fake_text('{"classe": "COMPRAR"}'), engine.CLASSE_RUIDO),
    # JSON válido: o campo `classe` manda, o ruído ao lado não vota.
    (fake_text('{"classe": "SAIR", "classe2": "ADIAR"}'), engine.CLASSE_SAIR),
    # JSON quebrado e com DUAS classes soltas: modelo hesitando em voz alta.
    (fake_text("{classe: SAIR, ADIAR}"), engine.CLASSE_RUIDO),
    # JSON quebrado com UMA classe: aqui a tolerância se paga.
    (fake_text('```json\n{"classe": "QUENTE"\n'), engine.CLASSE_QUENTE),
])
async def test_saida_estranha_do_modelo_vira_a_classe_certa(resultado, esperado):
    """Cada saída torta tem UM destino definido — o assert é o valor, não o tipo.

    A versão anterior deste teste só afirmava `classe in engine.CLASSES`, o que é
    verdade em todo caminho do módulo: ele passava mesmo se o parse escolhesse a
    classe errada. O JSON truncado com uma classe é o único caso em que o parse de
    emergência vale (lição do incidente de 08/07, memory_manager._extract_json_object).
    """
    with _patch_generate(resultado):
        assert await classifier.classificar("mensagem qualquer do lead") == esperado


@pytest.mark.parametrize("bruto", [
    # O caso que motivou o conserto: campo inválido + a palavra SAIR na justificativa.
    '{"classe": "TALVEZ", "justificativa": "o cliente pediu para SAIR mais tarde"}',
    '{"classe": "INDEFINIDO", "nota": "parece ADIAR"}',
    # Objeto no formato certo, mas sem o campo: também não autoriza varrer a prosa.
    '{"resposta": "acho que o cliente quer SAIR"}',
])
def test_json_valido_com_campo_invalido_nao_cai_no_fallback_por_substring(bruto):
    """JSON que parseou é a palavra final do modelo — prosa em volta não vota.

    O fallback por substring varre o texto CRU (chaves, justificativa, prosa) e uma
    única ocorrência da palavra decidia a classe: `{"classe":"TALVEZ",
    "justificativa":"o cliente pediu para SAIR mais tarde"}` devolvia SAIR, ou seja,
    um opt-out irreversível decidido por uma palavra solta dentro de um comentário
    do modelo. Só varre quem nem parseou.
    """
    assert classifier._extrair_classe(bruto) is None


async def test_justificativa_com_a_palavra_sair_nao_descadastra_ninguem():
    """O repro do parágrafo acima, ponta a ponta: tem que virar RUIDO."""
    bruto = '{"classe": "TALVEZ", "justificativa": "o cliente pediu para SAIR mais tarde"}'
    with _patch_generate(fake_text(bruto)):
        assert await classifier.classificar("vou ver e te falo") == engine.CLASSE_RUIDO


async def test_json_truncado_com_uma_classe_ainda_e_aproveitado():
    with _patch_generate(fake_text('```json\n{"classe": "QUENTE"')):
        assert await classifier.classificar("me ve 10 pacotes") == engine.CLASSE_QUENTE


@pytest.mark.parametrize("exc", [
    asyncio.TimeoutError(),
    TimeoutError(),
    RuntimeError("429 RESOURCE_EXHAUSTED: quota estourada"),
    ValueError("GEMINI_API_KEY is not configured"),
    Exception("503 UNAVAILABLE"),
])
async def test_excecao_do_provedor_vira_ruido(exc):
    """Timeout, quota, chave ausente e 5xx: o lead não pode ficar sem resposta.

    RUIDO cai na regra de nudge do motor — reoferece os botões uma vez e, na segunda,
    silencia e entrega ao João. Nenhum caminho aqui pode levantar: o turno inteiro
    do bot morreria com ele.
    """
    with _patch_generate(exc):
        assert await classifier.classificar("acho que vou querer") == engine.CLASSE_RUIDO


async def test_timeout_real_do_wait_for(monkeypatch):
    """O teto de espera é de verdade, não só um except bonito.

    `gemini_client.generate` não tem knob de timeout e o lead está esperando dentro
    da janela de 24h — pendurar o worker do buffer custa a thread inteira.
    """
    monkeypatch.setenv("RECUPERACAO_CLASSIFIER_TIMEOUT_S", "0.01")

    async def _pendurado(*_a, **_k):
        await asyncio.sleep(5)

    with patch("app.button_flow.classifier.generate", new=_pendurado):
        assert await classifier.classificar("oi, tudo bem?") == engine.CLASSE_RUIDO


async def test_budget_estourado_nao_chama_o_provedor(monkeypatch):
    """Kill-switch diário (FinOps P0, 12/07): com o teto estourado não se chama nada.

    O caminho seguro já existe — RUIDO nudgeia com texto de flows.py, a custo zero.
    """
    monkeypatch.setattr("app.agent.budget_guard.is_exceeded", lambda: True)
    with _patch_generate(_resposta(engine.CLASSE_QUENTE)) as m_gen:
        assert await classifier.classificar("me manda a tabela") == engine.CLASSE_RUIDO
    assert m_gen.await_count == 0


async def test_budget_guard_quebrado_nao_derruba_a_classificacao(monkeypatch):
    """Medidor com defeito é fail-open: nunca derrubamos o atendimento por causa dele."""
    def _explode():
        raise RuntimeError("supabase fora do ar")

    monkeypatch.setattr("app.agent.budget_guard.is_exceeded", _explode)
    with _patch_generate(_resposta(engine.CLASSE_QUENTE)):
        assert await classifier.classificar("me manda a tabela") == engine.CLASSE_QUENTE


# ── Forma da chamada: estreita, barata e determinística ─────────────────────
async def test_chamada_e_estreita_e_deterministica():
    """json_mode de verdade, thinking desligado, temperatura 0 e teto de saída curto.

    `json_mode=True` é a correção real do incidente de 08/07 (a fachada OpenAI-shape
    engolia `response_format` em silêncio). `thinking_off` importa no dinheiro: os
    thoughts são cobrados como saída e não há o que pensar para devolver uma palavra.
    """
    with _patch_generate(_resposta(engine.CLASSE_ADIAR)) as m_gen:
        await classifier.classificar("vou ver e te falo", historico_curto="Como esta o estoque?")
    args, kwargs = m_gen.await_args
    assert args[0] == classifier.modelo()
    assert kwargs["json_mode"] is True
    assert kwargs["thinking_off"] is True
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_output_tokens"] <= 64
    assert kwargs["system_instruction"] == classifier.INSTRUCAO_SISTEMA
    assert "tools" not in kwargs, "classificador não usa tool-calling"
    enviado = kwargs["contents"][0].parts[0].text
    assert "vou ver e te falo" in enviado
    assert "Como esta o estoque?" in enviado


async def test_entrada_longa_e_truncada():
    """Quem cola um catálogo não pode estourar o orçamento de ~300 tokens.

    A classe se decide nas primeiras linhas; o resto é peso morto no prompt.
    """
    with _patch_generate(_resposta(engine.CLASSE_QUENTE)) as m_gen:
        await classifier.classificar("x" * 5000, historico_curto="h" * 5000)
    enviado = m_gen.await_args.kwargs["contents"][0].parts[0].text
    assert len(enviado) < 1200
    assert len(enviado.split("Resposta do cliente: ", 1)[1]) == 600
    assert enviado.count("h") == 300


async def test_modelo_e_timeout_vem_do_env(monkeypatch):
    """Env por os.getenv, nunca campo no Settings (config.py:65-69 tem extra:allow —
    a var é aceita no .env mas o atributo não existe, e o acesso levantaria
    AttributeError)."""
    assert classifier.modelo() == "gemini-2.5-flash-lite"
    monkeypatch.setenv("RECUPERACAO_CLASSIFIER_MODEL", "gemini-2.5-flash")
    assert classifier.modelo() == "gemini-2.5-flash"

    assert classifier.timeout_segundos() == 12.0
    monkeypatch.setenv("RECUPERACAO_CLASSIFIER_TIMEOUT_S", "3.5")
    assert classifier.timeout_segundos() == 3.5
    monkeypatch.setenv("RECUPERACAO_CLASSIFIER_TIMEOUT_S", "nao-e-numero")
    assert classifier.timeout_segundos() == 12.0
    monkeypatch.setenv("RECUPERACAO_CLASSIFIER_TIMEOUT_S", "0")
    assert classifier.timeout_segundos() == 12.0


async def test_gasto_e_contabilizado_em_token_usage(_sem_supabase):
    """O budget_guard só enxerga o que está em token_usage.

    O resumo de qualificação rodou off-book por meses e mascarava o gasto real
    (summary.py:178-180). Uma chamada por turno de exceção em ~900 leads é barata,
    mas invisível ela deixa de ser auditável.
    """
    with _patch_generate(_resposta(engine.CLASSE_PERGUNTA)):
        await classifier.classificar("voces entregam em Alagoas?", lead_id="lead-123")
    assert len(_sem_supabase) == 1
    linha = _sem_supabase[0]
    assert linha["call_type"] == "button_flow_classify"
    assert linha["model"] == classifier.modelo()
    assert linha["lead_id"] == "lead-123"
    assert linha["prompt_tokens"] > 0


async def test_contabilidade_quebrada_nao_derruba_o_turno(monkeypatch):
    """Fail-soft: erro ao gravar custo não pode custar a classificação do lead."""
    def _explode(**_kwargs):
        raise RuntimeError("PGRST204")

    monkeypatch.setattr("app.agent.token_tracker.track_token_usage", _explode)
    with _patch_generate(_resposta(engine.CLASSE_QUENTE)):
        assert await classifier.classificar("me manda a tabela") == engine.CLASSE_QUENTE


# ── O prompt continua estreito ──────────────────────────────────────────────
_EXEMPLOS_VERBATIM = [t for t, _ in _GATILHOS if t not in ("bom dia", "audio")]


@pytest.mark.parametrize("exemplo", _EXEMPLOS_VERBATIM)
def test_prompt_carrega_os_exemplos_verbatim(exemplo):
    """Os exemplos são registro do dataset, não invenção de prompt.

    Trocar por paráfrase perde o que o cliente realmente escreve: sem acento, com
    erro de digitação, com CNPJ colado no meio do pedido.
    """
    assert exemplo in classifier.INSTRUCAO_SISTEMA


def test_prompt_carrega_os_desempates():
    """As três regras do dossiê + a regra do "Nao" isolado estão escritas no prompt."""
    prompt = classifier.INSTRUCAO_SISTEMA
    assert "Duvida entre SAIR e ADIAR: responda ADIAR" in prompt
    assert "Duvida entre QUENTE e PERGUNTA: responda QUENTE" in prompt
    assert '"obrigado", "ja compro com o Joao", "acabei de repor" nunca sao SAIR' in prompt
    assert '"Nao" sozinho e RUIDO, nunca SAIR' in prompt


def test_prompt_nomeia_exatamente_as_seis_classes():
    for classe in engine.CLASSES:
        assert f"{classe}:" in classifier.INSTRUCAO_SISTEMA


def test_prompt_nao_vira_persona():
    """Sem persona, sem catálogo, sem preço: quem escreve para o cliente é flows.py.

    O turno modal da ValerIA custa ~35.565 tokens de input; este tem que continuar na
    casa das centenas — é a diferença entre uma camada e uma terceira persona (§D1).
    """
    assert len(classifier.INSTRUCAO_SISTEMA) <= classifier.MAX_CHARS_INSTRUCAO
    prompt = classifier.INSTRUCAO_SISTEMA.lower()
    for proibido in ("valéria", "valeria", "persona", "microlote", "frete", "r$", "desconto"):
        assert proibido not in prompt, f"{proibido!r} não tem lugar no classificador"


# ── Contrato de robustez ────────────────────────────────────────────────────
@pytest.mark.parametrize("texto", [
    None, "", "   ", "?", "👍", "n", "Nao", "x" * 4000,
    "bom dia\nvcs tem cafe?\nquanto ta?",
])
async def test_nunca_levanta_e_sempre_devolve_classe_valida(texto):
    """Contrato com o runner (W1): a chamada não tem caminho de exceção.

    Vale inclusive para entrada fora do tipo declarado (None), porque o texto vem de
    `messages.content` e o webhook da Meta já entregou nulo em campo obrigatório.
    """
    with _patch_generate(RuntimeError("qualquer coisa")):
        assert await classifier.classificar(texto) in engine.CLASSES
    with _patch_generate(_resposta(engine.CLASSE_SAIR)):
        assert await classifier.classificar(texto) in engine.CLASSES
