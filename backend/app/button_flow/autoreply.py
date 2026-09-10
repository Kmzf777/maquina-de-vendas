"""Camada 1.5: o texto que chegou é robô de saudação do WhatsApp Business do lead?

Função pura, zero LLM, zero I/O. Leaf module — não importa nada de `app`, no mesmo
contrato de `app/agent/persona.py` e `app/templates/intent.py`.

── O incidente que criou este módulo ────────────────────────────────────────
No broadcast mais limpo da base (`utilidade_geral_produto_v1`, 29/07/2026, 494
entregues, 60 respostas) 36 pessoas responderam em texto livre — e **17 dessas 36
não eram pessoas**: eram a mensagem de saudação/ausência do WhatsApp Business do
próprio cliente. 28% de TODAS as respostas do disparo. Verbatim do dump
(`research/freetext.json`, todas com lag 0,0h):

    "\u200eEmpório Vilela agradece seu contato!☺️🥰 …"
    "\u200eDivina Terra João Pessoa agradece seu contato. Sou consultora …"
    "Olá! ☕ Tudo bem? Somos da Tudo Café … 🕒 Funcionamos de segunda a sexta,
     das 07:30 às 18:30 …"

Sem este filtro, o bot responde para um robô e — pior — gasta o ÚNICO nudge que
`engine.decidir` concede ao lead (`engine.py`, `marcar_nudge`): o segundo texto
livre encerra o nó e devolve ao humano. Um lead que nunca leu nada sairia do fluxo
por causa da secretária eletrônica dele.

── A regra de combinação, e por que ela é assimétrica ───────────────────────
Falso positivo é MUITO pior que falso negativo: marcar um cliente real como robô
deixa o bot mudo para ele — e um "para de me mandar isso" silenciado é opt-out não
honrado (§11 do design; hoje já há 52 casos). Por isso NENHUM sinal isolado do
tipo "palavra solta + resposta rápida" marca nada. Os falsos positivos que
derrubaram a primeira versão da regex, todos reais e todos com lag < 3 min:

    "Qual o horário de funcionamento de vcs / Quero pegar o capuccino aí"  (25,9 s)
    "na verdade quero ser esse prestador de serviço … como posso ajudar vocês…" (57,9 s)
    "Oi valeria! … Consegue sim / Agora você fala com Bianca, como posso te ajudar?" (111,6 s)
    "Sem custo uma amostra é bem vindo. Meu endereço é …"                  (164,0 s)

Cada um casa UM item da lista de sinais da §6.5 do dossiê. Nenhum é robô.

Então a regra é em dois níveis:

  ASSINATURA — sozinha basta, o lag é irrelevante:
    - marca invisível de direção (U+200E LRM ou U+200F RLM) no texto. O WhatsApp
      Business injeta uma delas na mensagem automática. Medido: 44 mensagens
      `role='user'` do banco inteiro contêm U+200E, e as 44 são saudação de
      empresa. Zero exceções.
    - "<Empresa> agradece seu contato" — 3ª pessoa do SINGULAR, o formato
      literal da saudação padrão do WhatsApp Business, em que o sujeito é o nome
      da conta e não a pessoa. "agradeço" (1ª do singular) fica DE FORA de
      propósito: quem escreve "Agradeço muito, mas não fiz nenhum pedido" é
      gente — e é justamente um ENGANO, que precisa ser respondido e não
      silenciado. "agradecemos" (1ª do plural) TAMBÉM ficou de fora — ver o
      incidente abaixo.
    - declaração explícita de mensagem automática.

  INDÍCIOS — precisa de pelo menos um do NÚCLEO (boas-vindas, horário declarado,
  promessa de retorno, menu de escolha, "como podemos ajudar", "agradecemos seu
  contato") e de lag < 3 min, salvo quando 3 sinais DE NÚCLEO diferentes
  aparecem juntos. Os três de APOIO (auto-apresentação, vitrine/catálogo,
  cortesia de balcão) nunca decidem sozinhos NEM dispensam o lag — são só voz
  formal de empresa, e descrevem tão bem um robô quanto um comprador escrevendo
  um e-mail.

── Revisão adversarial de 09/09/2026: três defeitos corrigidos ──────────────
1. "Agradecemos" (1ª do PLURAL) era tratado como ASSINATURA. Mas o plural não é
   só o robô do WhatsApp Business: é o registro corporativo em que uma PESSOA
   escreve em nome da empresa. Como assinatura ignora núcleo e ignora lag, ela
   marcava sozinha, com qualquer lag e com qualquer resto de texto:

       "Agradecemos a sua mensagem, porem por favor descadastrar meu numero."
       "Bom dia! Agradecemos a mensagem. Segue pedido: 10 un canastra suave"

   O primeiro é opt-out silenciado (LGPD + Business Messaging Policy); o segundo
   é a venda que paga o projeto. E o próprio corpus de negativos já continha
   duas mensagens VERBATIM do mesmo registro — "Boa tarde, João! Agradecemos
   pela proposta encaminhada…" e "Nossa operação com café foi encerrada.
   Agradecemos à parceria…" — que só escapavam porque o objeto direto calhou de
   ser "proposta"/"parceria" em vez de "contato"/"mensagem".
   A 1ª do plural virou INDÍCIO DE NÚCLEO. Custo medido no banco (ver abaixo):
   UM falso negativo, zero falso positivo novo.
2. O limiar somava APOIO como se fosse NÚCLEO: `len(achados) >= 3` deixava
   1 núcleo + 2 apoios marcar em QUALQUER lag, sem a trava de tempo. As
   contagens agora são separadas — só núcleo dispensa o lag.
3. A marca invisível cobria só U+200E; U+200F (RLM) passava batido.

── O que foi medido (banco de produção, 09/09/2026) ─────────────────────────
Conjunto: 11.473 mensagens `role='user'` que chegaram até 40 min depois de um
envio nosso; e o corpus inteiro de 10.977 textos distintos de `role='user'`.

  - varredura por U+200E/palavra-chave, rotulada à mão — 113 mensagens,
    107 robô e 6 gente:      TP 103 · FN 4 · **FP 0** · TN 6
  - detector sobre as 11.473: 109 marcadas (61 textos distintos); revisão manual
    das 61: **0 falsos positivos**
  - pior caso, os 10.977 textos distintos avaliados com lag = 0 s (o mais
    permissivo possível): 67 marcados, todos robô, **0 falsos positivos**
  - recall na verdade-terreno do U+200E: **44/44**

Custo do defeito 1, medido no corpus de 10.977 textos distintos: 42 textos
disparam a assinatura "agradece"; 11 casam SÓ a 1ª do plural; 10 desses 11
carregam também pelo menos um sinal de NÚCLEO e continuam marcados. Sobra UM
("Agradecemos seu contato. Esse número é exclusivo para dúvidas técnicas.") que
vira falso negativo — um nudge a mais, contra a classe inteira de opt-out e
pedido silenciados.

Custo do defeito 2: 10 textos distintos hoje alcançam o atalho "3 sinais"
com menos de 3 núcleos. Nenhum deles chegou com lag ≥ 3 min em produção
(0 ocorrências nas 11.473) — a trava fecha o buraco sem perder detecção.

Os 4 falsos negativos são indício único ("No momento estamos indisponíveis,
logo responderemos…", "Agradecemos seu contato. Esse número é exclusivo…") ou
fora da janela de 3 min ("Olá me chamo Jonatan Ugulino, em que posso ajudar?",
807 s depois do nosso envio). É o erro que se aceita: perder um robô custa um
nudge; silenciar um cliente custa a venda.

── Por que NÃO reusamos `app/agent/adherence.py::detect_autoresponder` ──────
Existe um segundo detector do mesmo fenômeno no repo. Ele fica separado de
propósito, e a medição justifica: sobre o conjunto rotulado deste arquivo ele
acerta 7 dos 24 autoresponders (17 falsos negativos, recall 29%) contra 23/24
daqui. Duas razões estruturais:

  - ele só olha a marca invisível em `texto[0]`; "Fala mestre beleza?
    \u200eJared aqui" e "Olá, sou a \u200eYandra do Villa Brownie" trazem a
    marca no MEIO e escapam;
  - ele não recebe o lag, que é justamente o que separa "Qual o horário de
    funcionamento de vcs" (cliente, 25,9 s) da placa da porta.

E os custos de erro são opostos: lá o detector audita a NOSSA saída e um falso
negativo é barato; aqui um falso positivo emudece o bot para um cliente real.
Fundir os dois obrigaria a escolher uma calibração só — e a de lá silenciaria
gente que esta aqui deixa passar. Mantê-los separados é a decisão consciente.
"""
from __future__ import annotations

import re
import unicodedata

# LEFT-TO-RIGHT MARK. Invisível, e o WhatsApp Business a injeta na mensagem
# automática. É a assinatura mais barata e mais precisa que existe aqui.
# Escrita em ESCAPE de propósito: o caractere é invisível, e um editor que
# normalize o arquivo a apagaria sem deixar rastro — `"" in texto` é True
# para qualquer texto, o que marcaria a coorte inteira como robô.
MARCA_AUTOMATICA = "\u200e"
# RIGHT-TO-LEFT MARK, o par da anterior. Revisão adversarial de 09/09/2026:
# esta versão cobria só a LRM, enquanto `app/agent/adherence.py:183`
# (`detect_autoresponder`) já cobria as DUAS para o mesmo fenômeno —
# divergência sem motivo entre dois detectores do mesmo repo. O banco hoje tem
# 28 textos distintos com LRM e ZERO com RLM, então a cobertura é preventiva e
# custa nada: um aparelho RTL do lado do lead injeta a RLM no lugar da LRM.
MARCA_AUTOMATICA_RTL = "\u200f"
MARCAS_AUTOMATICAS: tuple[str, ...] = (MARCA_AUTOMATICA, MARCA_AUTOMATICA_RTL)

# Um humano que leu o template também pode responder rápido — o lag por si só não
# separa nada (o "Qual o horário de funcionamento de vcs" acima chegou em 25,9 s).
# Ele serve só para apertar o caso de 2 indícios. 3 min é o teto do dossiê (§6.5);
# no conjunto medido, todo autoresponder pego por indício chegou em até 60 s.
LAG_MAXIMO_S = 180.0

# Abaixo disso não há texto suficiente para juntar dois indícios sem chutar.
# (A assinatura continua valendo: "\u200eZenzi," tem 7 chars e é robô.)
MINIMO_DE_TEXTO = 12

# ── Assinaturas: sozinhas bastam ────────────────────────────────────────────
# "Empório Vilela agradece seu contato" — SÓ a 3ª do SINGULAR. O sujeito é o
# nome da conta, não quem escreve: é formato de template, e ninguém fala de si
# assim. "agradeço" (1ª do singular) e "agradecemos" (1ª do plural) ficam DE
# FORA — ver `_IND_AGRADECEMOS` abaixo e o incidente 1 no cabeçalho do módulo.
_ASSINATURA_AGRADECE = re.compile(
    r"\bagradece\b[^.!?\n]{0,30}?\b(?:contato|mensagem)\b"
)
_ASSINATURA_AUTOMATICA = re.compile(
    r"\b(?:mensagem|resposta|atendimento|retorno)\s+autom[aá]tic[oa]\b"
)

# "Agradecemos seu contato" / "agradecemos sua mensagem" — 1ª do PLURAL.
# Rebaixada de ASSINATURA para indício de NÚCLEO na revisão de 09/09/2026: como
# assinatura ela ignorava núcleo e ignorava lag, e silenciava o registro
# corporativo em que uma PESSOA escreve pela empresa — "Agradecemos a sua
# mensagem, porem por favor descadastrar meu numero." (opt-out) e "Bom dia!
# Agradecemos a mensagem. Segue pedido: 10 un canastra suave" (venda). Como
# indício, ela ainda é do NÚCLEO (a mensagem automática SEMPRE recebe alguém),
# mas precisa de companhia e de lag curto. Custo medido: 1 falso negativo em
# 10.977 textos distintos.
_IND_AGRADECEMOS = re.compile(
    r"\bagradecemos\b[^.!?\n]{0,30}?\b(?:contato|mensagem)\b"
)

# ── Indícios: precisam de companhia ─────────────────────────────────────────
# "Seja bem-vindo(a) ao universo da VIVAMAIS Natural!" — boas-vindas de abertura.
# O "seja" é o que separa a saudação do uso corrente: "Material para somar será
# bem vindo" e "Sem custo uma amostra é bem vindo" são clientes reais escrevendo.
_IND_BOASVINDAS = re.compile(r"\bseja\s+(?:muito\s+)?bem[\s-]?vind")
# A forma sem "seja" só vale na ABERTURA: ou nos primeiros 15 chars ("*Bem
# vindo(a) ao Afeto Ateliê Criativo*"), ou logo depois de uma saudação ("Olá!
# Bem-vindo(a) à MJM Advocacia"). Os dois clientes reais acima escrevem "bem
# vindo" no meio da frase, a 24 e 76 chars do início — e ficam de fora.
_IND_BOASVINDAS_FRACA = re.compile(r"\bbem[\s-]?vind[oa]")
_ABERTURA_CHARS = 15
_APOS_SAUDACAO_CHARS = 60
_ABRE_COM_SAUDACAO = re.compile(
    r"^[\W\d_]{0,8}(?:ola|oi+|bom\s+dia|boa\s+(?:tarde|noite)|prezad|querid|"
    r"caro\b|sauda[cç])"
)

# Horário DECLARADO. "Qual o horário de funcionamento de vcs" também casa — por
# isso este sinal nunca decide sozinho.
_IND_HORARIO = re.compile(
    r"hor[aá]rio\s+de\s+(?:atendimento|funcionamento)|nosso\s+hor[aá]rio|"
    r"funcionamos\s+de\s+(?:segunda|ter[cç]a|domingo)|"
    r"atendemos\s+de\s+(?:segunda|ter[cç]a|domingo)|"
    r"nosso\s+atendimento\s+[eé]\s"
)

# Promessa de retorno / indisponibilidade — o miolo da mensagem de ausência.
_IND_RETORNO = re.compile(
    r"\bretornaremos\b|\bresponderemos\b|\bretornarei\b|\bcontataremos\b|"
    r"\bretornamos\s+seu\b|\batender[eê]mos\b|"
    r"assim\s+que\s+(?:pudermos|poss[ií]vel|estiver)|"
    r"n[aã]o\s+estamos\s+dispon[ií]ve|estamos\s+(?:ausentes|indispon[ií]ve)|"
    r"n[aã]o\s+podemos\s+responder|logo\s+que\s+poss[ií]vel|"
    r"o\s+mais\s+breve\s+poss[ií]vel|t[aã]o\s+logo|"
    r"em\s+instantes\s+(?:um|voc|ir)|j[aá]\s+iremos\s+atend"
)

# Menu numerado: "*1* - Ver promoções", "1️⃣ Seguros", "Digite o número".
# NÃO reconhece lista numerada crua ("1. catálogo de produtos; 2. pedido
# mínimo…"): era assim que o Wagner, dono de um empório novo pedindo tabela de
# atacado por escrito, virava robô. O sinal é a INSTRUÇÃO de escolher, não a
# numeração.
_IND_MENU = re.compile(
    r"\*\s*1\s*\*|1️⃣|"
    r"digite\s+o\s+n[uú]mero|digite\s+1\b|responda\s+com\s+o\s+n[uú]mero|"
    r"escolha\s+(?:uma\s+)?(?:das\s+)?op[cç]"
)

# Oferta genérica de ajuda — o fecho canônico da saudação do WhatsApp Business.
_IND_COMO_AJUDAR = re.compile(
    r"como\s+pode(?:mos|s)?\s+(?:te\s+|lhe\s+|voc[eê]\s+)?ajud|"
    r"como\s+posso\s+(?:te\s+|lhe\s+)?ajud|"
    r"em\s+que\s+(?:posso|podemos)\s+(?:te\s+|lhe\s+)?(?:ajudar|auxiliar)"
)

# Auto-apresentação institucional ("Olá me chamo Jonatan Ugulino, em que posso
# ajudar?", "Eu sou o Wallison e estou à disposição").
_IND_APRESENTACAO = re.compile(
    r"\bme\s+chamo\b|\bmeu\s+nome\s+[eé]\b|\bsou\s+(?:a|o|consultor)\b|"
    r"\bsomos\s+(?:a|o|d[ao])\b|\bequipe\s+d[eoa]\b"
)

# Vitrine: link de catálogo/cardápio/loja, convite a seguir no Instagram.
_IND_VITRINE = re.compile(
    r"nosso\s+(?:cat[aá]logo|card[aá]pio|site)|wa\.me/c/|loja\s+virtual|"
    r"conhe[cç]a\s+(?:nossa|nosso)|siga\s+(?:a\s+|o\s+|n[oa]s\b)"
)

# Cortesia de balcão, na voz institucional.
_IND_CORTESIA = re.compile(
    r"(?:fico|ficamos|estou|estamos)\s+[aà]\s+(?:sua\s+)?disposi[cç]|"
    r"sinta-se\s+[aà]\s+vontade|"
    r"[eé]\s+um\s+prazer\s+(?:te|lhe|falar|atend)|prazer\s+em\s+(?:te|lhe)\s+atend|"
    r"agradecemos\s+(?:a\s+)?(?:sua\s+)?prefer|obrigad[oa]\s+por\s+(?:ter\s+)?entrar"
)

_INDICIOS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("agradecemos_contato", _IND_AGRADECEMOS),
    ("horario", _IND_HORARIO),
    ("retorno", _IND_RETORNO),
    ("menu", _IND_MENU),
    ("como_ajudar", _IND_COMO_AJUDAR),
    ("apresentacao", _IND_APRESENTACAO),
    ("vitrine", _IND_VITRINE),
    ("cortesia", _IND_CORTESIA),
)

# Indícios que só a mensagem automática tem: ela SEMPRE recebe alguém — dá boas-
# vindas, declara horário, promete retorno, oferece menu, agradece o contato em
# nome da casa ou pergunta como ajudar.
# Os outros três (apresentação, vitrine, cortesia) são apenas voz formal de
# empresa, e sozinhos descrevem tão bem um robô quanto uma pessoa escrevendo:
#
#   "Meu nome é Viviane Naves / Sou da FLEX MOBILY MÓVEIS … Ficamos à disposição"
#   "Meu nome é Emillyane Burdzik e faço parte da equipe comercial da VALIA …"
#   "Meu nome é Wagner e serei proprietário da Loja Recanto de Minas … fico à
#    disposição para uma breve conversa"
#
# Os três são gente de carne e osso — e o último é um comprador pedindo tabela de
# atacado. Por isso NENHUMA combinação só de apoio marca autoresponder.
NUCLEO: frozenset[str] = frozenset(
    {"boas_vindas", "horario", "retorno", "menu", "como_ajudar",
     "agradecemos_contato"}
)

# O complemento explícito, para o limiar poder contá-los separado. Antes da
# revisão de 09/09/2026 o limiar fazia `quantos = len(achados)` e somava apoio
# com núcleo: 1 núcleo + 2 apoios dava 3 e dispensava a trava de lag. Um
# "Sinta-se à vontade na loja X … como podemos ajudar? … siga no Instagram"
# marcava chegando 6 horas depois — e um prospector B2B escrevendo devagar tem
# exatamente essa forma.
APOIO: frozenset[str] = frozenset({"apresentacao", "vitrine", "cortesia"})

# Só 3 sinais DE NÚCLEO diferentes dispensam o lag. No corpus são 2 os textos
# que chegam aí sem assinatura, e os dois são placa de porta de empresa.
NUCLEOS_QUE_DISPENSAM_LAG = 3


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento, espaços colapsados. Mantém a quebra de linha.

    A quebra sobrevive porque a saudação automática é quase sempre multilinha, e
    a abertura ("Olá! / Seja bem-vindo…") só é reconhecível como abertura
    enquanto a primeira linha continuar sendo a primeira linha.
    """
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    # As marcas de direção (U+200E/U+200F) e U+200B (zero-width space, que
    # aparece colado em texto vindo de editor web) viram espaço: colados numa
    # palavra, eles quebrariam o limite de palavra das regex sem rastro na tela.
    for marca in (*MARCAS_AUTOMATICAS, "\u200b"):
        sem_acento = sem_acento.replace(marca, " ")
    return re.sub(r"[^\S\n]+", " ", sem_acento).strip().lower()


def _e_boas_vindas(normalizado: str) -> bool:
    """Saudação de boas-vindas de ABERTURA — não o adjetivo solto no meio da frase."""
    if _IND_BOASVINDAS.search(normalizado):
        return True
    achado = _IND_BOASVINDAS_FRACA.search(normalizado)
    if achado is None:
        return False
    if achado.start() < _ABERTURA_CHARS:
        return True
    return (
        _ABRE_COM_SAUDACAO.search(normalizado) is not None
        and achado.start() < _APOS_SAUDACAO_CHARS
    )


def sinais(texto: str) -> tuple[str, ...]:
    """Nomes dos sinais que dispararam. Existe para o log e para o teste.

    Devolver a lista (em vez de só o booleano) é o que permite a um incidente em
    produção dizer QUAL regra silenciou o lead — sem isso, depurar um falso
    positivo exigiria reconstruir o texto original a partir do banco.
    """
    if not texto:
        return ()

    achados: list[str] = []
    if any(marca in texto for marca in MARCAS_AUTOMATICAS):
        achados.append("marca_invisivel")

    normalizado = _normalizar(texto)
    if _ASSINATURA_AGRADECE.search(normalizado):
        achados.append("agradece_contato")
    if _ASSINATURA_AUTOMATICA.search(normalizado):
        achados.append("declara_automatica")

    if len(normalizado) >= MINIMO_DE_TEXTO:
        if _e_boas_vindas(normalizado):
            achados.append("boas_vindas")
        for nome, padrao in _INDICIOS:
            if padrao.search(normalizado):
                achados.append(nome)

    return tuple(achados)


ASSINATURAS: frozenset[str] = frozenset(
    {"marca_invisivel", "agradece_contato", "declara_automatica"}
)


def parece_autoresponder(
    texto: str, *, segundos_desde_nosso_envio: float | None
) -> bool:
    """True quando o texto é a saudação/ausência automática do WhatsApp do lead.

    Chamado ANTES do classificador (camada 2) e antes de qualquer nudge: quando
    devolve True o runner não responde, não gasta o nudge e mantém o lead
    elegível ao toque D+4 — ele nunca leu nada.

    `segundos_desde_nosso_envio` é o intervalo entre a NOSSA última saída e esta
    mensagem. `None` significa desconhecido (não há envio nosso registrado, ou o
    runner não conseguiu apurar) e é tratado como o caso severo: sem assinatura,
    só marca com 3 sinais DE NÚCLEO. Nunca use o lag sozinho — "Qual o horário
    de funcionamento de vcs" chegou 25,9 s depois do nosso envio e é um cliente
    querendo comprar.

    A ordem das guardas é a ordem do custo: assinatura decide sozinha; sem
    núcleo nunca marca; e o apoio (`APOIO`) só completa a contagem, jamais
    dispensa o lag — ver a revisão de 09/09/2026 no cabeçalho do módulo.
    """
    achados = sinais(texto)
    if not achados:
        return False
    if ASSINATURAS.intersection(achados):
        return True

    # As contagens são SEPARADAS de propósito (revisão de 09/09/2026). A versão
    # anterior fazia `quantos = len(achados)` e deixava 1 núcleo + 2 apoios
    # atingir o limiar de 3, dispensando a trava de lag — e apoio (apresentação,
    # vitrine, cortesia) descreve um prospector B2B tão bem quanto um robô.
    nucleos = NUCLEO.intersection(achados)
    if not nucleos:
        return False
    if len(nucleos) >= NUCLEOS_QUE_DISPENSAM_LAG:
        return True

    # Abaixo disso o apoio só soma para chegar a dois sinais; quem paga a conta
    # é o lag. Lag negativo (relógio torto) não vale como rapidez, e `None`
    # (não sabemos) também não — afrouxar onde há menos informação é o oposto do
    # que este detector precisa fazer.
    lag_curto = (
        segundos_desde_nosso_envio is not None
        and 0 <= segundos_desde_nosso_envio < LAG_MAXIMO_S
    )
    return lag_curto and len(achados) >= 2
