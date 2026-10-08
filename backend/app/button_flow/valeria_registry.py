"""Estrutura do fluxo de botões da ValerIA. Dado puro, zero lógica.

O CONTRATO entre a tela (o modal de /campanhas) e o motor. Mesmo papel do
campaigns/node_registry.py, e pelo mesmo motivo: o cabeçalho daquele arquivo
documenta que o builder de cadências "foi construído e NUNCA foi usado — 16
campanhas, 0 ativas, 0 matrículas na história", e que toda falha medida tinha a
mesma raiz, a tela gravando uma chave e o motor lendo outra coisa no mesmo nome.

Aqui a tela só pode editar `corpo` e `rotulos`. Quem existe, quantos botões cada
nó tem e para onde cada botão vai é DECLARADO — não é editável, não vem do banco,
e é verificado por tests/test_valeria_registry_2026_09_29.py.

Do `app` importa UMA coisa: `app.button_flow.flows`, o registry irmão da
Recuperação, de onde vêm os três prazos de adiamento (`flows.PRAZOS`) e a frase
de fechamento do adiamento (`flows.MSG_PRAZO_FECHAMENTO`). Não cria ciclo porque
`flows.py` é ele próprio um leaf — importa só `dataclasses`, nada de `app` — e é
o único import de `app` que este arquivo tem. O que se reusa é DADO de negócio já
em produção; o que NÃO se reusa é o vocabulário de desfecho do outro fluxo (veja
a nota da folha de prazos, no fim do arquivo).

── De onde vêm os textos deste arquivo ──────────────────────────────────────
Todo `corpo` e todo `rotulo` abaixo são TRANSCRITOS de duas fontes, nunca
escritos aqui:
  • §5 da spec (docs/superpowers/specs/2026-09-29-valeria-botoes-design.md) —
    rótulos, destinos e a coluna "Grava";
  • o artefato "As Telas da ValerIA" que a spec linka, que fecha com "os textos
    são os definitivos, dentro do limite de 20 caracteres por botão".
Onde as duas divergem, a §5 vence na ESTRUTURA (é ela que o motor interpreta) e o
artefato vence no TEXTO. O único caso é o preço do `N5`: o artefato mostra
"R$28,70" já resolvido e a §5 manda o corpo trazer o marcador `{preco}` —
resolvido pelo runner contra `products` no instante do envio. Preço no texto
envelhece em silêncio; cotar de memória foi o que perdeu as 500 unidades da Ritz
(documentado em flows.py).

Os 3 corpos que NÃO estão em nenhuma das duas fontes estão marcados um a um com
"COMPOSTO" no lugar. São os dois nós de segundo produto (`N5b`, `P4b`) e o
reconhecimento de opt-out (`T_OPTOUT`), e cada um cita de onde a frase foi
copiada.

── Por que 17 nós e não 15 ──────────────────────────────────────────────────
A §4.1 da spec soma "N0 (1), N1–N5 (5), P1–P4 (4), C1 (1), E1–E4 (4) = 15" e
esquece os dois nós de segundo produto que a própria §5 exige: `N5b` e `P4b`, os
destinos de "Ver outras opções". Sem eles o botão não tem para onde ir. São 17
nós de conversa — a conta da §4.1 é o erro, não o desenho.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.button_flow import flows

FLOW_ID = "valeria_botoes_v1"
NO_ENTRADA = "N0"

# ── Limites da Meta (não são preferências: acima deles o envio é RECUSADO) ───
LIMITE_ROTULO_BOTAO = 20
LIMITE_TITULO_LISTA = 24
LIMITE_DESC_LISTA = 72
MAX_BOTOES = 3
MAX_LINHAS_LISTA = 10

# ── Tags de desfecho ────────────────────────────────────────────────────────
# Semeadas por 20260929_valeria_botoes.sql (§10 da spec) e resolvidas POR NOME
# EXATO: `add_tags_to_lead` procura o nome e devolve em silêncio se não achar,
# então um acento perdido aqui não levanta nada — só deixa de marcar o lead. É a
# mesma armadilha que flows.py documenta no seu bloco de tags.
TAG_QUALIFICADO = "Botões: Qualificado"
TAG_ADIADO = "Botões: Adiado"
TAG_HUMANO = "Botões: Atendimento humano"
TAG_OPTOUT = "Botões: Opt-out"

# Os dois vendedores, como a §5 os escreve no `encaminhar_humano(vendedor=...)`.
# Não é o nome do CARTÃO de contato: aquele é `agent.tools.SUPERVISOR_NAME`
# ("João - Café Canastra") e quem o envia é o runner, que pode importar app.
# SEM ACENTO de proposito: este valor vai no argumento `vendedor=` de
# encaminhar_humano, e TODO call site de producao passa "Joao Bras"
# (prompts/base.py:547, valeria_inbound/atacado.py:15, e outros 6). O nome
# ACENTUADO aparece na prosa dos terminais, que e o que o lead le — aqui e
# identificador, e identificador divergente e a classe de bug que
# campaigns/node_registry.py documenta.
VENDEDOR_ATACADO = "Joao Bras"
VENDEDOR_EXPORTACAO = "Arthur"


@dataclass(frozen=True)
class Botao:
    """Um botão. `id` é o contrato estável; o rótulo é editável na tela.

    A Meta devolve o `id` no webhook (meta_parser.py:161 grava em `payload`), então
    editar "Cafeteria" para "Sou cafeteria" NÃO quebra a conversa de quem já
    recebeu a tela antiga.
    """
    id: str
    rotulo: str
    destino: str
    # ((campo_do_score, valor),) — gravado por save_score_evidence no clique.
    grava: tuple[tuple[str, object], ...] = ()
    # Só para linhas de lista: a segunda linha, que o botão comum não tem.
    descricao: str = ""

    @property
    def titulo(self) -> str:
        """Alias de LEITURA de `rotulo`, para compatibilidade de renderizador.

        `engine.Mensagem.botoes` é anotado `tuple[flows.Botao, ...]` e este fluxo
        põe `reg.Botao` ali dentro: os dois tipos passam pelo MESMO campo, e o da
        Recuperação chama o texto de `titulo`. Não há type checker no CI deste
        repo, então um renderizador que leia `.titulo` não falharia na revisão —
        falharia em produção, num lead real, no meio da conversa. O alias faz os
        dois tipos serem estruturalmente intercambiáveis para qualquer
        renderizador.

        `rotulo` continua sendo o campo REAL e o único editável na tela (é ele que
        `valeria_content.aplicar` troca por `dataclasses.replace`). `titulo` é
        derivado de propósito: dois campos graváveis para o mesmo texto é a
        divergência que campaigns/node_registry.py documenta, agora dentro de uma
        linha só.
        """
        return self.rotulo


@dataclass(frozen=True)
class Card:
    """Um card do carrossel. O botão do card devolve o id `card:<id>` no webhook.

    Só existe na v2 (valeria_registry_v2.py); mora aqui para que os dois fluxos
    compartilhem os MESMOS tipos, como `Botao`, `No` e `Terminal`.
    """
    id: str                       # "classico"
    foto: str                     # caminho sob backend/app/photos/
    corpo: str                    # texto com marcadores {preco:<products.name exato>}
    skus: tuple[str, ...]         # products.name que o card cita; todos ativos e com preço, senão o card não sai
    exige_min_lot: str | None = None   # ex.: "100 un" — o card só sai se TODOS os skus tiverem esse min_lot
    destino: str = ""             # nó para onde o toque no card leva (QA1 / QP1)
    rotulo_botao: str = "Quero esse"


@dataclass(frozen=True)
class No:
    id: str
    rotulo_interno: str          # "N1 · Segmento" — só tela e log
    # "botoes" | "lista" | "foto_botoes" | "carrossel". "carrossel" é nó da v2
    # (vitrine): `cards` vira o carrossel e `botoes` são os botões de ação.
    tela: str
    corpo: str
    botoes: tuple[Botao, ...]
    ramo: str                    # "entrada"|"atacado"|"private_label"|"consumo"|"exportacao"
    foto: str | None = None      # caminho sob backend/app/photos/
    produto: str | None = None   # SKU declarado; o preço vem do catálogo no envio
    editaveis: tuple[str, ...] = ("corpo", "rotulos")
    # Só nós `tela="carrossel"` da v2 têm cards; na v1 é sempre vazio.
    cards: tuple[Card, ...] = ()


@dataclass(frozen=True)
class Terminal:
    id: str
    rotulo_interno: str
    vendedor: str | None = None
    corpo: str = ""
    tags: tuple[str, ...] = ()
    silenciar_ia: bool = False
    handoff: bool = False
    optout: bool = False
    # Quando True, o terminal PERGUNTA o prazo (30/60/90) em vez de encerrar.
    prazos: bool = False


# ─── Os nós ──────────────────────────────────────────────────────────────────
#
# `grava` só aparece no ramo ATACADO, e de propósito. `lead_score/model.py` é
# "wholesale lead scoring": os 5 critérios (segment, monthly_volume_kg,
# supplier_reason, purchase_timing, purchase_intent) descrevem um revendedor.
# Gravar `purchase_intent` num lead de private label ou de exportação produziria
# um score com 4 dos 5 campos vazios — `is_provisional=True` e prioridade "low"
# para o lead do MAIOR setor da casa (45% dos leads). Melhor não ter score do que
# ter um score que mente. É o que a §5 declara: só o ramo A "fecha o score".

# ── O corpo do nudge ────────────────────────────────────────────────────────
# Reoferecimento: quando o lead DIGITA em vez de tocar, o motor reenvia o MESMO
# no com este corpo e os MESMOS botoes daquele no.
#
# Mora aqui, e nao no motor, porque a secao 6 da spec declara este texto
# editavel na tela — e o unico jeito de a tela editar sem inventar um segundo
# mecanismo de armazenamento e ele ser um override como qualquer outro. A tabela
# `valeria_flow_content` e chaveada por `node_id`, e o nudge NAO e um no: por
# isso ele tem a chave reservada abaixo. Sem ela havia dois donos possiveis para
# uma string (registry e motor), que e exatamente a divergencia que
# campaigns/node_registry.py documenta.
CHAVE_NUDGE = "__nudge__"

# O TEXTO MUDOU EM 01/10, e o motivo saiu de producao: o corpo antigo era "pra eu te
# passar o VALOR certo, e so tocar numa das opcoes" e ele pressupoe que o lead
# perguntou preco. No primeiro dia do fluxo ele respondeu a um AUDIO de numero errado
# ("Oi, minha filha, como voce esta?") e a um VIDEO — nos dois a frase nao faz sentido
# nenhum, porque o nudge responde a QUALQUER coisa que nao seja um clique (audio,
# video, figurinha, localizacao), e nao so a uma pergunta de preco. O corpo novo e
# neutro e serve aos quatro casos. Continua editavel na tela pela chave reservada
# acima, ou seja, reversivel sem deploy.
CORPO_NUDGE = "pra seguir, é só tocar numa das opções abaixo 👇"

# ── O rótulo do botão que ABRE a folha de opções numa tela de lista ─────────
# Mesma situação do nudge, e por isso a MESMA solução: é texto que o lead LÊ (nas
# duas listas do fluxo, N0 e E1), não pertence a nó nenhum — é o mesmo para as
# duas — e `valeria_flow_content` é chaveada por `node_id`. Sem chave reservada
# nenhuma linha da tabela o alcança: ele morava no runner e era o único texto
# visível ao lead que a tela não conseguia editar.
#
# Limite de 20 caracteres é da Meta (`LIMITE_ROTULO_BOTAO`), não preferência:
# acima dele o envio da lista é RECUSADO e a ValerIA fica muda na tela de
# entrada. `valeria_content.validar` é quem fecha esse portão na gravação.
CHAVE_ROTULO_LISTA = "__rotulo_lista__"

ROTULO_BOTAO_LISTA = "Ver opções"

# Teto de reenvios por ATENDIMENTO, nao por no. Por no, 17 nos dariam 51 nudges:
# o desperdicio maximo por lead passaria de 3 para 51 mensagens faturadas.
TETO_NUDGES = 3


NOS: dict[str, No] = {
    "N0": No(
        id="N0", rotulo_interno="N0 · Setor", tela="lista", ramo="entrada",
        corpo=(
            "oi! aqui é a Valéria, do comercial da Café Canastra ☕\n\n"
            "pra eu já te levar pro que importa e não te encher de coisa que não "
            "tem a ver com você, me diz: o café é pra qual caso?"
        ),
        # Lista e não botões por DOIS motivos, e os dois valem: 4 opções não cabem
        # no teto de 3 botões da Meta, e a linha de lista aceita descrição — o
        # botão não. A descrição é o que faz "Pro meu negócio" não precisar de
        # uma segunda mensagem explicando o que é.
        botoes=(
            Botao("negocio", "Pro meu negócio", "N1",
                  descricao="revenda, cafeteria, restaurante, hotel"),
            Botao("marca", "Com a minha marca", "P1",
                  descricao="café embalado com a sua logo"),
            Botao("consumo", "Pra consumo próprio", "C1",
                  descricao="em casa ou de presente"),
            Botao("exportacao", "Pra exportação", "E1",
                  descricao="mercado externo"),
        ),
    ),

    # ── Ramo A · Atacado → João Brás · 8 mensagens · fecha o score ──────────
    "N1": No(
        id="N1", rotulo_interno="N1 · Segmento", tela="botoes", ramo="atacado",
        corpo="boa! e que tipo de negócio você tem?",
        botoes=(
            # Os 15 segmentos do score têm só 3 FAIXAS de pontuação
            # (lead_score/model.py:16-31): cafeteria=2, as 9 lojas
            # especializadas=1, o resto=0. Por isso 3 botões bastam.
            Botao("cafeteria", "Cafeteria", "N2", grava=(("segment", "cafeteria"),)),
            Botao("loja", "Loja ou empório", "N2", grava=(("segment", "emporio"),)),
            Botao("outro", "Outro tipo", "N2", grava=(("segment", "other"),)),
        ),
    ),
    "N2": No(
        id="N2", rotulo_interno="N2 · Volume", tela="botoes", ramo="atacado",
        corpo="e quanto café você usa por mês, mais ou menos?",
        botoes=(
            # `monthly_volume_kg` é NÚMERO, não faixa: o score faz
            # `volume <= 30` (model.py:88). Por isso cada botão grava o
            # representante da sua faixa — 30 pontua 1, 65 e 150 pontuam 0.
            # Contraintuitivo de propósito: quem usa pouco é quem a Canastra
            # atende melhor; volume grande vira negociação do João.
            Botao("ate30", "Até 30 kg por mês", "N3", grava=(("monthly_volume_kg", 30),)),
            Botao("ate100", "30 a 100 kg", "N3", grava=(("monthly_volume_kg", 65),)),
            Botao("mais100", "Mais de 100 kg", "N3", grava=(("monthly_volume_kg", 150),)),
        ),
    ),
    "N3": No(
        id="N3", rotulo_interno="N3 · Fornecedor", tela="botoes", ramo="atacado",
        corpo="e hoje, como tá o seu fornecimento de café?",
        botoes=(
            # `replace` vale 2 pontos E é metade da regra de score 10
            # (model.py:95: replace + purchase_intent clear => 10, "maximum",
            # ignorando o resto). É o clique mais valioso do fluxo inteiro.
            Botao("trocar", "Quero trocar", "N4", grava=(("supplier_reason", "replace"),)),
            Botao("segundo", "Quero um segundo", "N4",
                  grava=(("supplier_reason", "second_supplier"),)),
            Botao("comecar", "Ainda não vendo café", "N4",
                  grava=(("supplier_reason", "start_specialty_coffee"),)),
        ),
    ),
    "N4": No(
        id="N4", rotulo_interno="N4 · Prazo", tela="botoes", ramo="atacado",
        corpo="última coisa: pra quando você precisa?",
        botoes=(
            Botao("dias15", "Próximos 15 dias", "N5",
                  grava=(("purchase_timing", "within_15_days"),)),
            # `days_16_30` é o que a §5 declara para "Este mês ou o outro", e não
            # `months_1_3`, que seria a leitura literal do rótulo. Os dois valem 0
            # ponto (só `within_15_days` pontua), então a escolha não muda o score —
            # mas o valor gravado é o que a §5 diz, não o que o rótulo sugere.
            Botao("mes", "Este mês ou o outro", "N5",
                  grava=(("purchase_timing", "days_16_30"),)),
            Botao("sem_data", "Ainda sem data", "N5",
                  grava=(("purchase_timing", "no_timeline"),)),
        ),
    ),
    "N5": No(
        id="N5", rotulo_interno="N5 · Entrega + encaminhamento", tela="foto_botoes",
        ramo="atacado",
        # Foto + preço + pergunta numa mensagem SÓ. A mensagem interativa da Meta
        # aceita header de imagem, e é isso que corta 2 mensagens faturadas do ramo
        # mais caro. Hoje `enviar_fotos("atacado")` manda o catálogo inteiro: 6
        # arquivos = 6 mensagens.
        #
        # `{preco}` é marcador, nunca número. O runner resolve contra `products` no
        # envio; se o produto declarado não casar com SKU ativo, manda o corpo SEM a
        # linha de preço, como flows.MSG_QUENTE_SEM_PRECO já faz.
        # O qualificador "gira em torno de" é obrigatório e fechado
        # (atacado.py:46-59): "sai por R$" e "é R$" são capturados pelo QA como
        # compromisso de preço.
        corpo=(
            "esse é o Clássico 250g — torra escura, notas de caramelo e chocolate, "
            "84 pontos, da nossa fazenda na Serra da Canastra.\n\n"
            "gira em torno de {preco} a unidade no atacado.\n\n"
            "gostaria de ser encaminhado ao vendedor?"
        ),
        foto="atacado/foto_1_classico.jpg",
        produto="Clássico 250g",
        botoes=(
            Botao("sim", "Sim, quero falar", "T_HANDOFF",
                  grava=(("purchase_intent", "clear"),)),
            # Não grava nada: "quero ver outro café" não é sinal de intenção em
            # nenhuma direção. Gravar `unclear` aqui rebaixaria um lead que está
            # justamente comparando produto.
            Botao("ver_outras", "Ver outras opções", "N5b"),
            Botao("nao_agora", "Não agora", "T_ADIAR",
                  grava=(("purchase_intent", "unclear"),)),
        ),
    ),
    "N5b": No(
        id="N5b", rotulo_interno="N5b · Segundo produto", tela="foto_botoes",
        ramo="atacado",
        # COMPOSTO. Nem a §5 nem o artefato mostram esta tela; o que as duas
        # declaram é a ESTRUTURA (segundo produto = Suave 250g, sem o botão de
        # reoferecer). O corpo espelha a forma do N5 e a nota sensorial é copiada
        # palavra por palavra de `SENSORY_CAPTIONS_ATACADO["suave"]` em
        # agent/tools.py — fonte de verdade ÚNICA das notas, derivada do banco
        # `products`. A auditoria QA de 15/07 pegou exatamente esta divergência
        # (legenda dizia "melaço", que é do Microlote), então a nota se COPIA, não
        # se parafraseia.
        corpo=(
            "esse é o Suave 250g — torra média, notas achocolatadas, mesmo café "
            "84 pontos da nossa fazenda.\n\n"
            "gira em torno de {preco} a unidade no atacado.\n\n"
            "gostaria de ser encaminhado ao vendedor?"
        ),
        foto="atacado/foto_2_suave.jpg",
        produto="Suave 250g",
        # SEM `ver_outras`: é a TOPOLOGIA que garante "uma vez só". Um contador no
        # flow_state seria estado a mais para o teste cobrir e para o operador
        # entender; aqui o reoferecimento simplesmente não existe neste nó.
        botoes=(
            Botao("sim", "Sim, quero falar", "T_HANDOFF",
                  grava=(("purchase_intent", "clear"),)),
            Botao("nao_agora", "Não agora", "T_ADIAR",
                  grava=(("purchase_intent", "unclear"),)),
        ),
    ),

    # ── Ramo B · Private Label → João Brás · 7 mensagens · 45% dos leads ────
    "P1": No(
        id="P1", rotulo_interno="P1 · A marca", tela="botoes", ramo="private_label",
        corpo="que projeto bom! você já tem uma marca criada ou tá pensando em lançar do zero?",
        botoes=(
            Botao("tenho_marca", "Já tenho a marca", "P2"),
            Botao("criar_zero", "Quero criar do zero", "P2"),
            # Atalho direto ao vendedor: torra e envase de grão de terceiro é
            # SERVIÇO, não projeto de marca, e é produto que a casa não faz.
            # `private_label.py` já trata "Graos de Terceiros" como exceção do
            # circuit breaker — aqui a exceção vira uma aresta declarada.
            Botao("tenho_graos", "Já tenho os grãos", "T_HANDOFF_PL"),
        ),
    ),
    "P2": No(
        id="P2", rotulo_interno="P2 · Lote", tela="botoes", ramo="private_label",
        corpo="e quantos pacotes você pensa por lote?",
        botoes=(
            Botao("ate100", "Até 100 pacotes", "P3"),
            Botao("ate500", "100 a 500", "P3"),
            Botao("mais500", "Mais de 500", "P3"),
        ),
    ),
    "P3": No(
        id="P3", rotulo_interno="P3 · Prazo", tela="botoes", ramo="private_label",
        corpo="e pra quando você quer lançar?",
        botoes=(
            Botao("dias30", "Próximos 30 dias", "P4"),
            Botao("meses23", "Em 2 ou 3 meses", "P4"),
            Botao("sem_data", "Ainda sem data", "P4"),
        ),
    ),
    "P4": No(
        id="P4", rotulo_interno="P4 · Entrega + encaminhamento", tela="foto_botoes",
        ramo="private_label",
        # SEM número de preço, e sem `{preco}`: o valor do private label muda por
        # LOTE e não há SKU fixo para o runner resolver. O corpo diz de onde o
        # valor sai em vez de dizer quanto é — `private_label.py:29` manda
        # exatamente isso ("te confirmo no fechamento com o João Brás").
        corpo=(
            "assim fica o resultado: embalagem standup com a sua logo, café 84 "
            "pontos da nossa fazenda, torrado e empacotado por nós e pronto pra "
            "vender.\n\n"
            "o valor por pacote sai do catálogo, conforme o lote.\n\n"
            "gostaria de ser encaminhado ao vendedor?"
        ),
        # `foto_2.jpg` é o slug "standup" em CATALOGO_FOTOS["private_label"]
        # (agent/tools.py) — o mesmo modelo que o corpo nomeia. O vínculo
        # arquivo↔conteúdo vem do nome do slug, não da posição: a auditoria QA de
        # 08/09 achou legenda de Microlote colada na foto das cápsulas justamente
        # porque o vínculo era posicional.
        foto="private_label/foto_2.jpg",
        botoes=(
            Botao("sim", "Sim, quero falar", "T_HANDOFF_PL"),
            Botao("ver_outras", "Ver outra opção", "P4b"),
            Botao("nao_agora", "Não agora", "T_ADIAR"),
        ),
    ),
    "P4b": No(
        id="P4b", rotulo_interno="P4b · Segunda opção", tela="foto_botoes",
        ramo="private_label",
        # COMPOSTO, mesma situação do N5b: a estrutura é declarada, o texto não.
        # A "outra opção" é o silk — `foto_3.jpg`, slug "silk" em
        # CATALOGO_FOTOS["private_label"], legenda de banco "Exemplo de silk com
        # logo do cliente". É um modelo de embalagem diferente do standup do P4, e
        # não uma foto do mesmo produto de outro ângulo.
        corpo=(
            "tem também o silk: a sua logo impressa direto na embalagem, mesmo "
            "café 84 pontos da nossa fazenda.\n\n"
            "o valor por pacote sai do catálogo, conforme o lote.\n\n"
            "gostaria de ser encaminhado ao vendedor?"
        ),
        foto="private_label/foto_3.jpg",
        # Sem `ver_outras` — igual ao N5b, "uma vez só" pela topologia.
        botoes=(
            Botao("sim", "Sim, quero falar", "T_HANDOFF_PL"),
            Botao("nao_agora", "Não agora", "T_ADIAR"),
        ),
    ),

    # ── Ramo C · Consumo → loja online · 2 mensagens ────────────────────────
    "C1": No(
        id="C1", rotulo_interno="C1 · Loja + cupom", tela="botoes", ramo="consumo",
        # Link e cupom na MESMA mensagem. Hoje o prompt de consumo tem uma "REGRA
        # ATOMICA DO CUPOM" que manda quebrar isso em 3 bolhas ("nao empilhe \n\n
        # dentro de nenhuma") porque a falha de 02/07 deixou um lead sem o cupom
        # prometido. Aqui as 3 viram 1: sem IA no caminho, não existe turno onde a
        # segunda bolha se perca.
        #
        # `*ESPECIAL10*` com asterisco simples é negrito do WhatsApp. O artefato de
        # desenho mostra `<b>` porque é HTML; no corpo o que vale é a sintaxe da
        # Meta. Cupom e link conferidos contra consumo.py:36-48.
        corpo=(
            "nossa linha completa tá na loja online, e vou te deixar um cupom de "
            "10% de desconto pra usar lá 🎟️\n\n"
            "🔗 loja.cafecanastra.com\n"
            "cupom: *ESPECIAL10*\n\n"
            "qualquer dúvida sobre os cafés, me chama aqui."
        ),
        botoes=(
            # O único botão do fluxo que MUDA de ramo: consumo que pede quantidade
            # é atacado, e entra pelo N1 como qualquer outro.
            Botao("quantidade", "Quero em quantidade", "N1"),
            Botao("duvida", "Tenho uma dúvida", "T_HUMANO"),
        ),
        # Sem clique, encerra em T_FIM — e T_FIM não descarta ninguém. É a regra
        # "Consumo não é encerramento definitivo" de consumo.py. Por isso nenhum
        # botão aponta para T_FIM: quem leva o lead até lá é o silêncio, não um
        # clique, e é o runner que fecha o atendimento.
    ),

    # ── Ramo D · Exportação → Arthur · 7 mensagens ──────────────────────────
    "E1": No(
        id="E1", rotulo_interno="E1 · Destino", tela="lista", ramo="exportacao",
        corpo="legal! e qual é o mercado de destino?",
        # Lista pelo mesmo motivo do N0: 6 mercados não cabem em 3 botões. Sem
        # descrição aqui — nome de mercado não precisa de segunda linha, e linha
        # vazia na folha de opções fica pior do que sem linha.
        botoes=(
            Botao("europa", "Europa", "E2"),
            Botao("eua", "Estados Unidos", "E2"),
            Botao("asia", "Ásia", "E2"),
            Botao("america_latina", "América Latina", "E2"),
            Botao("oriente_medio", "Oriente Médio", "E2"),
            Botao("outro", "Outro mercado", "E2"),
        ),
    ),
    "E2": No(
        id="E2", rotulo_interno="E2 · Estrutura", tela="botoes", ramo="exportacao",
        # A forma condicional é obrigatória neste ramo: `exportacao.py` tem uma
        # regra "Anti-premissa" que PROÍBE assumir que o lead já exporta. "você
        # exporta pelo seu próprio CNPJ ou prefere que a gente cuide" não assume.
        corpo="e você exporta pelo seu próprio CNPJ ou prefere que a gente cuide dessa parte?",
        botoes=(
            Botao("cnpj_proprio", "Pelo meu CNPJ", "E3"),
            Botao("voces_exportam", "Vocês exportam", "E3"),
            Botao("nao_sei", "Ainda não sei", "E3"),
        ),
    ),
    "E3": No(
        id="E3", rotulo_interno="E3 · Objetivo", tela="botoes", ramo="exportacao",
        corpo="e o seu objetivo é…",
        # Duas opções, não três: `exportacao.py` coleta exatamente esta dicotomia
        # (agente/representante vs. comprador revendedor). Um terceiro botão
        # genérico daria ao Arthur um lead com a pergunta sem resposta.
        botoes=(
            Botao("revender", "Comprar e revender", "E4"),
            Botao("representante", "Ser representante", "E4"),
        ),
    ),
    "E4": No(
        id="E4", rotulo_interno="E4 · Encaminhamento", tela="botoes", ramo="exportacao",
        corpo=(
            "com essas informações o Arthur, nosso responsável de exportação, já "
            "consegue te atender direto.\n\n"
            "gostaria de ser encaminhado a ele?"
        ),
        botoes=(
            Botao("sim", "Sim, quero falar", "T_HANDOFF_ARTHUR"),
            Botao("nao_agora", "Não agora", "T_ADIAR"),
        ),
    ),
}


# ─── Os terminais ────────────────────────────────────────────────────────────
#
# SETE, e a §5 lista cinco. Os dois que faltam na tabela dela são `T_OPTOUT` e
# `T_ADIADO`.
#
# `T_ADIADO` é o turno seguinte ao `T_ADIAR`: a §5 trata o adiamento como ponta
# de linha e esquece que ele PERGUNTA, então o que o lead vê depois de tocar "Em
# 30 dias" não está declarado em lugar nenhum da spec. Sem esse terminal o clique
# cai num corpo vazio e o adiamento termina em silêncio.
#
# O outro é `T_OPTOUT`, que a §6 descreve sem nomear:
# "casou → registrar_optout imediato, sem gastar nudge". Ele é destino do MOTOR
# (nenhum botão aponta para ele — quem chega lá digitou "pare"), e é por isso que
# escapou da tabela da §5. Sem declaração, o efeito de opt-out ficaria escrito
# dentro do motor e o desfecho mais delicado do fluxo — o único que a Meta EXIGE
# honrar — seria o único invisível na tela.
#
# `T_FIM` não é destino de clique nenhum: quem leva o lead até lá é o silêncio
# depois do C1, e é o runner que fecha o atendimento. `T_ADIADO` é o contrário —
# SÓ se chega nele por clique — mas o clique vem da folha `BOTOES_PRAZO`, que é
# oferecida por um TERMINAL (`T_ADIAR`) e não por um nó. Ou seja: uma caminhada
# pelos botões de `NOS` não alcança nem um nem outro, e é por isso que o teste de
# alcançabilidade cobre só `NOS`. As arestas da folha de prazos têm cobertura
# própria em tests/test_valeria_adiamento_2026_09_29.py.

TERMINAIS: dict[str, Terminal] = {
    "T_HANDOFF": Terminal(
        id="T_HANDOFF", rotulo_interno="Handoff · João Brás",
        vendedor=VENDEDOR_ATACADO,
        # O cartão de contato NÃO é decidido aqui: é o runner que aplica a regra
        # `canal_do_vendedor` (engine.py:317) e omite o cartão quando a conversa já
        # está no número do próprio João. Mandar o cartão dele no número dele é
        # justamente o degrau que a auditoria do funil mediu em 26% de perda.
        # SEM "!" E SEM EMOJI, contra o texto da maquete. A auditoria 08/07
        # (nota do `_HANDOFF_MSG` em agent/tools.py:239) mediu que os leads
        # receberam "Perfeito! Seu atendimento agora sera continuado..." e que
        # maiusculas, "!", emoji e ponto final QUEBRARAM A MASCARA no momento
        # mais fragil da conversa. O handoff e exatamente esse momento. O texto
        # segue editavel na tela, entao a decisao e reversivel.
        corpo="perfeito, já chamei o João Brás aqui\n\nele te responde em instantes",
        tags=(TAG_QUALIFICADO,),
        silenciar_ia=True,
        handoff=True,
    ),
    "T_HANDOFF_PL": Terminal(
        id="T_HANDOFF_PL", rotulo_interno="Handoff · João Brás (marca própria)",
        vendedor=VENDEDOR_ATACADO,
        # Terminal SEPARADO do T_HANDOFF, e nao o mesmo com texto trocado: a
        # maquete aprovada traz duas redacoes distintas de handoff — atacado
        # ("ele te responde em instantes") e marca propria ("ele te detalha tudo
        # e da o proximo passo contigo"). Um terminal so nao carrega as duas, e
        # resolver isso com linha por ramo no `valeria_flow_content` faria a
        # tabela de CONTEUDO carregar uma diferenca de ESTRUTURA. Mesmo vendedor,
        # mesma tag, mesmos efeitos: muda so a frase.
        corpo="show, já chamei o João Brás aqui\n\nele te detalha tudo e dá o próximo passo contigo",
        tags=(TAG_QUALIFICADO,),
        silenciar_ia=True,
        handoff=True,
    ),
    "T_HANDOFF_ARTHUR": Terminal(
        id="T_HANDOFF_ARTHUR", rotulo_interno="Handoff · Arthur",
        vendedor=VENDEDOR_EXPORTACAO,
        # Mesma regra de voz do T_HANDOFF (auditoria 08/07).
        corpo="combinado, já passei pro Arthur\n\nele entra em contato assim que estiver disponível",
        tags=(TAG_QUALIFICADO,),
        silenciar_ia=True,
        handoff=True,
    ),
    "T_ADIAR": Terminal(
        id="T_ADIAR", rotulo_interno="Adiamento · 30/60/90 dias",
        # PERGUNTA, não encerra: `prazos=True` faz o motor oferecer a folha
        # `BOTOES_PRAZO` declarada no fim deste arquivo (Em 30 / 60 / 90 dias).
        # Quem responde ao toque é `T_ADIADO` — sem ele este terminal pergunta e
        # não escuta, que foi o defeito medido: o clique caía em `T_FIM`, de corpo
        # vazio, e o lead levava SILÊNCIO no turno em que acabou de pedir para ser
        # chamado de novo.
        #
        # E `optout=False` é o ponto inteiro deste terminal. "Não agora" não é um
        # não: medido em 9 casos no canal do João, 4 voltaram sozinhos e um fechou
        # R$ 5.500. Quem pergunta QUANDO guarda o lead; quem pergunta SE o perde.
        # Interrogacao fica: e pergunta, nao exclamacao. O "!" sai (auditoria 08/07).
        corpo="sem problema, quando faz sentido eu te chamar de novo?",
        tags=(TAG_ADIADO,),
        prazos=True,
    ),
    "T_ADIADO": Terminal(
        id="T_ADIADO", rotulo_interno="Adiamento confirmado",
        # A RESPOSTA ao toque em 30/60/90 — o turno que faltava. O destino antigo
        # era `T_FIM`, de corpo vazio, e corpo vazio é o contrato declarado de "não
        # manda mensagem": o lead pedia para ser chamado em 30 dias e a ValerIA
        # não dizia nada.
        #
        # O texto é REUSADO de `flows.MSG_PRAZO_FECHAMENTO`, a frase que a
        # Recuperação já manda em produção exatamente neste turno — não é copiada
        # para cá. Duas cópias da mesma string são dois donos, e a que ninguém
        # lembrar de editar é a que fica errada.
        #
        # Guarda o MOLDE, não a frase resolvida: `{prazo}` é substituído pelo
        # runner no instante do envio (`flows.render` com o `rotulo_humano` do
        # prazo clicado — "em 30 dias"), do mesmo jeito que `{preco}` nos nós de
        # foto. O motor devolve o corpo como está aqui.
        #
        # `optout=False` e `handoff=False` são o ponto do adiamento: quem marcou
        # data continua na base e continua sendo lead da ValerIA — não foi
        # descartado nem entregue a vendedor. O agendamento em si sai por
        # `Efeitos.recontato_dias`, que o motor preenche com `DIAS_POR_PRAZO`.
        #
        # `prazos=False`: reoferecer a folha aqui reperguntaria o que o lead
        # acabou de responder.
        corpo=flows.MSG_PRAZO_FECHAMENTO,
        tags=(TAG_ADIADO,),
    ),
    "T_HUMANO": Terminal(
        id="T_HUMANO", rotulo_interno="Atendimento humano",
        # 0 mensagens: `corpo` vazio é o contrato de "não gasta mensagem". Chega
        # aqui quem pediu pessoa ("Tenho uma dúvida") e quem digitou 3 vezes — e
        # esse segundo NÃO é blacklist: quem insiste em digitar é quem quer falar,
        # e descartá-lo é a perda que a auditoria do funil mediu.
        corpo="",
        tags=(TAG_HUMANO,),
        silenciar_ia=True,
    ),
    "T_FIM": Terminal(
        id="T_FIM", rotulo_interno="Encerrado sem descarte",
        # Nem mensagem, nem tag, nem opt-out. É o fim do ramo Consumo sem clique:
        # "Consumo não é encerramento definitivo" (consumo.py). O lead continua na
        # base, com `opt_out` false, e pode voltar a qualquer momento.
        corpo="",
    ),
    "T_OPTOUT": Terminal(
        id="T_OPTOUT", rotulo_interno="Opt-out por texto",
        # COMPOSTO: a frase é copiada de `_OPTOUT_MSG` em agent/tools.py, que é o
        # texto que a produção já manda quando um lead pede para sair — mesma voz
        # (minúsculas, sem ponto final), mesmo evento.
        corpo="sem problema, não te mando mais mensagem por aqui\n\nqualquer coisa, é só chamar",
        tags=(TAG_OPTOUT,),
        silenciar_ia=True,
        optout=True,
    ),
}


# ─── A folha de prazos (os botões do T_ADIAR) ────────────────────────────────
#
# Mora AQUI, e não no motor, pelo mesmo motivo de todo o resto deste arquivo:
# botão é estrutura, e o motor é intérprete de estrutura, não dono dela. Estes
# três eram declarados em `valeria_engine.py` — a única aresta do fluxo que a tela
# não conseguia enxergar no registry.
#
# Os 30/60/90 vêm de `flows.PRAZOS`, não são redigitados: estão calibrados no
# intervalo real entre compras desta base (78-122 dias, nota da própria
# `flows.PRAZOS`) e a Recuperação é dona desse número. Reusa-se `id`, `titulo` e
# `dias`.
#
# O que NÃO se reusa é `flows.Prazo.tag` ("Recuperação: 30 dias"): aquele é o
# vocabulário de desfecho do OUTRO fluxo, e aplicá-lo num lead da ValerIA
# carimbaria como recuperação quem nunca esteve numa onda de recuperação. A tag
# daqui é `TAG_ADIADO`, aplicada por `T_ADIAR` na ida e por `T_ADIADO` na volta.
#
# Os rótulos desta folha NÃO são editáveis na tela, ao contrário dos rótulos de
# nó: `valeria_flow_content` é chaveada por `node_id` e a folha não é um nó (é
# oferecida por um terminal). Quem quiser mudar "Em 30 dias" muda em `flows.PRAZOS`,
# onde o outro fluxo também é servido — e é assim de propósito, porque o número de
# dias e o rótulo têm de dizer a mesma coisa nos dois fluxos.
BOTOES_PRAZO: tuple[Botao, ...] = tuple(
    Botao(id=p.id, rotulo=p.titulo, destino="T_ADIADO") for p in flows.PRAZOS
)

# Dias de recontato por id de botão. O motor põe isso em `Efeitos.recontato_dias`
# quando o clique vem DESTA folha — o agendamento é efeito declarado do botão, não
# regra do motor.
DIAS_POR_PRAZO: dict[str, int] = {p.id: p.dias for p in flows.PRAZOS}
