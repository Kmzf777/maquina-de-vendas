"""Estrutura do fluxo de botões v2 da ValerIA (vitrine primeiro). Dado puro, zero lógica.

Mesmo papel do `valeria_registry.py` (v1): o CONTRATO entre a tela, o motor
(`valeria_engine_v2.py`) e o runner (`valeria_runner_v2.py`). A tela edita
`corpo`, `rotulos`, o corpo dos cards e os textos das chaves reservadas
(`CHAVES_TEXTO`); quem existe e para onde cada botão vai é DECLARADO aqui e
verificado por tests/test_valeria_v2_registry.py.

Fonte: docs/superpowers/specs/2026-10-08-valeria-botoes-v2-vitrine-design.md.
  • §4 — os ÚNICOS números que o funil pode afirmar. Kit Amostra e Microlote PL
    estão PENDENTES com o João e não aparecem como número em lugar nenhum: o kit
    não tem preço no texto, e o card do Microlote PL só cita `{preco:...}` e só sai
    quando o catálogo disser `min_lot = 100 un`.
  • §5 — nós, rótulos, destinos e a coluna "Grava".
  • §6 — vitrine: carrossel, tabela, regras, "como funciona" e as respostas fixas
    da lista de dúvidas (§6.4).
Os corpos que NÃO estão na spec estão marcados com "COMPOSTO" no lugar.

Reusa da v1, por import (um tipo, um dono): `Botao`, `No`, `Terminal`, `Card`,
as tags, os vendedores, a folha de prazos e os terminais que a §5 manda copiar
sem mudança. Os nós Consumo (C1) e Exportação (E1–E4) também vêm da v1; só o
C1 troca o destino de "Quero em quantidade" (N1 → VA).

── Ids especiais de destino (interpretados pelo motor v2) ───────────────────
  • "faq:<faq_id>" — linha da lista de dúvidas: manda a resposta fixa de `FAQ`
    e volta à tela de onde o lead veio (`flow_state.retorno`).
  • "tabela"       — reenvia a tabela + os botões de ação da vitrine do ramo.
  • "handoff"      — handoff do ramo (`HANDOFF_DO_RAMO`).
  • "regra:QP2"    — destino lido de `REGRA_QP2` com a resposta gravada no QP1.
"""
from __future__ import annotations

from dataclasses import replace

from app.button_flow.engine import normalizar
from app.button_flow.valeria_registry import (  # noqa: F401 — reexportados para o motor/runner v2
    BOTOES_PRAZO,
    CHAVE_NUDGE,
    CHAVE_ROTULO_LISTA,
    CORPO_NUDGE,
    DIAS_POR_PRAZO,
    LIMITE_DESC_LISTA,
    LIMITE_ROTULO_BOTAO,
    LIMITE_TITULO_LISTA,
    MAX_BOTOES,
    MAX_LINHAS_LISTA,
    NOS as _NOS_V1,
    ROTULO_BOTAO_LISTA,
    TAG_ADIADO,
    TAG_HUMANO,
    TAG_OPTOUT,
    TAG_QUALIFICADO,
    TERMINAIS as _TERMINAIS_V1,
    VENDEDOR_ATACADO,
    VENDEDOR_EXPORTACAO,
    Botao,
    Card,
    No,
    Terminal,
)

FLOW_ID = "valeria_botoes_v2"
NO_ENTRADA = "N0"

# Tag nova da v2 (spec §4/§5.2). Resolvida POR NOME EXATO por `add_tags_to_lead`,
# que NÃO cria tag: se ela não estiver semeada em `tags`, o lead simplesmente não
# é marcado (sem erro). Mesma armadilha documentada no bloco de tags da v1.
TAG_KIT = "Botões: Kit amostra"

# 2º RUIDO seguido (texto que o classificador não entendeu) → repasse do ramo
# (spec §7.2). Substitui o TETO_NUDGES da v1: lá o texto era sempre rebatido.
TETO_RUIDO = 2

# Corpo da 3ª mensagem da vitrine, a dos botões de ação (spec §6.1 e §6.2).
CORPO_ACOES = "como você quer seguir?"


# ─── Os cards do carrossel (spec §6.1 e §6.2) ────────────────────────────────
#
# Preço SÓ por marcador `{preco:<products.name exato>}`, resolvido pelo runner
# contra `products` no envio (`valeria_tabela.resolver_card`). O card some se
# algum SKU sumir: preço errado é pior que preço nenhum (§6.3).
#
# Orçamento de tamanho: ≤ 160 caracteres e ≤ 2 quebras DEPOIS de resolver os
# preços (limite da Meta para o corpo do card). O teste mede isso com o
# catálogo de produção e com um preço de 9 caracteres em todo marcador.

_SKUS_CLASSICO = (
    "Canastra Clássico — Moído 250g",
    "Canastra Clássico — Em Grãos 250g",
    "Canastra Clássico — Moído 500g",
    "Canastra Clássico — Em Grãos 500g",
    "Canastra Clássico — Em Grãos 1kg",
)
_SKUS_SUAVE = (
    "Canastra Suave — Moído 250g",
    "Canastra Suave — Em Grãos 250g",
    "Canastra Suave — Moído 500g",
    "Canastra Suave — Em Grãos 500g",
    "Canastra Suave — Em Grãos 1kg",
)


def _corpo_tradicional(cabecalho: str, skus: tuple[str, ...]) -> str:
    """Monta o corpo dos cards Clássico/Suave na forma da spec §6.1.

    Só concatena texto declarado — é a mesma frase para os dois cards, mudando a
    nota sensorial e os SKUs, e escrevê-la duas vezes à mão é como um travessão
    errado num nome de produto passa despercebido.
    """
    m250, g250, m500, g500, g1kg = skus
    return (
        f"{cabecalho}\n"
        f"250g: moído {{preco:{m250}}} · grão {{preco:{g250}}}\n"
        f"500g moído {{preco:{m500}}} · grão {{preco:{g500}}} · 1kg grão {{preco:{g1kg}}}"
    )


CARDS_ATACADO: tuple[Card, ...] = (
    Card(
        id="classico", foto="atacado/foto_1_classico.jpg",
        corpo=_corpo_tradicional("Clássico · torra escura, caramelo e chocolate · 84 pts",
                                 _SKUS_CLASSICO),
        skus=_SKUS_CLASSICO, destino="QA1",
    ),
    Card(
        id="suave", foto="atacado/foto_2_suave.jpg",
        # §6.1: "idem, com notas 'torra média, achocolatado'".
        corpo=_corpo_tradicional("Suave · torra média, achocolatado · 84 pts", _SKUS_SUAVE),
        skus=_SKUS_SUAVE, destino="QA1",
    ),
    Card(
        id="microlote", foto="atacado/foto_4_microlote.png",
        # A spec escreve `{preco:Microlote 250g}`; no catálogo são dois SKUs
        # (moído e grão), e o card cita os dois pelo nome exato.
        corpo=(
            "Microlote · 86 pts, cacau, melaço e cítrico\n"
            "250g moído {preco:Microlote — Moído 250g} · grão {preco:Microlote — Em Grãos 250g}"
        ),
        skus=("Microlote — Moído 250g", "Microlote — Em Grãos 250g"), destino="QA1",
    ),
)

CARDS_PL: tuple[Card, ...] = (
    Card(
        # foto_3 é o silk (agent/tools.py, CATALOGO_FOTOS["private_label"]).
        id="embalagem_canastra", foto="private_label/foto_3.jpg",
        corpo=(
            "Sua marca na embalagem Canastra\n"
            "250g {preco:Café Canastra 250g — c/ embalagem Canastra} · "
            "500g {preco:Café Canastra 500g — c/ embalagem Canastra}\n"
            "mínimo 100 pacotes"
        ),
        skus=("Café Canastra 250g — c/ embalagem Canastra",
              "Café Canastra 500g — c/ embalagem Canastra"),
        destino="QP1",
    ),
    Card(
        # foto_1 é a embalagem (agent/tools.py, CATALOGO_FOTOS["private_label"]).
        id="embalagem_cliente", foto="private_label/foto_1.jpg",
        corpo=(
            "Sua própria embalagem, a gente enche\n"
            "250g {preco:Café Canastra 250g — embalagem do cliente} · "
            "500g {preco:Café Canastra 500g — embalagem do cliente}\n"
            "mínimo 100 pacotes"
        ),
        skus=("Café Canastra 250g — embalagem do cliente",
              "Café Canastra 500g — embalagem do cliente"),
        destino="QP1",
    ),
    Card(
        # PENDENTE (§4): o preço do Microlote PL não está confirmado e o catálogo
        # ainda diz `min_lot = 50 un` na embalagem do cliente. `exige_min_lot`
        # segura o card até alguém corrigir o catálogo pelo modal de Preços — e
        # mesmo então o número vem do catálogo, nunca deste texto.
        id="microlote", foto="private_label/foto_4.jpg",
        corpo=(
            "Microlote 86 pts com a sua marca\n"
            "250g {preco:Microlote 250g — c/ embalagem Canastra} · mínimo 100 pacotes"
        ),
        skus=("Microlote 250g — c/ embalagem Canastra",
              "Microlote 250g — embalagem do cliente"),
        exige_min_lot="100 un",
        destino="QP1",
    ),
)


# ─── Textos da vitrine que não são nó (chaves reservadas, editáveis) ─────────
#
# `valeria_flow_content` é chaveada por `node_id`; texto editável que não é nó
# ganha chave reservada, como o `__nudge__` da v1.
CHAVE_REGRAS_ATACADO = "__regras_atacado__"
CHAVE_COMO_FUNCIONA_PL = "__como_funciona_pl__"

# §6.1, mensagem 2: as 4 linhas de regra que fecham a tabela atacado. Os
# números são os de §4 (mínimo, frete, pagamento, revenda).
REGRAS_ATACADO_DEFAULT = (
    "✅ pedido mínimo R$500 — pode misturar os cafés\n"
    "🚚 frete grátis acima de R$2.000; abaixo, pelo CEP\n"
    "💳 PIX, cartão em 2x sem juros ou boleto à vista\n"
    "💰 revenda ao consumidor: 250g R$35–50 · 500g R$50–65"
)

# §6.2, mensagem 2. A spec escreve `{total}`; o marcador aqui é `{total_pl}`
# (contrato C2), resolvido por `valeria_tabela.como_funciona_pl` como
# 100 × preço("Café Canastra 250g — c/ embalagem Canastra").
COMO_FUNCIONA_PL_DEFAULT = (
    "como funciona a marca própria 📦\n\n"
    "exemplo: 100 pacotes de 250g na embalagem Canastra\n"
    "= {total_pl} + fotolito R$100 (só no 1º pedido) + frete\n\n"
    "1️⃣ você manda a arte  2️⃣ aprovamos juntos\n"
    "3️⃣ produção em até 15 dias úteis  4️⃣ envio (frete calculado à parte)\n\n"
    "💳 PIX, cartão em 2x sem juros ou boleto à vista\n"
    "💰 revenda ao consumidor: 250g R$35–50 · 500g R$50–65"
)


# ─── Respostas fixas da lista de dúvidas (spec §6.4) ─────────────────────────
#
# ramo → faq_id → texto default. Editáveis pela chave "faq:<ramo>:<faq_id>".
# O único `{preco:...}` é o do faq_capsula, resolvido no envio como os cards.
_PAGAMENTO = ("PIX, cartão em até 2x sem juros ou boleto à vista "
              "(o pedido sai depois da confirmação).")
_REVENDA = "Referência ao consumidor: 250g de R$35 a R$50 · 500g de R$50 a R$65."

FAQ: dict[str, dict[str, str]] = {
    "atacado": {
        "grao": ("Clássico, Suave e Microlote vêm em grão ou moído. Canela só moído. "
                 "1kg e granel só em grão."),
        "minimo": "R$500 por pedido, misturando os cafés e as quantidades como quiser.",
        "frete": "Grátis acima de R$2.000. Abaixo disso, calculado pelo seu CEP.",
        "pagamento": _PAGAMENTO,
        "revenda": _REVENDA,
        "capsula": (
            "Cápsulas compatíveis Nespresso (display 10) "
            "{preco:Cápsula Canastra Clássico — Display 10 cápsulas} · "
            "Drip (display 10 sachês) {preco:Drip Coffee Canastra Suave — Display 10 sachês}."
        ),
    },
    "private_label": {
        "grao": "Você escolhe: grão ou moído, no 250g ou no 500g.",
        "minimo": "100 pacotes por pedido.",
        "frete": "Sempre calculado à parte, pelo seu CEP.",
        "pagamento": _PAGAMENTO,
        "revenda": _REVENDA,
        "prazo_pl": "Produção em até 15 dias úteis depois da aprovação da arte.",
        "fotolito": ("Você manda a arte e a gente aprova junto. O fotolito custa R$100 "
                     "e é cobrado só no 1º pedido."),
    },
}

# faq_id → 1 linha para o prompt do classificador (spec §7.3). COMPOSTO: a spec
# pede "1 linha de descrição cada" sem escrevê-las. "preco" não é linha da lista:
# é a FAQ que reenvia a tabela (§7.3, "qual o valor do quilo?").
FAQ_DESCRICAO: dict[str, str] = {
    "grao": "se vem em grão ou moído, quais formatos e tamanhos existem",
    "minimo": "pedido mínimo, quantidade mínima por pedido",
    "frete": "frete, entrega, custo de envio, frete grátis",
    "pagamento": "formas de pagamento: PIX, cartão, boleto, parcelamento",
    "revenda": "preço sugerido de revenda ao consumidor final, margem",
    "capsula": "cápsulas e drip coffee",
    "prazo_pl": "prazo de produção da marca própria",
    "fotolito": "arte, logo, fotolito, criação da embalagem",
    "preco": "pede preço/valor/tabela",
}

# Toda chave editável que não é nó nem terminal (contrato C2/C7).
CHAVES_TEXTO: frozenset[str] = frozenset(
    {CHAVE_NUDGE, CHAVE_ROTULO_LISTA, CHAVE_REGRAS_ATACADO, CHAVE_COMO_FUNCIONA_PL}
    | {f"faq:{ramo}:{faq_id}" for ramo, faqs in FAQ.items() for faq_id in faqs}
)


# ─── Roteamento pela mensagem pronta do anúncio (spec §5.1) ──────────────────
#
# Igualdade depois de `engine.normalizar`, contra esta tupla fechada. Qualquer
# variação editada pelo lead vai para o N0. Nenhuma IA entra aqui.
_MENSAGENS_PRONTAS: tuple[tuple[str, str], ...] = (
    ("Olá! Tenho um comércio e quero revender café especial.", "VA"),
    ("Olá! Quero saber mais sobre compra por atacado.", "VA"),
    ("Olá! Quero café com a minha marca — já tenho CNPJ", "VP"),
    ("Olá! Quero saber mais sobre ter a Marca Própria de Café.", "VP"),
)
MENSAGENS_PRONTAS: dict[str, str] = {normalizar(t): no for t, no in _MENSAGENS_PRONTAS}


# ─── Os nós (spec §5.2) ──────────────────────────────────────────────────────

def _linhas_de_duvida(rotulos: tuple[tuple[str, str], ...], handoff: str) -> tuple[Botao, ...]:
    """Linhas da lista VD (§5.2): uma por FAQ do ramo + "Outra pergunta" + vendedor."""
    return (
        tuple(Botao(f"faq_{faq_id}", rotulo, f"faq:{faq_id}") for faq_id, rotulo in rotulos)
        + (Botao("faq_outra", "Outra pergunta", "VO"),
           Botao("faq_vendedor", "Falar com vendedor", handoff))
    )


_N0_V1 = {b.id: b for b in _NOS_V1["N0"].botoes}
_C1_V1 = {b.id: b for b in _NOS_V1["C1"].botoes}

# VD não tem corpo na spec. COMPOSTO, na voz da v1 (minúsculas, sem ponto final).
_CORPO_DUVIDAS = "claro! escolhe a sua dúvida aqui embaixo 👇"

NOS: dict[str, No] = {
    "N0": No(
        id="N0", rotulo_interno="N0 · Ramo", tela="lista", ramo="entrada",
        corpo="oi! aqui é a Valéria, do comercial da Café Canastra ☕ me diz: o café é pra qual caso?",
        # Mesmas linhas e descrições da v1; "negocio" e "marca" levam às vitrines.
        botoes=(
            replace(_N0_V1["negocio"], rotulo="Revender ou servir", destino="VA"),
            replace(_N0_V1["marca"], destino="VP"),
            _N0_V1["consumo"],
            _N0_V1["exportacao"],
        ),
    ),

    # ── Ramo atacado ───────────────────────────────────────────────────────
    "VA": No(
        id="VA", rotulo_interno="VA · Vitrine atacado", tela="carrossel", ramo="atacado",
        corpo=(
            "esses são os mais pedidos por cafeterias e empórios ☕ preço por pacote, "
            "direto da nossa fazenda na Serra da Canastra 👇"
        ),
        # Botões de AÇÃO: saem na 3ª mensagem, com `CORPO_ACOES` (§6.1).
        botoes=(
            Botao("pedido", "Fazer pedido", "QA1", grava=(("purchase_intent", "clear"),)),
            Botao("provar", "Provar antes", "VK"),
            Botao("duvida", "Tenho dúvida", "VD_A"),
        ),
        cards=CARDS_ATACADO,
    ),
    "QA1": No(
        id="QA1", rotulo_interno="QA1 · Tipo de negócio", tela="botoes", ramo="atacado",
        corpo="boa! pra eu já te passar pro João com tudo certo: que tipo de negócio você tem?",
        # Ids e `grava` idênticos aos do N1 da v1 (3 faixas do score).
        botoes=tuple(replace(b, destino="QA2") for b in _NOS_V1["N1"].botoes),
    ),
    "QA2": No(
        id="QA2", rotulo_interno="QA2 · Volume", tela="botoes", ramo="atacado",
        corpo="e quanto café você usa ou vende por mês, mais ou menos?",
        # Ids e `grava` do N2 da v1 (30/65/150 kg); rótulos de §5.2.
        botoes=(
            Botao("ate30", "Até 30 kg", "T_HANDOFF", grava=(("monthly_volume_kg", 30),)),
            Botao("ate100", "30 a 100 kg", "T_HANDOFF", grava=(("monthly_volume_kg", 65),)),
            Botao("mais100", "Mais de 100 kg", "T_HANDOFF", grava=(("monthly_volume_kg", 150),)),
        ),
    ),
    "VD_A": No(
        id="VD_A", rotulo_interno="VD · Dúvidas (atacado)", tela="lista", ramo="atacado",
        corpo=_CORPO_DUVIDAS,
        botoes=_linhas_de_duvida((
            ("grao", "Grão ou moído?"),
            ("minimo", "Pedido mínimo"),
            ("frete", "Frete"),
            ("pagamento", "Formas de pagamento"),
            ("revenda", "Preço de revenda"),
            ("capsula", "Cápsula e drip"),
        ), handoff="T_HANDOFF"),
    ),

    # ── Ramo private label ─────────────────────────────────────────────────
    "VP": No(
        id="VP", rotulo_interno="VP · Vitrine marca própria", tela="carrossel",
        ramo="private_label",
        corpo="a gente torra o café na nossa fazenda e entrega com a sua marca ☕ escolhe o formato 👇",
        botoes=(
            Botao("orcamento", "Fazer orçamento", "QP1"),
            Botao("provar", "Provar antes", "VK"),
            Botao("duvida", "Tenho dúvida", "VD_P"),
        ),
        cards=CARDS_PL,
    ),
    "QP1": No(
        id="QP1", rotulo_interno="QP1 · Marca", tela="botoes", ramo="private_label",
        corpo="pra montar seu orçamento: você já tem a marca?",
        botoes=(
            Botao("tenho_marca", "Já tenho a marca", "QP2"),
            Botao("criar_zero", "Vou criar do zero", "QP2"),
            # Igual à v1: quem só quer torra vai direto ao João.
            Botao("tenho_graos", "Já tenho os grãos", "T_HANDOFF_PL"),
        ),
    ),
    "QP2": No(
        id="QP2", rotulo_interno="QP2 · Quantidade", tela="botoes", ramo="private_label",
        corpo="e quantos pacotes no primeiro pedido?",
        # O destino real sai de `REGRA_QP2` com a resposta do QP1.
        botoes=(
            Botao("menos100", "Menos de 100", "regra:QP2"),
            Botao("de100a500", "100 a 500", "regra:QP2"),
            Botao("mais500", "Mais de 500", "regra:QP2"),
        ),
    ),
    "PL_ABAIXO": No(
        # A spec chama de terminal (`T_PL_ABAIXO`), mas ele TEM botões e não
        # repassa — no vocabulário destes tipos isso é um nó.
        id="PL_ABAIXO", rotulo_interno="PL abaixo do mínimo", tela="botoes",
        ramo="private_label",
        corpo=(
            "o mínimo pra marca própria é 100 pacotes. pra quem tá começando, um bom "
            "primeiro passo é provar nossos cafés com o kit amostra 😊"
        ),
        botoes=(
            Botao("quero_kit", "Quero o kit", "T_KIT"),
            Botao("depois", "Mais pra frente", "T_ADIAR"),
        ),
    ),
    "VD_P": No(
        id="VD_P", rotulo_interno="VD · Dúvidas (marca própria)", tela="lista",
        ramo="private_label",
        corpo=_CORPO_DUVIDAS,
        botoes=_linhas_de_duvida((
            ("grao", "Grão ou moído?"),
            ("minimo", "Pedido mínimo"),
            ("frete", "Frete"),
            ("pagamento", "Formas de pagamento"),
            ("revenda", "Preço de revenda"),
            ("prazo_pl", "Prazo de produção"),
            ("fotolito", "Arte e fotolito"),
        ), handoff="T_HANDOFF_PL"),
    ),

    # ── Telas compartilhadas pelos dois ramos ──────────────────────────────
    # `ramo="entrada"` aqui quer dizer "o nó não fixa ramo": o ramo da conversa
    # vem de `flow_state.ramo`, gravado quando o lead chegou à vitrine.
    "VK": No(
        id="VK", rotulo_interno="VK · Kit amostra", tela="botoes", ramo="entrada",
        # PENDENTE (§4): sem preço nem composição até o João confirmar; editável
        # na tela "Fluxo da Valéria" sem deploy.
        corpo=("temos um kit pra você provar nossos cafés antes do pedido 😊 "
               "o João te passa o valor e o frete pro seu CEP"),
        botoes=(
            Botao("quero_kit", "Quero o kit", "T_KIT"),
            Botao("ver_precos", "Ver preços de novo", "tabela"),
            Botao("vendedor", "Falar com vendedor", "handoff"),
        ),
    ),
    "VO": No(
        id="VO", rotulo_interno="VO · Outra pergunta", tela="botoes", ramo="entrada",
        # Sem botões: espera o texto do lead, que vai ao classificador (§5.2/§7).
        corpo="pode escrever sua pergunta 🙂",
        botoes=(),
    ),

    # ── Consumo e Exportação: copiados da v1 (§5) ──────────────────────────
    "C1": replace(
        _NOS_V1["C1"],
        botoes=(replace(_C1_V1["quantidade"], destino="VA"), _C1_V1["duvida"]),
    ),
    "E1": _NOS_V1["E1"],
    "E2": _NOS_V1["E2"],
    "E3": _NOS_V1["E3"],
    "E4": _NOS_V1["E4"],
}

RAMO_DO_NO: dict[str, str] = {no_id: no.ramo for no_id, no in NOS.items()}

HANDOFF_DO_RAMO = {"atacado": "T_HANDOFF", "private_label": "T_HANDOFF_PL",
                   "exportacao": "T_HANDOFF_ARTHUR"}
VITRINE_DO_RAMO = {"atacado": "VA", "private_label": "VP"}
DUVIDAS_DO_RAMO = {"atacado": "VD_A", "private_label": "VD_P"}

# Nós onde o lead já mostrou intenção (tocou "Quero esse", "Fazer pedido",
# "Fazer orçamento" ou "Provar antes"): só estes entram no repasse automático
# de parados (spec §8). Quem só viu a vitrine não é repassado.
NOS_COM_INTENCAO = frozenset({"QA1", "QA2", "QP1", "QP2", "VK"})

# A única regra condicional do fluxo (spec §5.2), declarada como tabela:
# (resposta do QP1, resposta do QP2) → destino. Só "criar do zero" + "menos de
# 100" não repassa; o resto vai ao João. Ausente → "T_HANDOFF_PL" (o motor).
REGRA_QP2: dict[tuple[str, str], str] = {
    ("criar_zero", "menos100"): "PL_ABAIXO",
    ("criar_zero", "de100a500"): "T_HANDOFF_PL",
    ("criar_zero", "mais500"): "T_HANDOFF_PL",
    ("tenho_marca", "menos100"): "T_HANDOFF_PL",
    ("tenho_marca", "de100a500"): "T_HANDOFF_PL",
    ("tenho_marca", "mais500"): "T_HANDOFF_PL",
}


# ─── Os terminais ────────────────────────────────────────────────────────────
#
# Os da v1 são os MESMOS objetos (§5: "copiados da v1 sem mudança"). O único
# novo é o T_KIT.
TERMINAIS: dict[str, Terminal] = {
    **{tid: _TERMINAIS_V1[tid] for tid in (
        "T_HANDOFF", "T_HANDOFF_PL", "T_HANDOFF_ARTHUR",
        "T_ADIAR", "T_ADIADO", "T_HUMANO", "T_FIM", "T_OPTOUT",
    )},
    "T_KIT": Terminal(
        id="T_KIT", rotulo_interno="Handoff · João Brás (kit amostra)",
        vendedor=VENDEDOR_ATACADO,
        # Sem preço nem composição: pendentes com o João (§4).
        # Sem emoji: regra de voz do handoff (auditoria 08/07, ver T_HANDOFF na v1).
        corpo="perfeito, já chamei o João Brás aqui pra combinar o kit com você",
        tags=(TAG_QUALIFICADO, TAG_KIT),
        silenciar_ia=True,
        handoff=True,
    ),
}
