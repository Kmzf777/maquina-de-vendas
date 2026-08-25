"""Geração do PDF do orçamento (proposta comercial) com a marca Café Canastra.

Por que o PDF é nosso e não do Bling: a API de propostas comerciais **não tem
endpoint de PDF** — a spec OpenAPI inteira foi varrida e os únicos PDFs que ela
devolve são DANFE de NF-e e etiqueta de envio. Então o documento que o cliente
recebe é montado aqui.

REGRA DE OURO DESTE MÓDULO: nenhuma rede, nenhum banco. Tudo chega pronto em
dicionários e o único I/O é ler o logo do disco. Isso não é purismo — é o que
permite testar o documento inteiro chamando a função direto, sem subir a app e
sem mockar Supabase, e é o que garante que a rota `GET /api/quotes/{id}/pdf`
não fique dependente de um segundo serviço para responder.

Duas armadilhas do domínio que o código trata explicitamente:

* **`internal_notes` NUNCA sai no PDF.** É a anotação do vendedor (margem,
  histórico de negociação) e este arquivo vai para a mão do cliente. A chave
  simplesmente não é lida em lugar nenhum daqui — é mais seguro do que lembrar
  de filtrar.
* **Número da proposta pode não existir.** O `POST /propostas-comerciais`
  devolve só `{data:{id}}`; o `numero` vem de um `GET` seguinte que é
  best-effort. Um orçamento cujo GET falhou tem que gerar PDF do mesmo jeito,
  caindo no `id` e, na falta dos dois, num traço.

Formatação de dinheiro e data é feita **na mão**. Nada de `locale.setlocale`:
a imagem `python:3.12-slim` não tem a locale `pt_BR` gerada, então
`locale.setlocale(LC_ALL, "pt_BR.UTF-8")` levanta `locale.Error` em produção e
passaria despercebido na máquina do desenvolvedor (Windows tem a locale). Além
disso `locale` é estado global do processo — mudá-lo dentro de um request do
FastAPI contaminaria os outros requests que rodam no mesmo worker.
"""
import logging
import os
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import partial
from io import BytesIO
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (Image, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Identidade visual — os mesmos tokens do DESIGN.md, para o documento não
# destoar do CRM. Helvetica é a fonte embutida no reportlab; a fonte da marca
# (Saans) não está no repositório e trocar, se o .ttf aparecer, é uma linha.
# --------------------------------------------------------------------------
COR_TEXTO = colors.HexColor("#111111")
COR_ROTULO = colors.HexColor("#7b7b78")
COR_FILETE = colors.HexColor("#dedbd6")

MARGEM = 16 * mm
# Faixa reservada na base para o rodapé fixo. O rodapé é desenhado no canvas
# (e não no fim da história) porque ele tem que aparecer em TODA página: as
# cláusulas de preço e tributo são o disclaimer comercial do documento, e um
# orçamento de duas páginas em que elas só constam na última é um orçamento em
# que a primeira página circula sozinha sem ressalva nenhuma.
RODAPE_ALTURA = 28 * mm

EMPRESA_RAZAO = "Boaventura Cafés Especiais Ltda"
EMPRESA_CNPJ = "CNPJ 24.252.228/0001-37"
EMPRESA_ENDERECO = ("Rua Nivaldo Guerreiro Nunes 701 · Distrito Industrial · "
                    "Uberlândia/MG · 38402-330")
EMPRESA_CONTATO = "comercial@cafecanastra.com · cafecanastra.com"

# Texto contratual — literal, revisado pelo usuário. Não reescrever nem
# "melhorar" a redação: é cláusula, não copy.
CLAUSULAS = (
    "Preços sujeitos a alteração sem aviso prévio.",
    "Tributos sob a venda já incluídos (não incluído possíveis diferenças de "
    "alíquotas de ICMS, consulte seu contador pois depende do seu regime "
    "tributário e das regras de seu estado).",
)

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "logocanastra.png")
# Largura impressa do logo e resolução com que ele é embutido.
#
# O arquivo tem 1092px de largura, mas no papel ele ocupa 38mm (~1,5"): a 300dpi
# — resolução de impressão — bastam ~450px. Embutir o PNG original custa ~1s de
# CPU e ~120KB POR PDF, porque o reportlab não repassa o PNG: ele decodifica os
# pixels e recomprime tudo em zlib a cada `build`, e o PNG original é pequeno em
# disco graças a filtros de predição que o PDF não usa. Numa rota síncrona que o
# vendedor chama esperando o download, é a diferença entre instantâneo e travado
# — e o resultado impresso é idêntico.
LOGO_LARGURA = 38 * mm
LOGO_DPI = 300

_CENT = Decimal("0.01")

# --------------------------------------------------------------------------
# Estilos
# --------------------------------------------------------------------------
_EST_BASE = ParagraphStyle(
    "q_base", fontName="Helvetica", fontSize=8.5, leading=11,
    textColor=COR_TEXTO, alignment=TA_LEFT,
)
_EST_TITULO = ParagraphStyle(
    "q_titulo", parent=_EST_BASE, fontName="Helvetica-Bold", fontSize=15,
    leading=18, alignment=TA_RIGHT,
)
_EST_TITULO_SUB = ParagraphStyle(
    "q_titulo_sub", parent=_EST_BASE, fontSize=8.5, leading=11,
    textColor=COR_ROTULO, alignment=TA_RIGHT,
)
_EST_EMPRESA = ParagraphStyle(
    "q_empresa", parent=_EST_BASE, fontSize=7.5, leading=10.5,
    textColor=COR_ROTULO,
)
_EST_SECAO = ParagraphStyle(
    "q_secao", parent=_EST_BASE, fontName="Helvetica-Bold", fontSize=7.5,
    leading=10, textColor=COR_ROTULO, spaceAfter=1.5,
)
_EST_ROTULO = ParagraphStyle(
    "q_rotulo", parent=_EST_BASE, fontSize=7.5, leading=10.5,
    textColor=COR_ROTULO,
)
_EST_VALOR = ParagraphStyle("q_valor", parent=_EST_BASE, leading=10.5)
_EST_ITEM = ParagraphStyle("q_item", parent=_EST_BASE, fontSize=8, leading=10)
_EST_MARCA = ParagraphStyle(
    "q_marca", parent=_EST_BASE, fontName="Helvetica-Bold", fontSize=13,
)
_EST_RODAPE = ParagraphStyle(
    "q_rodape", parent=_EST_BASE, fontSize=6.8, leading=8.6,
    textColor=COR_ROTULO,
)
_EST_RODAPE_VENDEDOR = ParagraphStyle(
    "q_rodape_vend", parent=_EST_RODAPE, fontName="Helvetica-Bold",
    fontSize=7.5, leading=10, textColor=COR_TEXTO,
)


# --------------------------------------------------------------------------
# Formatação — pt-BR na mão (ver o docstring do módulo sobre `locale`)
# --------------------------------------------------------------------------
def _dec(valor) -> Decimal:
    """Decimal tolerante. Nada aqui pode levantar: o PDF é gerado a partir de
    uma linha do banco que pode ter coluna nula ou string, e uma exceção de
    conversão viraria 500 numa rota cujo único trabalho é imprimir."""
    if valor is None or valor == "":
        return Decimal("0")
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _numero(valor, casas: int = 2) -> str:
    """`1234.5` -> `1.234,50`. Milhar com ponto, decimal com vírgula."""
    d = _dec(valor).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    sinal = "-" if d < 0 else ""
    inteiro, _, frac = f"{abs(d):.{casas}f}".partition(".")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    texto = sinal + ".".join(grupos)
    return f"{texto},{frac}" if casas else texto


def _brl(valor) -> str:
    return "R$ " + _numero(valor, 2)


def _quantidade(valor) -> str:
    """Até 3 casas (a coluna é `numeric(14,3)`), sem zeros à toa: `2` e não
    `2,000`, mas `1,5` continua `1,5`."""
    texto = _numero(valor, 3)
    if "," in texto:
        texto = texto.rstrip("0").rstrip(",")
    return texto or "0"


def _percentual(valor) -> str:
    """Zero vira traço em vez de `0%`: a coluna de desconto por item costuma
    estar toda zerada e uma coluna de zeros só polui a leitura da tabela."""
    d = _dec(valor)
    if d == 0:
        return "-"
    texto = _numero(d, 2)
    if "," in texto:
        texto = texto.rstrip("0").rstrip(",")
    return f"{texto}%"


def _data(valor) -> str:
    """`2026-08-25` -> `25/08/2026`. Aceita date/datetime e ISO com hora.

    Data impossível de interpretar volta como veio, nunca levanta — um campo
    torto não pode impedir o vendedor de baixar o orçamento.
    """
    if valor is None or valor == "":
        return "-"
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor).strip()
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return texto


def _telefone(valor) -> str:
    """`5534999998888` -> `(34) 99999-8888`.

    O telefone chega no formato do WhatsApp (DDI colado, sem pontuação), que é
    ilegível num documento comercial. Formato desconhecido volta intacto — é
    melhor mostrar o número cru do que esconder ou deformar o contato.
    """
    if not valor:
        return ""
    digitos = "".join(c for c in str(valor) if c.isdigit())
    if digitos.startswith("55") and len(digitos) in (12, 13):
        digitos = digitos[2:]
    if len(digitos) in (10, 11):
        ddd, resto = digitos[:2], digitos[2:]
        return f"({ddd}) {resto[:-4]}-{resto[-4:]}"
    return str(valor)


def _documento(valor) -> str:
    """`12345678000190` -> `12.345.678/0001-90`; `12345678901` -> `123.456.789-01`.

    Mesma razao do `_telefone`: o documento e guardado so em digitos (e a chave
    de deduplicacao do contato no Bling), mas quem le o orcamento e o cliente,
    que confere o proprio CNPJ formatado como esta na nota. Quantidade de
    digitos fora de 11/14 volta intacta — documento estrangeiro ou cadastro
    torto e melhor aparecer cru do que sair deformado por um formatador que
    nao sabe o que esta olhando.
    """
    if not valor:
        return ""
    digitos = "".join(c for c in str(valor) if c.isdigit())
    if len(digitos) == 14:
        d = digitos
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(digitos) == 11:
        d = digitos
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return str(valor)


def _esc(valor) -> str:
    """Escapa para o mini-XML do `Paragraph`.

    Sem isso um cliente chamado "Zé & Filhos" ou uma observação com `<` derruba
    o parser do reportlab no meio do build — erro que só apareceria em
    produção, no primeiro cadastro com `&` no nome.
    """
    if valor is None:
        return ""
    return _xml_escape(str(valor))


# --------------------------------------------------------------------------
# Blocos do documento
# --------------------------------------------------------------------------
_logo_cache: tuple[bytes, int, int] | None = None


def _logo_png() -> tuple[bytes, int, int]:
    """PNG do logo já reamostrado, com as dimensões — resolvido UMA vez.

    O cache é de módulo porque o resultado nunca muda: o arquivo é estático e
    entra na imagem Docker junto com o código. Reamostrar a cada PDF seria
    repetir, por request, um trabalho de resultado idêntico.

    O que é cacheado são os BYTES, e não um `ImageReader` ou o `BytesIO`: o
    `platypus.Image` consome o objeto file-like que recebe, então um buffer
    compartilhado funcionaria no primeiro PDF e sairia sem logo no segundo.
    Cada build recebe um `BytesIO` novo por cima dos mesmos bytes.

    Falha não é memorizada de propósito: se o asset sumir, cada chamada tenta e
    loga de novo, em vez de o primeiro erro condenar o processo inteiro a nunca
    mais desenhar o logo.
    """
    global _logo_cache
    if _logo_cache is None:
        from PIL import Image as PILImage  # dependência do próprio reportlab

        alvo = max(1, int(LOGO_LARGURA / inch * LOGO_DPI))
        with PILImage.open(LOGO_PATH) as arquivo:
            imagem = arquivo.convert("RGB")
        if imagem.width > alvo:
            # Pillow >= 9.1 moveu os filtros para `Image.Resampling`, mantendo
            # os aliases antigos; o getattr atende as duas versões.
            resample = getattr(PILImage, "Resampling", PILImage).LANCZOS
            altura = max(1, round(imagem.height * alvo / imagem.width))
            imagem = imagem.resize((alvo, altura), resample)
        buffer = BytesIO()
        imagem.save(buffer, format="PNG")
        _logo_cache = (buffer.getvalue(), imagem.width, imagem.height)
    return _logo_cache


def _logo(largura: float):
    """Logo dimensionado pela proporção real do arquivo.

    A altura sai da imagem em vez de constante: se o arquivo for trocado por
    outro de proporção diferente, a imagem continua sem distorcer. E se o asset
    sumir (alguém podando a imagem Docker, por exemplo), cai no nome da marca em
    texto — um PDF sem logo é muito melhor do que um 500 na rota.
    """
    try:
        dados, orig_l, orig_a = _logo_png()
        img = Image(BytesIO(dados), width=largura,
                    height=largura * orig_a / orig_l)
        img.hAlign = "LEFT"
        return img
    except Exception:
        logger.warning("[QUOTES] logo %s indisponível; PDF sai só com o nome "
                       "da marca", LOGO_PATH, exc_info=True)
        return Paragraph("Café Canastra", _EST_MARCA)


def _numero_proposta(quote: dict) -> str:
    """Número do cabeçalho, com as duas quedas em cascata (ver docstring)."""
    numero = quote.get("bling_proposal_number")
    if numero:
        return str(numero)
    proposta_id = quote.get("bling_proposal_id")
    if proposta_id:
        return str(proposta_id)
    return "-"


def _cabecalho(quote: dict, largura: float) -> list:
    direita = [
        Paragraph(f"ORÇAMENTO Nº {_esc(_numero_proposta(quote))}", _EST_TITULO),
        Paragraph(_esc(_data(quote.get("quoted_at"))), _EST_TITULO_SUB),
    ]
    topo = Table(
        [[_logo(LOGO_LARGURA), direita]],
        colWidths=[largura * 0.5, largura * 0.5],
    )
    topo.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, COR_FILETE),
    ]))

    empresa = Paragraph(
        f"{_esc(EMPRESA_RAZAO)}<br/>{_esc(EMPRESA_CNPJ)}<br/>"
        f"{_esc(EMPRESA_ENDERECO)}<br/>{_esc(EMPRESA_CONTATO)}",
        _EST_EMPRESA,
    )
    return [topo, Spacer(1, 5), empresa, Spacer(1, 12)]


def _cliente(quote: dict, largura: float) -> list:
    """Bloco do cliente. Linha sem valor é omitida — um documento com
    "E-MAIL  -" só chama atenção para o que falta no cadastro."""
    linhas = [
        ("CLIENTE", quote.get("lead_nome")),
        ("CPF/CNPJ", _documento(quote.get("lead_documento"))),
        ("E-MAIL", quote.get("lead_email")),
        ("WHATSAPP", _telefone(quote.get("lead_telefone"))),
        ("A/C", quote.get("aos_cuidados_de")),
    ]
    dados = [
        [Paragraph(rotulo, _EST_ROTULO), Paragraph(_esc(valor), _EST_VALOR)]
        for rotulo, valor in linhas if valor
    ]
    if not dados:
        return []

    tabela = Table(dados, colWidths=[24 * mm, largura - 24 * mm])
    tabela.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return [tabela, Spacer(1, 12)]


_ITENS_CABECALHO = ["Código", "Descrição", "Un", "Qtd", "Valor unit.",
                    "Desc. %", "Total"]


def _itens(items: list[dict], largura: float) -> list:
    if not items:
        return []

    # A API pode devolver as linhas em qualquer ordem (o PostgREST não garante
    # ordenação sem ORDER BY). A coluna `ordem` é quem define a sequência que o
    # vendedor montou na tela.
    ordenados = sorted(items or [], key=lambda i: _dec(i.get("ordem")))

    fixas = [20 * mm, 11 * mm, 15 * mm, 23 * mm, 15 * mm, 25 * mm]
    col_descricao = largura - sum(fixas)
    larguras = [fixas[0], col_descricao] + fixas[1:]

    linhas = [_ITENS_CABECALHO]
    for item in ordenados:
        linhas.append([
            _esc(item.get("codigo") or "-"),
            Paragraph(_esc(item.get("descricao") or "Item"), _EST_ITEM),
            _esc(item.get("unidade") or "UN"),
            _quantidade(item.get("quantidade")),
            _brl(item.get("valor_unitario")),
            _percentual(item.get("desconto_percentual")),
            _brl(item.get("total")),
        ])

    # repeatRows=1: a tabela quebra para a página seguinte repetindo o
    # cabeçalho. Sem isso a segunda página vira uma lista de números sem rótulo
    # nenhum, e o cliente não sabe qual coluna é o desconto.
    tabela = Table(linhas, colWidths=larguras, repeatRows=1)
    tabela.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), COR_ROTULO),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("TEXTCOLOR", (0, 1), (-1, -1), COR_TEXTO),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, COR_FILETE),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, COR_FILETE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (1, 0), (1, -1), 4),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [tabela, Spacer(1, 10)]


def _valores(quote: dict, items: list[dict]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Subtotal, desconto, frete e total.

    Os quatro vêm gravados na `quotes` — o PDF NÃO recalcula, de propósito: o
    número que o cliente lê tem que ser exatamente o que foi enviado ao Bling e
    o que vai ser cobrado. Recalcular aqui abriria a chance de o documento
    divergir do ERP por uma diferença de arredondamento.

    Os fallbacks existem só para linha incompleta (coluna nula em orçamento
    antigo ou em teste): aí sim derivamos dos itens, porque um PDF com "R$ 0,00"
    seria pior do que um PDF com o total somado na hora.
    """
    if quote.get("subtotal") is not None:
        subtotal = _dec(quote.get("subtotal"))
    else:
        subtotal = sum((_dec(i.get("total")) for i in items or []), Decimal("0"))
    desconto = _dec(quote.get("discount_value"))
    frete = _dec(quote.get("freight"))
    if quote.get("total") is not None:
        total = _dec(quote.get("total"))
    else:
        total = subtotal - desconto + frete
    return (subtotal.quantize(_CENT, ROUND_HALF_UP),
            desconto.quantize(_CENT, ROUND_HALF_UP),
            frete.quantize(_CENT, ROUND_HALF_UP),
            total.quantize(_CENT, ROUND_HALF_UP))


def _totais(quote: dict, items: list[dict]) -> list:
    subtotal, desconto, frete, total = _valores(quote, items)

    linhas = [["Subtotal", _brl(subtotal)]]
    # Desconto e frete só entram quando existem (decisão de §7). Linha de
    # "Desconto R$ 0,00" num orçamento sem desconto sugere ao cliente que houve
    # negociação onde não houve.
    if desconto != 0:
        linhas.append(["Desconto", "- " + _brl(abs(desconto))])
    if frete != 0:
        linhas.append(["Frete", _brl(frete)])
    linhas.append(["TOTAL", _brl(total)])

    tabela = Table(linhas, colWidths=[38 * mm, 32 * mm], hAlign="RIGHT")
    tabela.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -2), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -2), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -2), COR_ROTULO),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("TEXTCOLOR", (0, -1), (-1, -1), COR_TEXTO),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, COR_FILETE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    # KeepTogether: o bloco de totais separado da última linha de itens, no pé
    # de uma página, é o tipo de quebra que faz o cliente ligar perguntando
    # qual é o valor.
    return [KeepTogether([tabela]), Spacer(1, 14)]


def _pagamento(quote: dict, largura: float) -> list:
    forma = quote.get("payment_method_name")
    prazos = quote.get("payment_terms")
    parcelas = quote.get("installments") or []
    if not (forma or prazos or parcelas):
        return []

    blocos: list = [Paragraph("PAGAMENTO", _EST_SECAO)]

    resumo = []
    if forma:
        resumo.append(f"Forma: {_esc(forma)}")
    if prazos:
        resumo.append(f"Prazo: {_esc(prazos)} dias")
    if resumo:
        blocos.append(Paragraph(" · ".join(resumo), _EST_VALOR))
        blocos.append(Spacer(1, 4))

    if parcelas:
        total = len(parcelas)
        linhas = [["Parcela", "Vencimento", "Valor"]]
        for i, parcela in enumerate(parcelas, start=1):
            linhas.append([
                f"{i}/{total}",
                _data((parcela or {}).get("dataVencimento")),
                _brl((parcela or {}).get("valor")),
            ])
        tabela = Table(linhas, colWidths=[20 * mm, 32 * mm, 32 * mm],
                       hAlign="LEFT")
        tabela.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 7),
            ("TEXTCOLOR", (0, 0), (-1, 0), COR_ROTULO),
            ("FONTSIZE", (0, 1), (-1, -1), 8.5),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, COR_FILETE),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        blocos.append(tabela)

    return [KeepTogether(blocos), Spacer(1, 12)]


def _observacoes(quote: dict) -> list:
    """Só `notes`. `internal_notes` não é lido em lugar nenhum deste módulo."""
    notes = (quote.get("notes") or "").strip()
    if not notes:
        return []
    texto = _esc(notes).replace("\n", "<br/>")
    return [
        KeepTogether([
            Paragraph("OBSERVAÇÕES", _EST_SECAO),
            Paragraph(texto, _EST_VALOR),
        ]),
        Spacer(1, 12),
    ]


def _desenha_rodape(canvas, doc, *, seller: dict | None) -> None:
    """Rodapé repetido em toda página: vendedor + as duas cláusulas fixas.

    Desenhado no canvas, e não como flowable no fim da história, porque a
    história termina onde o conteúdo acabar — num orçamento de duas páginas as
    cláusulas só sairiam na última, e a primeira página circularia sem elas.
    """
    canvas.saveState()
    x0 = doc.leftMargin
    largura = doc.width

    y = doc.bottomMargin - 6 * mm
    canvas.setStrokeColor(COR_FILETE)
    canvas.setLineWidth(0.6)
    canvas.line(x0, y, x0 + largura, y)

    # Número da página fica ACIMA do filete, no vão entre o fim do frame e a
    # linha — assim nunca colide com o texto das cláusulas, que cresce para
    # baixo e cujo tamanho depende da quebra de linha.
    canvas.setFont("Helvetica", 6.8)
    canvas.setFillColor(COR_ROTULO)
    canvas.drawRightString(x0 + largura, y + 1.6 * mm, str(doc.page))

    blocos = []
    if isinstance(seller, dict):
        nome = _esc(seller.get("nome") or "")
        email = _esc(seller.get("email") or "")
        assinatura = " · ".join(p for p in (nome, email) if p)
        if assinatura:
            blocos.append((f"Vendedor: {assinatura}", _EST_RODAPE_VENDEDOR))
    blocos.extend((_esc(c), _EST_RODAPE) for c in CLAUSULAS)

    y -= 3.5 * mm
    for texto, estilo in blocos:
        paragrafo = Paragraph(texto, estilo)
        _, altura = paragrafo.wrap(largura, RODAPE_ALTURA)
        y -= altura
        paragrafo.drawOn(canvas, x0, y)
        y -= 1.5 * mm
    canvas.restoreState()


# --------------------------------------------------------------------------
# API pública
# --------------------------------------------------------------------------
def build_quote_pdf(quote: dict, items: list[dict], *,
                    seller: dict | None = None,
                    compress: bool = True) -> bytes:
    """Monta o PDF do orçamento e devolve os bytes.

    `quote` é a linha da tabela `quotes` acrescida do que o PDF precisa e a
    tabela não guarda: `lead_nome`, `lead_documento`, `lead_email`,
    `lead_telefone`, `aos_cuidados_de`, `payment_method_name` e `installments`
    (a lista de parcelas já calculada, no mesmo formato que foi enviada ao
    Bling — `[{"dataVencimento": "2026-09-24", "valor": 298.0}]`). Quem monta
    esse dicionário é o router; aqui nada é buscado.

    `items` são as linhas de `quote_items`. `seller` é `{"nome", "email"}` ou
    `None`.

    `compress=False` desliga a compressão do stream de conteúdo. Serve à suíte,
    que lê o texto desenhado direto dos bytes do arquivo em vez de instalar um
    extrator de PDF só para testar — o backend não tem nenhuma dependência de
    teste hoje e não vale a pena ganhar a primeira por isso. Em produção fica
    ligada.

    Não levanta por dado faltando: campo ausente vira traço ou some do
    documento. A rota que chama isto existe para o vendedor baixar o arquivo, e
    um 500 por causa de um CNPJ nulo é pior do que um PDF com uma linha a menos.
    """
    quote = quote or {}
    items = items or []
    buffer = BytesIO()
    numero = _numero_proposta(quote)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGEM,
        rightMargin=MARGEM,
        topMargin=MARGEM,
        # A margem inferior embute a faixa do rodapé fixo: é ela que impede o
        # último item da tabela de invadir as cláusulas.
        bottomMargin=MARGEM + RODAPE_ALTURA,
        title=f"Orçamento {numero}",
        author=EMPRESA_RAZAO,
        subject="Proposta comercial",
        creator="Máquina de Vendas Canastra",
        pageCompression=1 if compress else 0,
    )

    story: list = []
    story += _cabecalho(quote, doc.width)
    story += _cliente(quote, doc.width)
    story += _itens(items, doc.width)
    story += _totais(quote, items)
    story += _pagamento(quote, doc.width)
    story += _observacoes(quote)
    # `doc.build` com história vazia levanta; um orçamento sem item nenhum não
    # deveria existir, mas linha incompleta no banco não pode virar 500.
    if not story:
        story = [Spacer(1, 1)]

    rodape = partial(_desenha_rodape, seller=seller)
    doc.build(story, onFirstPage=rodape, onLaterPages=rodape)
    return buffer.getvalue()
