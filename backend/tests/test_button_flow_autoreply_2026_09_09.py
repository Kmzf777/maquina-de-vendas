"""Camada 1.5 do bot de botões: o detector de autoresponder (app/button_flow/autoreply.py).

Todo texto aqui é VERBATIM do banco de produção, extraído em 09/09/2026 da tabela
`messages` (`role='user'`), com o lag real desde a nossa saída anterior. Nada foi
inventado nem editado — nem a pontuação, nem os emojis, nem o U+200E invisível.

Por que este arquivo existe:

  - 17 das 36 respostas em texto livre do broadcast de 29/07/2026 eram a saudação
    automática do WhatsApp Business do próprio cliente (28% de TODAS as respostas
    do disparo). Responder isso é robô conversando com robô, e gasta o único nudge
    que `app/button_flow/engine.py` concede ao lead — `Decisao.marcar_nudge`:
    o segundo texto livre encerra o nó e devolve ao humano.

  - E o erro caro é o contrário. A primeira versão da regra era a lista de sinais
    da §6.5 do dossiê aplicada em OU ("lag < 3 min E (U+200E OU palavra-chave)").
    Contra o banco, ela silenciava seis clientes de carne e osso — todos em
    `test_os_seis_humanos_que_derrubaram_a_primeira_regra`. Um deles queria um
    capuccino; outro, tabela de atacado para um empório novo.

O conjunto rotulado à mão (113 mensagens da varredura por U+200E/palavra-chave,
107 robô e 6 gente) mede TP 104 · FN 3 · FP 0 · TN 6. Sobre as 11.556 mensagens
que chegaram até 40 min depois de um envio nosso, 111 são marcadas e a revisão
manual dos 62 textos distintos não achou nenhum falso positivo.
"""
import pytest

from app.button_flow import autoreply
from app.button_flow.autoreply import parece_autoresponder, sinais

# ── POSITIVOS: 24 autoresponders reais, com o lag real ──────────────────────
# Cada tupla é (texto verbatim, segundos desde a NOSSA saída anterior).
AUTORESPONDERS_REAIS: list[tuple[str, float]] = [
    (
        "\u200eEmpório Vilela agradece seu contato!☺️🥰\n\nContato de nossas "
        "unidades:\n\nLoja Fazendinha: 1194580-6226\nLoja Polvilho: 1194540-6996\n"
        "Loja Portal dos Ipes: 1198937-4541\n\nPedidos para entrega a partir de 50 "
        "reais mais taxa!\n\nEntregas de segunda a sábado!\n\n\n"
        "NÃO ATENDEMOS LIGAÇÕES ⚠️",
        6.3,
    ),
    (
        "\u200eDivina Terra João Pessoa agradece seu contato. Sou consultora da "
        "Divina Terra JP, como posso te ajudar hoje?🤩",
        19.9,
    ),
    ("\u200eIG Celular agradece seu contato. Como posso ajuda? 😄", 8.9),
    ("\u200eFazenda Store agradece seu contato. Como podemos ajudar?", 18.3),
    ("\u200eJ.L Construçao agradece seu contato. Como podemos ajudar?", 17.7),
    (
        "\u200eLaza Biotecnologia agradece seu contato. Lhe retornaremos o mais "
        "breve possível.",
        23.1,
    ),
    # A saudação mais curta do banco: sete caracteres e uma vírgula. Só o U+200E
    # a denuncia — nenhuma palavra-chave existe aqui.
    ("\u200eZenzi,", 19.2),
    ("Fala mestre  beleza? \u200eJared aqui,  Como posso ajudar?", 26.4),
    (
        "Olá, sou a \u200eYandra do Villa Brownie e agradeço seu contato. Como "
        "podemos ajudar?",
        25.5,
    ),
    (
        "Agradecemos sua mensagem. Não estamos disponíveis no momento, mas "
        "responderemos assim que possível.",
        8.4,
    ),
    (
        "Olá Divino(a), tudo bem? 🫶🏻🤩\nAgradecemos o seu contato. Assim que "
        "pudermos, realizaremos o seu atendimento! 😊",
        19.1,
    ),
    ("Augusta Café agradece o contato e assim que possível retornaremos", 21.7),
    (
        "Nobre Imóveis Gramado agradece seu contato. Em instantes um de nossos "
        "especialistas ira lhe atender!",
        21.8,
    ),
    ("Adriana Wachholz agradece seu contato. Como podemos ajudar?", 213.4),
    ("Café Grãos da Fazenda agradece seu contato. Como podemos ajudar?☕🌿", 28.2),
    (
        "*Mensagem automática:* Olá, no momento não estou disponível. Retorno "
        "assim que possível. Obrigada pelo seu contato.",
        0.0,
    ),
    # Daqui para baixo, nenhuma assinatura: só indícios combinados.
    (
        "Olá, seja bem-vindo à Capim Santo! 💚\nRetornaremos sua mensagem assim que "
        "possível.\nEnquanto isso, gostaria de compartilhar comigo o que você "
        "precisa?",
        5.8,
    ),
    (
        "Olá! ☕ Tudo bem?\nSomos da Tudo Café, é um prazer te atender 😊\n\n"
        "🕒 Funcionamos de segunda a sexta, das 07:30 às 18:30\n\n🚚 Entregas:\n"
        "Aproveite! Em pedidos a partir de R$ 20,00, a entrega é GRÁTIS 🎉\n"
        "(Abaixo desse valor, taxa fixa de R$ 5,00)\n\n📋 Me conta: você gostaria "
        "de ver nosso cardápio\nou já sabe o que vai pedir? 😄\n\n"
        "💳 Pagamento via Pix:\nChave (CNPJ): 49.887.973/0001-83\n"
        "Nome: Carvalho e Andrade Comércio e Serviços\n\n👉 Dica: aproveite a "
        "entrega grátis e peça um combo com café + acompanhamento ☕🥐\n\n"
        "Fico à disposição!",
        8.1,
    ),
    (
        "Olá, bem vinda(o) à N'Ativa! 💚\nPor favor, escolha sobre qual assunto "
        "deseja falar:\n\n*1* - Ver promoções\n*2* - Falar com atendimento\n\n"
        "Digite o número que você deseja. ☺️",
        20.3,
    ),
    (
        "Olá! 😊\nSeja bem-vindo(a) ao universo da VIVAMAIS Natural!\nÉ um prazer "
        "falar com você e saber do seu interesse em nossa franquia. 🌿\n\nPra te "
        "atender melhor, você pode me responder rapidinho?\n\n1️⃣ Qual sua cidade "
        "e estado?\n2️⃣ Já tem experiência com negócios ou no ramo da saúde?",
        7.2,
    ),
    (
        "Olá me chamo Jonatan Ugulino, em que posso ajudar?",
        11.1,
    ),
    (
        "Olá! Sinta-se à vontade na DriCafé, a sua loja de acessórios e cafés "
        "especiais. Como podemos te ajudar?\n\n👉 Aproveita e já siga a DriCafé no "
        "Instagram: instagram.com/dricafebsb",
        18.7,
    ),
    (
        "Olá, tudo bem? \n\nEsperamos que sim! \n\nMuito prazer, meu nome é "
        "Gabriela, sou consultora da GM Soluções Ambientais e farei seu "
        "atendimento. Deixe sua mensagem, assim que estiver disponível, darei um "
        "retorno 🌱",
        6.4,
    ),
]

# ── NEGATIVOS: 24 mensagens de gente de verdade, com o lag real ─────────────
# A metade de cima é o que o fluxo PRECISA responder — SAIR, ENGANO, ADIAR,
# QUENTE. Um falso positivo aqui deixa o bot mudo e um opt-out por honrar.
HUMANOS_REAIS: list[tuple[str, float]] = [
    # Os seis que derrubaram a primeira versão da regra: todos com lag < 3 min e
    # todos casando um item da lista de sinais da §6.5.
    ("Qual o horário de funcionamento de vcs\nQuero pegar o capuccino aí", 25.9),
    ("Vou te mostrar onde moro. Quando vier pra essas bandas serás bem vinda.", 45.1),
    (
        "na verdade quero ser esse prestador de serviço no comercio exterior, como "
        "posso ajudar vocês....\n\nFazendo toda a parte que envolve o transporte "
        "dessa carga de *ponta a ponta*\ndocumentação, seguro...\ntudo",
        57.9,
    ),
    (
        "Oi valeria! Tudo bem?\nConsegue sim\nAgora você fala com Bianca, como posso "
        "te ajudar?",
        111.6,
    ),
    (
        "Vc teria mais algum complemento sobre o q solicitei\nMaterial para somar "
        "será bem vindo",
        130.9,
    ),
    (
        "Sem custo  uma amostra  é  bem vindo.  Meu  endereço  é  rua pequi quadra  "
        "20 lote 05 bairro Rodrigues.  Santa  Helena  de Goiás  Goiás  CEP "
        "75920-000 Nivaldo Figueiredo de Matos",
        164.0,
    ),
    # Voz formal de empresa — mas é gente escrevendo. O Wagner é um comprador
    # pedindo tabela de atacado; silenciá-lo custaria o melhor lead do lote.
    (
        "Assunto: Parceria Comercial | Cotação para Revenda - [Recanto de Minas]\n"
        "Olá, Bom dia João.\nEspero encontrá-lo bem.\nMeu nome é Wagner e serei "
        "proprietário da Loja Recanto de Minas, um novo empório de produtos "
        "mineiros a ser elaborado (projeto) e definido para a região da Baixada "
        "Santista (a cidade ainda será definida). Acompanho o trabalho de vocês e "
        "admiro a qualidade dos seus Produtos, por isso gostaria de tê-los como "
        "fornecedores em nossa vitrine.\nEstamos em fase de elaboração do projeto "
        "e montagem de estoque e gostaria de solicitar:\n\n1.\tCatálogo de Produtos "
        "atualizado com preços para revenda (atacado);\n2.\tQuantidade mínima por "
        "pedido (faturamento mínimo);\n3.\tPrazos de entrega e valor do frete para "
        "o CEP 11000-000 (usando CEP de Santos como referência);\n4.\tInformações "
        "sobre o selo de inspeção (SIM, SIF, SISBI e SELO ARTE).\n5.\tCondições de "
        "pagamento (boleto, cartão, prazo);\n\nFico à disposição para uma breve "
        "conversa por telefone ou whatsapp, caso prefiram.\n\nAtenciosamente,\n"
        "Wagner Andare Payao",
        138.8,
    ),
    (
        "Prezado Senhor João,\n\nEspero que esta mensagem a encontre bem.\n\nMeu "
        "nome é Emillyane Burdzik e faço parte da equipe comercial da *VALIA Brazil "
        "Importação & Exportação Ltda* .\n\nA VALIA é uma empresa especializada no "
        "desenvolvimento de mercados internacionais e na coordenação de projetos de "
        "exportação para fabricantes brasileiros.",
        0.5,
    ),
    (
        "Olá! Tudo bem?\n\nMeu nome é Vanderson Cardoso e atuo como Diretor "
        "Comercial.\n\nEstamos expandindo nossa atuação no mercado internacional e "
        "buscamos parcerias com produtores e empresas comprometidos com a qualidade "
        "do café brasileiro.\n\nPoderia, por gentileza, me informar quem é o "
        "responsável pelo setor comercial ou de exportação para darmos continuidade "
        "à conversa?\n\nFico à disposição.\n\nVanderson Cardoso\nDiretor Comercial",
        13.4,
    ),
    (
        "Meu nome é Viviane Naves\n\nSou da FLEX MOBILY MÓVEIS, empresa de "
        "Goiânia/GO especialista em venda de Mobiliário Corporativo, de 02 (duas) "
        "marcas CONCEITUADAS no mercado:\n\nCAVALETTI - Cadeiras, Poltronas, "
        "Longarinas, Cadeiras Caixas, Sofás, entre outros;",
        62.2,
    ),
    # SAIR — silenciar qualquer um destes é opt-out não honrado (já há 52 no banco).
    ("Boa tarde\nNao tenho interesse", 360.0),
    ("Boa tarde, por favor descadastrar meu número. Eu vendi a Duo Gelatto Nerópolis", 90.0),
    (
        "[audio transcrito: Oi, meu amigo, beleza? Meu, eu nunca comprei esse café, "
        "não tenho interesse não, tá bom? Obrigado.]\nNao tenho interesse",
        1080.0,
    ),
    # ENGANO — o pretexto do template foi contestado; o script tem que abortar.
    ("Boa noite! \n\nAgradeço muito, mas não fiz nenhum pedido. Só tenho que agradecer.", 45.0),
    ("Olá,  eu não fiz nenhum pedido. Acredito que seja um equívoco.", 5040.0),
    (
        "Oi João, tu me atende em outro whatsapp. Mas no momento não fiz nenhum "
        "pedido. Acho q há uma confusão aí.",
        720.0,
    ),
    ("Oi bom dia. Acho que vocês estão me confundindo\nNão fiz nenhum pedido nunca", 60.0),
    (
        "Boa tarde, tudo bem?\nEsse número não pertence mais a Divina Terra Atibaia, "
        "essa Unidade fechou",
        6120.0,
    ),
    (
        "Nossa operação com café foi encerrada. Agradecemos à parceria neste tempo "
        "do nosso MVP.",
        30.0,
    ),
    # ADIAR / QUENTE — os dois desfechos que pagam o projeto.
    ("Boa tarde João, por essa semana ainda está ok o estoque", 1441.7),
    ("Quero não\nTou pagando 44 kg\nAqui em Maringá", 210.2),
    (
        "João tudo bem ?\nQuero voltar a parceira \nMe envia as amostras para enviar "
        "para dar para meus clientes dos ovos",
        290.0,
    ),
    (
        "Pedido divina terra Plaza \nCnpj 15-737-471-0002-35\n\nCafé canastra suave "
        "250gr em pó 10 uni\nCafé canastra em pó c/canela 8 uni\nCafé canastra suave "
        "em pó 500 gr 8 uni\nCafé canastra em grão de 1 kg 12 \nCafé canastra granel "
        "pacote de 2 kg 30 kg\nBom dia\nSegue pedido",
        30.0,
    ),
    (
        "Boa tarde, João!\nAgradecemos pela proposta encaminhada. Neste momento, não "
        "daremos continuidade ao processo de compra. Certamente teremos novas "
        "oportunidades.",
        120.0,
    ),
]


@pytest.mark.parametrize("texto,lag", AUTORESPONDERS_REAIS)
def test_autoresponder_real_e_detectado(texto: str, lag: float):
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=lag) is True, (
        f"sinais apurados: {sinais(texto)}"
    )


@pytest.mark.parametrize("texto,lag", HUMANOS_REAIS)
def test_cliente_real_nunca_e_marcado_como_robo(texto: str, lag: float):
    """Falso positivo deixa o bot MUDO para um cliente de verdade.

    É o modo de falha caro: silenciar um "descadastrar meu número" é opt-out não
    honrado (LGPD + Business Messaging Policy), e silenciar um "Segue pedido" é
    perder a venda que justifica o projeto inteiro.
    """
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=lag) is False, (
        f"sinais apurados: {sinais(texto)}"
    )


def test_o_conjunto_de_calibracao_tem_tamanho_util():
    """Guarda contra alguém "consertar" a regra apagando os casos que a incomodam."""
    assert len(AUTORESPONDERS_REAIS) >= 15
    assert len(HUMANOS_REAIS) >= 15


def test_os_seis_humanos_que_derrubaram_a_primeira_regra():
    """Cada um casa UM sinal da §6.5 e tem lag < 3 min. Nenhum é robô.

    Foi este conjunto que forçou a regra de combinação: nem "lag curto" nem
    "uma palavra da lista" bastam, e os indícios de apoio (apresentação, vitrine,
    cortesia) nunca decidem sozinhos.
    """
    for texto, lag in HUMANOS_REAIS[:6]:
        assert lag < autoreply.LAG_MAXIMO_S
        assert sinais(texto) != () or "bem vind" in texto.lower(), (
            "o caso perdeu a graça: já não casa nenhum sinal da lista original"
        )
        assert parece_autoresponder(texto, segundos_desde_nosso_envio=lag) is False


# ── Comportamento da regra de combinação ────────────────────────────────────
def test_a_marca_automatica_e_exatamente_u200e():
    """Guarda contra o modo de falha silencioso mais burro possível.

    A constante é um caractere INVISÍVEL. Um editor que normalize o arquivo, ou
    um copiar-colar por um terminal, pode apagá-la sem deixar rastro — e
    `"" in texto` é True para qualquer texto, o que faria o detector marcar TODA
    mensagem como robô e o bot emudecer para a coorte inteira. Por isso o arquivo
    escreve `"\\u200e"` em escape, e este teste checa o valor.
    """
    assert autoreply.MARCA_AUTOMATICA == "\u200e"
    assert len(autoreply.MARCA_AUTOMATICA) == 1
    assert parece_autoresponder("bom dia", segundos_desde_nosso_envio=1.0) is False


def test_marca_invisivel_do_whatsapp_business_basta_sozinha():
    """U+200E é assinatura, não indício: vale sem lag e sem palavra-chave.

    Verdade-terreno: as 44 mensagens `role='user'` do banco que contêm U+200E são,
    todas as 44, saudação automática de empresa.
    """
    texto = f"{autoreply.MARCA_AUTOMATICA}Zenzi,"
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=None) is True
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=86_400.0) is True
    assert sinais(texto) == ("marca_invisivel",)


def test_agradece_em_terceira_pessoa_e_assinatura_mas_agradeco_nao():
    """"X agradece seu contato" é o formato da saudação padrão do WhatsApp Business.

    "Agradeço muito, mas não fiz nenhum pedido" é uma pessoa contestando o
    pretexto do template — classe ENGANO. A diferença entre silenciar um robô e
    silenciar um cliente cabe numa conjugação verbal, e por isso a assinatura só
    aceita 3ª do singular e 1ª do plural.
    """
    robo = "Adriana Wachholz agradece seu contato. Como podemos ajudar?"
    gente = "Boa noite! \n\nAgradeço muito, mas não fiz nenhum pedido. Só tenho que agradecer."
    assert "agradece_contato" in sinais(robo)
    assert "agradece_contato" not in sinais(gente)
    assert parece_autoresponder(robo, segundos_desde_nosso_envio=None) is True
    assert parece_autoresponder(gente, segundos_desde_nosso_envio=1.0) is False


def test_indicios_so_de_apoio_nunca_marcam():
    """Apresentação + cortesia é voz formal de empresa — humano ou robô.

    Sem esta trava, os três prospectores B2B reais do conjunto (VALIA, Vanderson,
    Viviane) e o comprador do empório Recanto de Minas viravam autoresponder.
    """
    texto = (
        "Meu nome é Viviane Naves\n\nSou da FLEX MOBILY MÓVEIS, empresa de "
        "Goiânia/GO especialista em venda de Mobiliário Corporativo.\n\n"
        "Ficamos à disposição."
    )
    apurados = set(sinais(texto))
    assert apurados == {"apresentacao", "cortesia"}
    assert not apurados & set(autoreply.NUCLEO)
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=0.0) is False


def test_dois_indicios_exigem_lag_curto():
    """Com 2 indícios o lag é o desempate; com 3 ele deixa de ser necessário.

    "Olá me chamo Jonatan Ugulino, em que posso ajudar?" é o mesmo texto nas duas
    chamadas — o que muda é só quanto tempo depois da nossa mensagem ele chegou.
    Chegou 13 min depois? Provavelmente alguém digitou. É um falso negativo
    assumido: custa um nudge, não uma venda.
    """
    texto = "Olá me chamo Jonatan Ugulino, em que posso ajudar?"
    assert set(sinais(texto)) == {"como_ajudar", "apresentacao"}
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=11.1) is True
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=807.1) is False
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=None) is False


def test_lag_desconhecido_cai_no_criterio_severo():
    """`None` = não sabemos. Trata como o pior caso, nunca como "lag curto".

    O runner passa None quando não há saída nossa registrada na conversa. Deixar
    None equivaler a 0 s afrouxaria a regra exatamente onde há menos informação.
    """
    dois_indicios = (
        "Olá, seja bem-vindo à Capim Santo! 💚\nRetornaremos sua mensagem assim que "
        "possível.\nEnquanto isso, gostaria de compartilhar comigo o que você precisa?"
    )
    assert len(sinais(dois_indicios)) == 2
    assert parece_autoresponder(dois_indicios, segundos_desde_nosso_envio=5.8) is True
    assert parece_autoresponder(dois_indicios, segundos_desde_nosso_envio=None) is False


def test_lag_negativo_nao_conta_como_lag_curto():
    """Relógio torto (webhook antes do nosso INSERT) não pode virar evidência.

    O lag vem de uma subtração entre dois timestamps de origens diferentes; um
    valor negativo é sintoma de que a apuração falhou, não prova de rapidez.
    """
    texto = (
        "Olá, seja bem-vindo à Capim Santo! 💚\nRetornaremos sua mensagem assim que "
        "possível.\nEnquanto isso, gostaria de compartilhar comigo o que você precisa?"
    )
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=-2.0) is False


def test_pergunta_sobre_horario_nao_e_declaracao_de_horario():
    """O sinal mais perigoso da lista da §6.5, no par mínimo.

    Os dois textos contêm "horário de funcionamento"; um é um cliente querendo um
    capuccino e o outro é a placa da porta. É por isso que `horario` nunca decide
    sozinho.
    """
    cliente = "Qual o horário de funcionamento de vcs\nQuero pegar o capuccino aí"
    placa = (
        "Olá, tudo bem? Seja bem vindo ao Empório Minas.\nComo posso ajudar?\n\n"
        "📲 Esse é o link do nosso catálogo:\n"
        "https://emporio-minas-2.ola.click/products\n\n"
        "⏰️ Horário de funcionamento: segunda à sábado das 9h às 19h"
    )
    assert "horario" in sinais(cliente)
    assert "horario" in sinais(placa)
    assert parece_autoresponder(cliente, segundos_desde_nosso_envio=25.9) is False
    assert parece_autoresponder(placa, segundos_desde_nosso_envio=7.9) is True


def test_bem_vindo_so_conta_na_abertura():
    """"seja bem-vindo" é saudação; "é bem vindo" no meio da frase é adjetivo.

    Os dois clientes reais que escreveram "bem vindo" (a 24 e a 76 chars do
    início da mensagem) estavam ACEITANDO uma amostra — o oposto de um robô.
    """
    saudacao = "*Bem vindo(a) ao Afeto Ateliê Criativo*\n\nVisite nosso site"
    adjetivo = (
        "Vc teria mais algum complemento sobre o q solicitei\nMaterial para somar "
        "será bem vindo"
    )
    assert "boas_vindas" in sinais(saudacao)
    assert "boas_vindas" not in sinais(adjetivo)


def test_lista_numerada_de_pedido_nao_e_menu():
    """Menu é a INSTRUÇÃO de escolher, não a numeração.

    O Wagner (empório Recanto de Minas) pediu 5 itens numerados de uma tabela de
    atacado. A regra anterior lia isso como menu de robô e o teria silenciado.
    """
    pedido = (
        "gostaria de solicitar:\n\n1.\tCatálogo de Produtos atualizado;\n"
        "2.\tQuantidade mínima por pedido;\n3.\tPrazos de entrega;"
    )
    menu = "*1* - Ver promoções\n*2* - Falar com atendimento\n\nDigite o número que você deseja."
    assert "menu" not in sinais(pedido)
    assert "menu" in sinais(menu)


def test_texto_vazio_ou_curto_nunca_junta_indicio():
    """Sem texto não há evidência — e "sem evidência" é False, nunca True."""
    assert parece_autoresponder("", segundos_desde_nosso_envio=1.0) is False
    assert parece_autoresponder("Bom dia", segundos_desde_nosso_envio=1.0) is False
    assert parece_autoresponder("ok", segundos_desde_nosso_envio=0.0) is False
    assert sinais("") == ()


def test_normalizacao_ignora_acento_caixa_e_marca_invisivel():
    """O mesmo texto tem que ser lido igual com e sem acento.

    Precedente do repo: há 64 cliques gravados em "Nao tenho interesse" e ZERO em
    "Não tenho interesse" (`app/button_flow/engine.py`, `normalizar`). O teclado
    do lead, e o próprio WhatsApp, comem acento.
    """
    com_acento = "HORÁRIO DE ATENDIMENTO"
    sem_acento = "horario de atendimento"
    assert autoreply._normalizar(com_acento) == sem_acento
    assert "horario" in sinais(com_acento)
    assert "horario" in sinais(sem_acento)
    # A marca invisível vira espaço na normalização, para não colar em palavra.
    assert autoreply._normalizar(f"{autoreply.MARCA_AUTOMATICA}Zenzi,") == "zenzi,"


def test_e_funcao_pura_sem_dependencia_de_app():
    """Leaf module: se ele importar orquestrador, vira impossível testar sem mock.

    Mesmo contrato de `app/agent/persona.py` e `app/templates/intent.py`. O núcleo
    de decisão do fluxo de botões inteiro depende de rodar igual em produção e no
    teste, sem banco e sem relógio.
    """
    import inspect

    fonte = inspect.getsource(autoreply)
    assert "from app." not in fonte
    assert "import app" not in fonte


# ── Revisão adversarial de 09/09/2026 ──────────────────────────────────────
# Três defeitos do detector, cada um com o repro que o revisor confirmou.
# Ao contrário do resto do arquivo, as duas primeiras frases de
# `REPROS_DO_PLURAL` foram ESCRITAS pelo revisor (não são verbatim do banco):
# são o registro corporativo do banco costurado com o desfecho que o fluxo mais
# precisa ouvir — SAIR e pedido. As duas últimas são verbatim, e já estavam em
# `HUMANOS_REAIS`: só escapavam porque o objeto direto calhou de ser
# "proposta"/"parceria" em vez de "contato"/"mensagem".
REPROS_DO_PLURAL: list[tuple[str, float]] = [
    ("Agradecemos a sua mensagem, porem por favor descadastrar meu numero.", 60.0),
    ("Bom dia! Agradecemos a mensagem. Segue pedido: 10 un canastra suave", 18.0),
    (
        "Boa tarde, João!\nAgradecemos pela proposta encaminhada. Neste momento, não "
        "daremos continuidade ao processo de compra. Certamente teremos novas "
        "oportunidades.",
        120.0,
    ),
    (
        "Nossa operação com café foi encerrada. Agradecemos à parceria neste tempo "
        "do nosso MVP.",
        30.0,
    ),
]


@pytest.mark.parametrize("texto,lag", REPROS_DO_PLURAL)
def test_agradecemos_no_plural_nao_silencia_cliente_real(texto: str, lag: float):
    """"Agradecemos o contato" também é gente escrevendo em nome da empresa.

    A versão original aceitava a 1ª do PLURAL como ASSINATURA
    (`_ASSINATURA_AGRADECE`, `r"\\bagradec(?:e|emos)\\b"`), e assinatura ignora
    núcleo, ignora lag e ignora o resto do texto — marcava sozinha. Os dois
    primeiros repros são o custo exato: um opt-out silenciado (LGPD + Business
    Messaging Policy; o banco já tem 52 opt-outs) e um pedido de 10 unidades
    silenciado, que é a venda que paga o projeto.
    """
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=lag) is False, (
        f"sinais apurados: {sinais(texto)}"
    )


def test_plural_e_indicio_de_nucleo_e_singular_continua_assinatura():
    """A 3ª do singular é formato de template; a 1ª do plural é registro formal.

    "Adriana Wachholz agradece seu contato" tem por sujeito o NOME DA CONTA —
    ninguém fala de si assim, e por isso continua bastando sozinha. Já
    "Agradecemos sua mensagem" é só primeira pessoa do plural: precisa de
    companhia e de lag curto como qualquer outro indício de núcleo.
    """
    assert "agradecemos_contato" in autoreply.NUCLEO
    assert "agradecemos_contato" not in autoreply.ASSINATURAS
    assert "agradece_contato" in autoreply.ASSINATURAS

    singular = "Adriana Wachholz agradece seu contato. Como podemos ajudar?"
    plural = (
        "Agradecemos sua mensagem. Não estamos disponíveis no momento, mas "
        "responderemos assim que possível."
    )
    assert "agradece_contato" in sinais(singular)
    assert "agradece_contato" not in sinais(plural)
    assert "agradecemos_contato" in sinais(plural)
    # O singular não depende do lag; o plural depende.
    assert parece_autoresponder(singular, segundos_desde_nosso_envio=86_400.0) is True
    assert parece_autoresponder(plural, segundos_desde_nosso_envio=8.4) is True
    assert parece_autoresponder(plural, segundos_desde_nosso_envio=86_400.0) is False


def test_o_unico_falso_negativo_que_o_conserto_do_plural_custou():
    """O preço do conserto, escrito por extenso para ninguém redescobrir na mão.

    Medição sobre os 10.977 textos distintos de `role='user'` (banco de produção,
    09/09/2026): 42 disparam a assinatura "agradece"; 11 casam SÓ a 1ª do plural;
    10 desses 11 carregam também um sinal de NÚCLEO e seguem marcados. Sobra este
    — e ele custa um nudge, contra a classe inteira de opt-out silenciado.
    """
    texto = (
        "Agradecemos seu contato.\n\nEsse número é exclusivo para dúvidas "
        "técnicas.\n\nPara agendamentos, visitas ou orçamentoa contatar 54 981464781"
    )
    assert sinais(texto) == ("agradecemos_contato",)
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=16.7) is False


def test_apoio_somado_nunca_dispensa_a_trava_de_lag():
    """1 núcleo + 2 apoios chegava a `len(achados) >= 3` e marcava em QUALQUER lag.

    O limiar antigo fazia `quantos = len(achados)` sobre a lista inteira. Este
    texto é verbatim do banco (DriCafé) e tem exatamente essa forma: um núcleo
    ("como podemos te ajudar") e dois apoios (cortesia, vitrine). Chegando 18,7 s
    depois da nossa mensagem ele é robô e deve ser marcado; chegando seis horas
    depois, a única evidência que sobra é voz formal de empresa — e um prospector
    B2B escrevendo devagar tem a mesma forma.
    """
    texto = (
        "Olá! Sinta-se à vontade na DriCafé, a sua loja de acessórios e cafés "
        "especiais. Como podemos te ajudar?\n\n👉 Aproveita e já siga a DriCafé no "
        "Instagram: instagram.com/dricafebsb"
    )
    apurados = set(sinais(texto))
    assert apurados == {"como_ajudar", "cortesia", "vitrine"}
    assert len(apurados & set(autoreply.NUCLEO)) == 1
    assert len(apurados & set(autoreply.APOIO)) == 2
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=18.7) is True
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=21_600.0) is False
    assert parece_autoresponder(texto, segundos_desde_nosso_envio=None) is False


def test_so_nucleo_dispensa_o_lag():
    """O atalho "sem lag" agora conta SÓ núcleo, e exige três.

    A placa de porta do Empório Minas (verbatim) traz boas-vindas + "como posso
    ajudar" + horário declarado: três coisas que só quem RECEBE alguém escreve.
    """
    placa = (
        "Olá, tudo bem? Seja bem vindo ao Empório Minas.\nComo posso ajudar?\n\n"
        "📲 Esse é o link do nosso catálogo:\n"
        "https://emporio-minas-2.ola.click/products\n\n"
        "⏰️ Horário de funcionamento: segunda à sábado das 9h às 19h"
    )
    nucleos = set(sinais(placa)) & set(autoreply.NUCLEO)
    assert len(nucleos) >= autoreply.NUCLEOS_QUE_DISPENSAM_LAG
    assert parece_autoresponder(placa, segundos_desde_nosso_envio=86_400.0) is True
    assert parece_autoresponder(placa, segundos_desde_nosso_envio=None) is True


def test_nucleo_e_apoio_particionam_os_sinais_de_indicio():
    """Guarda estrutural: um indício novo tem que entrar num dos dois conjuntos.

    Sem isto, quem acrescentar um indício e esquecer de classificá-lo cria um
    sinal que não é núcleo (nunca decide) e não é apoio (escapa da contagem
    separada) — exatamente o buraco que a revisão de 09/09/2026 fechou.
    """
    nomes = {nome for nome, _ in autoreply._INDICIOS} | {"boas_vindas"}
    assert nomes == set(autoreply.NUCLEO) | set(autoreply.APOIO)
    assert not set(autoreply.NUCLEO) & set(autoreply.APOIO)
    assert not (set(autoreply.NUCLEO) | set(autoreply.APOIO)) & autoreply.ASSINATURAS


def test_marca_invisivel_cobre_lrm_e_rlm():
    """`app/agent/adherence.py:183` já cobria as duas; aqui só a LRM contava.

    O banco hoje tem 28 textos distintos com LRM e ZERO com RLM — a cobertura é
    preventiva e custa nada. O que ela evita é o modo de falha em que um aparelho
    RTL do lado do lead injeta U+200F, o detector não vê assinatura nenhuma, e o
    robô come o único nudge do lead.
    """
    assert autoreply.MARCA_AUTOMATICA_RTL == "\u200f"
    assert autoreply.MARCAS_AUTOMATICAS == ("\u200e", "\u200f")
    rtl = f"{autoreply.MARCA_AUTOMATICA_RTL}Zenzi,"
    assert sinais(rtl) == ("marca_invisivel",)
    assert parece_autoresponder(rtl, segundos_desde_nosso_envio=None) is True
    # E some na normalização, como a LRM: colada numa palavra ela quebraria o
    # limite de palavra das regex sem deixar rastro na tela.
    assert autoreply._normalizar(rtl) == "zenzi,"
    assert (
        "horario"
        in sinais(f"nosso{autoreply.MARCA_AUTOMATICA_RTL} horario de atendimento")
    )


def test_o_codigo_fonte_nao_tem_escape_nao_decodificado_em_comentario():
    """Comentário com "\\u00e9" no lugar de "é" é texto quebrado, não documentação.

    Um comentário existe para ser lido na revisão; escrito em escape, ele deixa de
    ser lido. Os ÚNICOS escapes legítimos neste arquivo são os de largura zero
    (U+200E, U+200F, U+200B), que precisam ficar visíveis no fonte justamente por
    serem invisíveis na tela.
    """
    import inspect
    import re as _re

    fonte = inspect.getsource(autoreply)
    achados = set(_re.findall(r"\\u[0-9a-fA-F]{4}", fonte))
    assert achados <= {"\\u200e", "\\u200f", "\\u200b"}, achados
