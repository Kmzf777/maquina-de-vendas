"""As duas lacunas do runner da ValerIA de botões, fechadas em 30/09/2026.

Desde 01/10/2026 a Meta cobra POR MENSAGEM ENVIADA, inclusive dentro da janela de
24h. As duas lacunas abaixo custam mensagem faturada, e é por isso que elas viraram
testes antes de virarem código.

── Lacuna 1 · o fluxo gastava o orçamento discutindo com um robô ─────────────
`buffer/processor.py` dá `return` INCONDICIONAL quando um fluxo de botões assume a
conversa, e o gate determinístico de autoresponder do processor (`_handle_autoresponder`,
caso Letícia/Duo Gelatto) mora DEPOIS desse return. O irmão (`button_flow/runner.py`,
o bot da Recuperação que já rodou em produção) tem detector próprio por causa disso;
o `valeria_runner` não tinha nenhum.

No dado medido deste repo, **~28% das "respostas"** são a saudação automática do
WhatsApp Business do PRÓPRIO cliente (17 de 36 textos livres do broadcast
`utilidade_geral_produto_v1`, 494 entregues). Sem detector, cada uma dessas chegava
como texto livre, o motor reoferecia os botões e o lead podia gastar os 3 nudges
inteiros — 3 mensagens faturadas — discutindo com um robô que nunca vai tocar em
botão nenhum. A 28% dos leads isso é desperdício recorrente e garantido.

O que os testes fixam: um autoresponder NÃO avança o nó, NÃO gasta nudge e NÃO
manda mensagem; um texto humano de verdade continua gastando nudge (a prova de que
o detector não está engolindo tudo); e três autoresponders seguidos não esgotam o
orçamento nem levam o lead ao T_HUMANO.

── Lacuna 2 · a rede de segurança do rótulo editado estava desligada ────────
As duas metades existiam e o meio não ligava:
  • `valeria_engine._casar` lê o histórico do `flow_state` da CONVERSA, na forma
    `{node_id: {rotulo: botao_id}}`;
  • `PUT /api/valeria-flow/{node_id}` grava na COLUNA
    `valeria_flow_content.rotulos_antigos`, na forma `[{botao_id, rotulo, em}]`;
  • `valeria_runner._carregar_conteudo` devolvia `(nós, terminais, nudge, rótulo da
    lista)` e nunca repassava a coluna — e nenhuma outra linha de `app/` escrevia
    aquela chave do `flow_state`.

Resultado: o lead que recebeu a tela ANTIGA e toca nela não casa com botão nenhum,
cai no nudge e queima uma mensagem faturada — exatamente o que a coluna existe para
impedir. O caminho real do clique-só-com-texto é o quick reply de TEMPLATE
(`webhook/meta_parser.py:148`: não mandamos o parâmetro `payload` no componente de
botão, então a Meta devolve o TEXTO do botão como payload).

As formas são diferentes de PROPÓSITO e os testes tratam as duas como contrato: a
lista da coluna casa com o default `'[]'::jsonb` e sobrevive a dois botões que um dia
compartilhem rótulo; o dict é a estrutura de busca do motor. Converte-se, não se
muda nenhum dos lados.
"""
import ast
from pathlib import Path

import pytest

from app.button_flow import valeria_content, valeria_registry as reg
from app.button_flow import valeria_runner as runner


class ProvedorFalso:
    def __init__(self):
        self.chamadas = []

    async def send_interactive_buttons(self, to, body, buttons, image_url=None):
        self.chamadas.append(("botoes", body, buttons, image_url))
        return {"messages": [{"id": "wamid.1"}]}

    async def send_interactive_list(self, to, body, button, rows, header=None):
        self.chamadas.append(("lista", body, rows))
        return {"messages": [{"id": "wamid.2"}]}

    async def send_text(self, to, text):
        self.chamadas.append(("texto", text))
        return {"messages": [{"id": "wamid.3"}]}

    async def send_contact(self, to, *, contact_name, contact_phone):
        self.chamadas.append(("cartao", contact_name, contact_phone))
        return {"messages": [{"id": "wamid.4"}]}


# A marca invisível U+200E (LEFT-TO-RIGHT MARK) que o WhatsApp Business injeta na
# mensagem automática — a assinatura mais precisa do detector (44 mensagens
# `role='user'` do banco inteiro a contêm, e as 44 são saudação de empresa).
#
# Montada com `chr()`, e NÃO colada como caractere nem escrita como escape `\\u200e`
# dentro de um literal. O caractere colado é invisível: um editor que normalize o
# arquivo (ou um encoder que o atravesse) o apaga sem deixar rastro, e o teste passa
# a testar outra coisa em silêncio — `button_flow/autoreply.py` documenta a mesma
# armadilha para o próprio detector. `chr(0x200E)` é ASCII puro no arquivo e não tem
# como ser normalizado.
MARCA_INVISIVEL = chr(0x200E)

# Verbatim do dump de produção (`research/freetext.json`, lag 0,0h).
ROBO = MARCA_INVISIVEL + "Empório Vilela agradece seu contato! já retornaremos"

# Cliente de verdade, e um dos que derrubaram a primeira versão da regex do
# detector: pergunta curta, direta, sem nenhum sinal de placa de porta.
HUMANO = "e quanto custa o quilo pra revenda?"

# O rótulo que saiu do ar. Acentuado de propósito: o histórico atravessa o banco
# (jsonb), o runner e `normalizar` antes de chegar ao `_casar`, e acento virando
# '?' é modo de falha recorrente neste repo.
ROTULO_ANTIGO = "Café com a minha marca"
EM = "2026-09-29T12:00:00+00:00"


def _linha_de_historico(botao_id: str = "marca", rotulo: str = ROTULO_ANTIGO) -> dict:
    """Uma entrada da coluna, na forma EXATA que `_versionar` grava."""
    return {"botao_id": botao_id, "rotulo": rotulo, "em": EM}


@pytest.fixture
def turno(monkeypatch):
    """Dirige `processar_inbound` com banco, CRM e histórico dublados.

    Mesma forma da fixture de `test_valeria_runner_2026_09_29.py`, com três dublês
    novos: `_historico` (o detector de autoresponder pede o lag da nossa última
    saída), `effects.atualizar_metadata` (a marca `auto_reply` do turno silenciado)
    e um `valeria_content.carregar` MUTÁVEL, para o teste montar a linha de override.
    """
    from app.button_flow import effects
    from app.button_flow import runner as irmao

    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    # `_motivo_para_nao_rodar` é reusado do irmão e resolve `is_lead_blacklisted` no
    # namespace DELE. Sem o dublê cada turno tenta resolver DNS e cai no fail-soft —
    # não é o que está sob teste, e o timeout multiplica por turno.
    monkeypatch.setattr(irmao, "is_lead_blacklisted", lambda _lead_id: False)
    registro = {"efeitos": [], "mensagens": [], "metadata": [],
                "historico": [], "gravacoes": [], "consultas": []}
    conversa = {"id": "C1", "stage": "atacado", "flow_state": None}
    lead = {"id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
            "name": "Roner", "human_control": False, "metadata": {}}
    overrides: dict = {}

    def _gravar_estado(_cid, **kw):
        registro["gravacoes"].append(kw["flow_state"])
        conversa["flow_state"] = kw["flow_state"]

    def _marcar_metadata(_lead, campos, *, rotulo):
        registro["metadata"].append((rotulo, campos))
        return True

    def _ler_historico(conversation_id):
        registro["consultas"].append(conversation_id)
        return registro["historico"]

    monkeypatch.setattr(runner, "_reler_estado", lambda c: c.get("flow_state"))
    monkeypatch.setattr(runner, "get_open_deal", lambda _l: None)
    monkeypatch.setattr(runner, "update_conversation", _gravar_estado)
    monkeypatch.setattr(runner, "save_message",
                        lambda *a, **k: registro["mensagens"].append(a[3]))
    monkeypatch.setattr(runner, "url_publica_da_foto", lambda _c: None)
    monkeypatch.setattr(runner, "preco_do_no", lambda _no: "R$ 28,70")
    monkeypatch.setattr(runner, "save_score_evidence", lambda **kw: None)
    monkeypatch.setattr(runner, "_historico", _ler_historico)
    monkeypatch.setattr(valeria_content, "carregar", lambda _f: overrides)
    monkeypatch.setattr(effects, "anotar", lambda *a: None)
    monkeypatch.setattr(effects, "atualizar_metadata", _marcar_metadata)

    def _aplicar(efeitos, **_kw):
        registro["efeitos"].append(efeitos)
        return True
    monkeypatch.setattr(effects, "aplicar", _aplicar)

    provedor = ProvedorFalso()

    async def _rodar(texto, *, payload=None, titulo=""):
        meta = {"payload": payload, "title": titulo} if payload else None
        await runner.processar_inbound(
            lead=lead, conversation=conversa, channel={"mode": "ai"},
            provider=provedor, texto=texto, metadata=meta, wamid="wamid.in",
        )
        return conversa["flow_state"]

    _rodar.provedor = provedor
    _rodar.registro = registro
    _rodar.overrides = overrides
    _rodar.conversa = conversa
    return _rodar


# ═══════════════════════════════════════════════════════════════════════════════
# Lacuna 1 · o robô de saudação do lead
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_autoresponder_do_lead_nao_avanca_o_no_nem_gasta_nudge(turno):
    """~28% das respostas da base são o robô do cliente. Nenhuma pode custar nudge.

    O nudge existe para LIMITAR desperdício — gastá-lo com um robô é o oposto do
    que ele serve, e ainda tira do lead a reoferta que só um humano consegue usar.
    """
    await turno("oi, queria saber sobre café")
    assert len(turno.provedor.chamadas) == 1, "a tela de entrada não saiu"

    estado = await turno(ROBO)

    assert len(turno.provedor.chamadas) == 1, "respondeu ao robô do cliente"
    assert estado["node"] == reg.NO_ENTRADA, "o robô moveu o fluxo"
    assert estado["nudges"] == 0, "o robô gastou um nudge do lead"
    assert len(turno.registro["gravacoes"]) == 1, "turno de robô gravou estado"


@pytest.mark.asyncio
async def test_autoresponder_marca_o_lead_para_medicao(turno):
    """A marca `auto_reply` é como o CRM sabe que aquele turno foi um robô."""
    await turno("oi")
    await turno(ROBO)
    rotulos = [r for r, _c in turno.registro["metadata"]]
    assert "auto_reply" in rotulos, "o turno silenciado não deixou rastro"
    campos = dict(turno.registro["metadata"][0][1])
    assert campos["auto_reply"]["origem"] == "valeria_botoes"


@pytest.mark.asyncio
async def test_texto_humano_de_verdade_continua_gastando_nudge(turno):
    """A prova de que o detector não está engolindo todo texto livre.

    Sem esta asserção um detector que devolvesse True sempre passaria nos testes
    acima — e a ValerIA ficaria muda para quem digita, que é o caso comum.
    """
    await turno("oi")
    estado = await turno(HUMANO)
    assert estado["nudges"] == 1
    assert estado["node"] == reg.NO_ENTRADA, "o nudge não avança o fluxo"
    assert reg.CORPO_NUDGE in turno.provedor.chamadas[-1][1]


@pytest.mark.asyncio
async def test_tres_autoresponders_seguidos_nao_esgotam_o_orcamento(turno):
    """Três robôs em sequência não podem levar o lead ao T_HUMANO.

    É o cenário exato do desperdício: o robô do cliente responde a cada envio
    nosso, e com o nudge sendo gasto o terceiro turno estouraria `TETO_NUDGES` e
    entregaria ao vendedor um lead que nunca leu uma linha.
    """
    await turno("oi")
    # O turno de abertura já aplicou os efeitos (vazios) da tela de entrada; o que
    # se mede aqui é o que os robôs acrescentam a partir dele.
    turno.registro["efeitos"].clear()

    estado = None
    for _ in range(reg.TETO_NUDGES):
        estado = await turno(ROBO)

    assert estado["nudges"] == 0
    assert estado["node"] == reg.NO_ENTRADA
    assert len(turno.provedor.chamadas) == 1, "gastou mensagem faturada com robô"
    assert turno.registro["efeitos"] == [], "aplicou efeito de CRM por causa do robô"

    # E o orçamento segue INTEIRO: o humano ainda tem as três reofertas dele.
    estado = await turno(HUMANO)
    assert estado["nudges"] == 1
    assert estado["node"] == reg.NO_ENTRADA


@pytest.mark.asyncio
async def test_pedido_de_saida_nunca_e_silenciado_como_robo(turno):
    """Opt-out vence o detector. Silenciar quem pede para sair é o pior erro aqui.

    O próprio `button_flow/autoreply.py` declara isso no cabeçalho: falso positivo
    emudece um cliente real, e "para de me mandar isso" silenciado é opt-out não
    honrado (52 casos em produção). O detector é assimétrico por isso, e a ordem
    das guardas no runner é a última linha dessa defesa.
    """
    await turno("oi")
    estado = await turno("descadastrar")
    assert estado["node"] == "T_OPTOUT"
    assert turno.registro["efeitos"][-1].optout is True


@pytest.mark.asyncio
async def test_clique_nao_passa_pelo_detector(turno):
    """Clique é toque humano por definição — nem o histórico é consultado.

    A consulta de histórico é I/O por turno; pagá-la num clique seria uma ida ao
    banco a mais em 100% dos toques para perguntar algo que já se sabe.
    """
    await turno("oi")
    turno.registro["consultas"].clear()
    estado = await turno("Pro meu negócio", payload="negocio",
                         titulo="Pro meu negócio")
    assert turno.registro["consultas"] == [], "clique foi ao banco sem motivo"
    assert estado["node"] == "N1"


# ═══════════════════════════════════════════════════════════════════════════════
# Lacuna 2 · a coluna `rotulos_antigos` chega ao motor
# ═══════════════════════════════════════════════════════════════════════════════
def test_reshape_converte_a_lista_da_coluna_no_mapa_do_motor():
    """Da forma da COLUNA para a forma que `valeria_engine._casar` indexa."""
    mapa = valeria_content.historico_de_rotulos({
        "N0": {"corpo": None, "rotulos": {},
               "rotulos_antigos": [_linha_de_historico()]},
    })
    assert mapa == {"N0": {ROTULO_ANTIGO: "marca"}}


def test_reshape_sobrevive_a_linha_sem_corpo_e_sem_rotulos():
    """É o que o DELETE da rota deixa para trás: linha zerada, histórico vivo.

    `api_delete_conteudo` grava `corpo=None, rotulos=None` e PRESERVA
    `rotulos_antigos` — justamente porque o rótulo editado acabou de sair do ar e
    quem o recebeu ainda pode tocar nele. Se o reshape exigisse corpo ou rótulo, o
    histórico morreria no momento em que ele mais importa.
    """
    mapa = valeria_content.historico_de_rotulos({
        "N0": {"corpo": None, "rotulos": None,
               "rotulos_antigos": [_linha_de_historico()]},
    })
    assert mapa == {"N0": {ROTULO_ANTIGO: "marca"}}


def test_reshape_ignora_entrada_incompleta_sem_derrubar_as_boas():
    """jsonb aceita qualquer forma: uma entrada torta não pode levar as outras."""
    mapa = valeria_content.historico_de_rotulos({
        "N0": {"rotulos_antigos": [
            {"botao_id": "marca"},                    # sem rótulo
            {"rotulo": "Só o texto"},                 # sem botão
            {"botao_id": "consumo", "rotulo": "   "},  # rótulo em branco
            "lixo",
            None,
            _linha_de_historico(),
        ]},
    })
    assert mapa == {"N0": {ROTULO_ANTIGO: "marca"}}


def test_reshape_nao_estoura_com_qualquer_lixo_na_coluna():
    for lixo in (None, [], {}, "texto", 7, {"rotulos_antigos": "texto"},
                 {"rotulos_antigos": 3}, {"N0": None}, {"N0": "lixo"}):
        assert isinstance(valeria_content.historico_de_rotulos(lixo), dict)


def test_reshape_com_rotulo_repetido_fica_com_a_entrada_mais_recente():
    """A coluna é uma LISTA e aceita dois botões com o mesmo rótulo; o mapa não.

    `_versionar` APPENDA, então a última entrada é a mais nova — e é ela que
    descreve a tela mais parecida com a que o lead tem na mão.
    """
    mapa = valeria_content.historico_de_rotulos({
        "N0": {"rotulos_antigos": [
            _linha_de_historico("consumo", "Rótulo repetido"),
            _linha_de_historico("marca", "Rótulo repetido"),
        ]},
    })
    assert mapa == {"N0": {"Rótulo repetido": "marca"}}


def test_reshape_omite_o_no_sem_historico():
    """Nó com override de texto mas sem rótulo trocado não entra no mapa.

    Entrar com `{}` faria `_casar` montar um dict vazio por nó a cada clique sem
    ganhar nada, e apagaria a diferença observável entre "não há histórico" e
    "há histórico vazio".
    """
    mapa = valeria_content.historico_de_rotulos({
        "N0": {"corpo": "texto novo", "rotulos": {}, "rotulos_antigos": []},
    })
    assert mapa == {}


@pytest.mark.asyncio
async def test_clique_em_rotulo_ja_substituido_chega_ao_destino_certo(turno):
    """Ponta a ponta pelo RUNNER: rótulo trocado na tela, clique da tela antiga.

    O destino é o que prova o acerto: `marca` leva a P1 (private label), e P1 é o
    único nó do fluxo alcançável por aquele botão. Cair no nudge (N0 de novo) é o
    defeito que este teste existe para pegar — e vale uma mensagem faturada.
    """
    turno.overrides["N0"] = {
        "corpo": None,
        "rotulos": {"marca": "Marca própria"},
        "rotulos_antigos": [_linha_de_historico()],
    }
    await turno("oi")
    estado = await turno(ROTULO_ANTIGO, payload=ROTULO_ANTIGO, titulo=ROTULO_ANTIGO)

    assert estado["node"] == "P1", "o clique da tela antiga caiu no nudge"
    assert estado["nudges"] == 0
    assert reg.NOS["P1"].corpo in turno.provedor.chamadas[-1][1]


@pytest.mark.asyncio
async def test_rotulo_antigo_casa_mesmo_com_o_acento_perdido_no_caminho(turno):
    """Há 64 cliques em produção gravados como "Nao tenho interesse" e ZERO com o
    acento. `normalizar` nas duas pontas é contrato, e o histórico passa por ele."""
    turno.overrides["N0"] = {
        "corpo": None, "rotulos": {"marca": "Marca própria"},
        "rotulos_antigos": [_linha_de_historico()],
    }
    await turno("oi")
    sem_acento = "Cafe com a minha marca"
    assert sem_acento != ROTULO_ANTIGO, "o verbatim do teste perdeu o acento"
    estado = await turno(sem_acento, payload=sem_acento, titulo=sem_acento)
    assert estado["node"] == "P1"


@pytest.mark.asyncio
async def test_historico_vive_em_linha_sem_corpo_e_sem_rotulos_ate_o_runner(turno):
    """A linha que o DELETE deixa (corpo e rótulos nulos) ainda salva o clique."""
    turno.overrides["N0"] = {
        "corpo": None, "rotulos": None,
        "rotulos_antigos": [_linha_de_historico()],
    }
    await turno("oi")
    estado = await turno(ROTULO_ANTIGO, payload=ROTULO_ANTIGO, titulo=ROTULO_ANTIGO)
    assert estado["node"] == "P1"


@pytest.mark.asyncio
async def test_lead_sem_override_nenhum_se_comporta_como_hoje(turno):
    """Sem linha na tabela: nada de histórico, defaults do registry, nudge normal."""
    await turno("oi")
    assert turno.provedor.chamadas[0][0] == "lista"
    assert reg.NOS["N0"].corpo in turno.provedor.chamadas[0][1]

    estado = await turno(ROTULO_ANTIGO, payload=ROTULO_ANTIGO, titulo=ROTULO_ANTIGO)
    assert estado["node"] == reg.NO_ENTRADA, "casou um rótulo que nunca existiu"
    assert estado["nudges"] == 1
    assert "rotulos_antigos" not in estado


@pytest.mark.asyncio
async def test_historico_nao_e_espelhado_dentro_do_flow_state(turno):
    """O histórico é OVERLAY de leitura, não cópia persistida.

    A coluna é a fonte e é lida a cada turno. Persistir o mapa em
    `conversations.flow_state` criaria um espelho por conversa que envelhece na
    primeira edição de rótulo seguinte — e engordaria o jsonb de todo turno com
    dados que já estão no banco.
    """
    turno.overrides["N0"] = {
        "corpo": None, "rotulos": {"marca": "Marca própria"},
        "rotulos_antigos": [_linha_de_historico()],
    }
    await turno("oi")
    estado = await turno(ROTULO_ANTIGO, payload=ROTULO_ANTIGO, titulo=ROTULO_ANTIGO)
    assert estado["node"] == "P1"
    for gravado in turno.registro["gravacoes"]:
        assert "rotulos_antigos" not in gravado


@pytest.mark.asyncio
async def test_falha_ao_ler_overrides_nao_tira_o_historico_do_caminho(turno, monkeypatch):
    """`carregar` é fail-open: sem banco, o fluxo roda nos defaults, sem histórico.

    O reshape entra DEPOIS do fail-open de `_carregar_conteudo`, então migration
    pendente ou PostgREST fora continua produzindo exatamente os defaults do
    registry — e não uma ValerIA muda.
    """
    def explode(_flow):
        raise RuntimeError("PostgREST fora")
    monkeypatch.setattr(valeria_content, "carregar", explode)
    estado = await turno("oi")
    assert estado["node"] == reg.NO_ENTRADA
    assert turno.provedor.chamadas[0][0] == "lista"


# ═══════════════════════════════════════════════════════════════════════════════
# As três armadilhas que já morderam esta feature
# ═══════════════════════════════════════════════════════════════════════════════
_TOCADOS = ("app/button_flow/valeria_runner.py", "app/button_flow/valeria_content.py")


def _raiz() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("relativo", _TOCADOS)
def test_arquivo_tocado_decodifica_em_utf8_estrito_e_compila(relativo):
    """Armadilha 1 (newline real dentro de literal quebrou um módulo) + armadilha 2
    (acento persistido como '?'). Decodifica em UTF-8 ESTRITO e passa no ast."""
    bruto = (_raiz() / relativo).read_bytes()
    fonte = bruto.decode("utf-8")  # estrito: qualquer byte torto levanta aqui
    ast.parse(fonte)


@pytest.mark.parametrize("relativo", _TOCADOS)
def test_acentos_do_portugues_sobreviveram_no_arquivo(relativo):
    """Acento virando '?' é modo de falha recorrente aqui. Prova por amostra."""
    fonte = (_raiz() / relativo).read_bytes().decode("utf-8")
    for palavra in ("histórico", "rótulo", "não"):
        assert palavra in fonte, f"{palavra!r} perdeu o acento em {relativo}"


def test_este_arquivo_nao_guarda_a_marca_invisivel_colada():
    """A armadilha de `autoreply.py`, aplicada ao próprio teste.

    Se a U+200E estiver COLADA no fonte, um editor que normalize o arquivo a apaga
    sem rastro: `ROBO` deixaria de ter assinatura, o detector pararia de marcá-la e
    os testes da lacuna 1 passariam a afirmar o contrário do que dizem — em
    silêncio. Montada por `chr(0x200E)`, ela não pode se perder.
    """
    fonte = Path(__file__).read_bytes().decode("utf-8")
    assert MARCA_INVISIVEL not in fonte, "a marca foi colada no fonte"
    assert MARCA_INVISIVEL in ROBO, "o verbatim do robô perdeu a assinatura"
