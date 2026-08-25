"""Testes do PDF do orçamento (T2 do plano de propostas comerciais).

O `build_quote_pdf` é puro de propósito: recebe dicionários prontos e o único I/O
que faz é ler o logo do disco. Por isso o documento inteiro é exercitado
chamando a função direto, sem subir a app, sem Supabase e sem Bling.

COMO O TEXTO É EXTRAÍDO SEM DEPENDÊNCIA NOVA
--------------------------------------------
Instalar um extrator de PDF (pypdf, pdfminer) só para a suíte acrescentaria uma
dependência de teste a um backend que hoje não tem nenhuma — e o que precisamos
verificar é bem mais simples do que um parser completo: se determinada frase foi
ou não desenhada na página.

Então o PDF é gerado com `compress=False`, o que deixa o *content stream* de
cada página em texto puro dentro do arquivo. Dali os literais entre parênteses —
que são exatamente os argumentos dos operadores `Tj`/`TJ`, ou seja, tudo que foi
desenhado — são lidos na mão.

Duas armadilhas que o leitor abaixo trata, e que são o motivo de ele não ser um
`re.findall(rb"\\((.*?)\\)")`:

  * o logo entra como stream BINÁRIO comprimido e está cheio de bytes `(` e `)`
    soltos, que arrastariam o scanner para fora de sincronia. Por isso só os
    streams SEM `/Filter` (os de conteúdo, que a falta de compressão deixa
    legíveis) são varridos;
  * uma linha de parágrafo vira UM literal; um texto que quebrou em três linhas
    vira três literais. Por isso os literais são unidos por espaço e o espaço em
    branco é normalizado antes da busca — assim uma cláusula que quebrou de
    linha continua sendo encontrada inteira.
"""
import re

import pytest

from app.quotes.pdf import build_quote_pdf

# Marcador que só existe em `internal_notes`. É deliberadamente artificial: uma
# frase realista ("margem apertada") poderia aparecer no PDF por coincidência e
# o teste de vazamento passaria a acusar falso positivo — ou, pior, a passar por
# acidente. Com um token único, "não está no PDF" significa exatamente isso.
SEGREDO = "MARGEM-INTERNA-XYZZY-42"


# ---------------------------------------------------------------------------
# leitor de texto do PDF
# ---------------------------------------------------------------------------

_STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.S)

# Escapes de string literal do PDF (PDF 32000-1, 7.3.4.2). O `\(` e o `\)`
# importam de verdade aqui: a segunda cláusula fixa tem parênteses no meio.
_ESCAPES = {
    b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
    b"(": b"(", b")": b")", b"\\": b"\\",
}
_OCTAL = b"01234567"


def _content_streams(dados: bytes) -> list[bytes]:
    """Streams sem filtro — na prática, o conteúdo desenhado de cada página."""
    saida = []
    for m in _STREAM.finditer(dados):
        # O dicionário do próprio stream é o trecho entre o último `<<` e o
        # `stream`. Sem recortar no último `<<`, um `/Filter` de um objeto
        # anterior (a imagem, por exemplo) apareceria na janela e descartaria
        # uma página inteira de texto.
        janela = dados[max(0, m.start() - 400):m.start()]
        corte = janela.rfind(b"<<")
        if corte >= 0:
            janela = janela[corte:]
        if b"/Filter" in janela:
            continue
        saida.append(m.group(1))
    return saida


def _literais(stream: bytes) -> list[str]:
    """Todos os literais `( ... )` do stream, com os escapes desfeitos."""
    saida: list[str] = []
    i, n = 0, len(stream)
    while i < n:
        if stream[i:i + 1] != b"(":
            i += 1
            continue
        i += 1
        buf = bytearray()
        nivel = 1
        while i < n:
            c = stream[i:i + 1]
            if c == b"\\":
                prox = stream[i + 1:i + 2]
                if prox in (b"\n", b"\r"):        # quebra de linha escapada
                    i += 2
                    continue
                if prox and prox in _OCTAL:        # \ddd -> byte
                    octal = b""
                    j = i + 1
                    while j < n and len(octal) < 3 and stream[j:j + 1] in _OCTAL:
                        octal += stream[j:j + 1]
                        j += 1
                    buf.append(int(octal, 8) & 0xFF)
                    i = j
                    continue
                buf += _ESCAPES.get(prox, prox)
                i += 2
                continue
            if c == b"(":
                nivel += 1
            elif c == b")":
                nivel -= 1
                if nivel == 0:
                    i += 1
                    break
            buf += c
            i += 1
        # Helvetica padrão é WinAnsi, que coincide com latin-1 em tudo que o
        # documento usa (acentos, ç, º, ·).
        saida.append(buf.decode("latin-1", errors="replace"))
    return saida


def pdf_text(dados: bytes) -> str:
    partes: list[str] = []
    for stream in _content_streams(dados):
        partes.extend(_literais(stream))
    return re.sub(r"\s+", " ", " ".join(partes))


# ---------------------------------------------------------------------------
# fixtures de dados (o mesmo formato que o router vai montar em T5)
# ---------------------------------------------------------------------------

def _quote(**over) -> dict:
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "bling_proposal_number": 137,
        "bling_proposal_id": 987654321,
        "quoted_at": "2026-08-25",
        "status": "rascunho",
        "subtotal": 1234.56,
        "discount_value": 0,
        "discount_unit": "REAL",
        "discount_input": 0,
        "freight": 0,
        "freight_mode": 0,
        "total": 1234.56,
        "payment_method_id": 45,
        "payment_method_name": "Boleto Bancário",
        "payment_terms": "30/60",
        "notes": "Entrega combinada direto com o comprador.",
        "internal_notes": SEGREDO,
        "lead_nome": "Padaria do Zé & Filhos Ltda",
        "lead_documento": "12.345.678/0001-90",
        "lead_email": "compras@padariadoze.com.br",
        "lead_telefone": "5534999998888",
        "aos_cuidados_de": "José da Silva",
        "installments": [
            {"dataVencimento": "2026-09-24", "valor": 617.28},
            {"dataVencimento": "2026-10-24", "valor": 617.28},
        ],
    }
    base.update(over)
    return base


def _items() -> list[dict]:
    return [
        {"codigo": "CAN-250", "descricao": "Café Canastra Torrado e Moído 250g",
         "unidade": "UN", "quantidade": 24, "valor_unitario": 38.90,
         "desconto_percentual": 0, "total": 933.60, "ordem": 0},
        {"codigo": "CAN-GR1", "descricao": "Café Canastra Grãos 1kg",
         "unidade": "UN", "quantidade": 3, "valor_unitario": 111.00,
         "desconto_percentual": 9.6, "total": 300.96, "ordem": 1},
    ]


VENDEDOR = {"nome": "Arthur Boaventura", "email": "arthur@cafecanastra.com"}


def _build(**over) -> bytes:
    return build_quote_pdf(_quote(**over), _items(), seller=VENDEDOR,
                           compress=False)


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

def test_devolve_bytes_de_pdf():
    dados = _build()
    assert isinstance(dados, bytes)
    assert dados.startswith(b"%PDF")


def test_o_leitor_de_texto_do_teste_realmente_le_alguma_coisa():
    """Guarda do próprio instrumento.

    Todos os testes de ausência ("X não está no PDF") passariam trivialmente se
    o leitor devolvesse string vazia — por exemplo se uma versão futura do
    reportlab passasse a comprimir o conteúdo mesmo com `compress=False`. Este
    teste é o que impede a suíte de virar decoração silenciosa.
    """
    texto = pdf_text(_build())
    assert len(texto) > 200
    assert "Café Canastra" in texto


# ---------------------------------------------------------------------------
# conteúdo obrigatório
# ---------------------------------------------------------------------------

def test_o_logo_entra_como_imagem_no_documento():
    """O logo é reamostrado e guardado num cache de módulo antes de ser
    embutido. Se esse caminho quebrar, o `_logo` cai no nome da marca em texto
    e o PDF sai — sem logo — sem que nenhum outro teste perceba. Duas gerações
    seguidas porque a segunda é a que usa o `ImageReader` já em cache.
    """
    primeiro = _build()
    segundo = _build()
    assert b"/Subtype /Image" in primeiro
    assert b"/Subtype /Image" in segundo


def test_traz_os_dados_da_empresa():
    texto = pdf_text(_build())
    assert "Boaventura Cafés Especiais Ltda" in texto
    assert "24.252.228/0001-37" in texto
    assert "comercial@cafecanastra.com" in texto


def test_traz_as_duas_clausulas_fixas():
    """As cláusulas quebram de linha; o leitor as remonta juntando os literais."""
    texto = pdf_text(_build())
    assert "Preços sujeitos a alteração sem aviso prévio." in texto
    assert ("Tributos sob a venda já incluídos (não incluído possíveis "
            "diferenças de alíquotas de ICMS, consulte seu contador pois "
            "depende do seu regime tributário e das regras de seu estado)."
            ) in texto


def test_traz_o_vendedor_no_rodape():
    texto = pdf_text(_build())
    assert "Arthur Boaventura" in texto
    assert "arthur@cafecanastra.com" in texto


def test_traz_cliente_itens_e_observacoes():
    texto = pdf_text(_build())
    assert "Padaria do Zé & Filhos Ltda" in texto      # `&` não quebra o parser
    assert "12.345.678/0001-90" in texto
    assert "José da Silva" in texto                     # A/C
    assert "Café Canastra Torrado e Moído 250g" in texto
    assert "CAN-GR1" in texto
    assert "Entrega combinada direto com o comprador." in texto


def test_numero_e_data_no_cabecalho():
    texto = pdf_text(_build())
    assert "ORÇAMENTO Nº 137" in texto
    assert "25/08/2026" in texto


def test_pagamento_com_forma_e_parcelas():
    texto = pdf_text(_build())
    assert "Boleto Bancário" in texto
    assert "24/09/2026" in texto
    assert "24/10/2026" in texto
    assert "R$ 617,28" in texto


def test_dinheiro_em_pt_br_com_separador_de_milhar():
    """`locale` do sistema não é usado — o container não tem pt-BR instalado."""
    texto = pdf_text(_build())
    assert "R$ 1.234,56" in texto


# ---------------------------------------------------------------------------
# o que NÃO pode entrar
# ---------------------------------------------------------------------------

def test_observacao_interna_nunca_entra_no_pdf():
    """`internal_notes` é anotação do vendedor (margem, histórico) e o PDF vai
    para a mão do cliente. Vazar aqui é incidente comercial, não bug estético."""
    texto = pdf_text(_build())
    assert SEGREDO not in texto


def test_desconto_e_frete_zerados_nao_aparecem():
    texto = pdf_text(_build(discount_value=0, freight=0))
    assert "Subtotal" in texto
    assert "Desconto" not in texto
    assert "Frete" not in texto


def test_desconto_e_frete_diferentes_de_zero_aparecem():
    texto = pdf_text(_build(discount_value=100, freight=57.30,
                            total=1191.86))
    assert "Desconto" in texto
    assert "- R$ 100,00" in texto
    assert "Frete" in texto
    assert "R$ 57,30" in texto
    assert "R$ 1.191,86" in texto


# ---------------------------------------------------------------------------
# robustez — nada aqui pode levantar exceção
# ---------------------------------------------------------------------------

def test_proposta_sem_numero_cai_no_id_do_bling():
    """O POST do Bling devolve só o `id`; o `numero` vem de um GET seguinte que
    é best-effort. Um orçamento cujo GET falhou tem que gerar PDF do mesmo
    jeito — o vendedor não pode ficar sem documento por causa disso."""
    texto = pdf_text(_build(bling_proposal_number=None))
    assert "987654321" in texto


def test_proposta_sem_numero_e_sem_id_usa_traco():
    texto = pdf_text(_build(bling_proposal_number=None, bling_proposal_id=None))
    assert "ORÇAMENTO Nº -" in texto


def test_sem_vendedor_e_sem_campos_opcionais_nao_levanta():
    quote = _quote(notes="", aos_cuidados_de=None, lead_email=None,
                   lead_telefone=None, lead_documento=None,
                   payment_method_name=None, installments=[])
    dados = build_quote_pdf(quote, _items(), seller=None, compress=False)
    assert dados.startswith(b"%PDF")
    # As cláusulas fixas continuam no rodapé mesmo sem vendedor.
    assert "Preços sujeitos a alteração sem aviso prévio." in pdf_text(dados)


def test_quote_minimo_e_sem_itens_nao_levanta():
    """Defesa contra linha incompleta vinda do banco (colunas nulas)."""
    dados = build_quote_pdf({}, [], seller=None, compress=False)
    assert dados.startswith(b"%PDF")


@pytest.mark.parametrize("data_ruim", ["", None, "data-invalida", "2026-08-25T13:45:00+00:00"])
def test_data_estranha_nao_derruba_o_pdf(data_ruim):
    dados = _build(quoted_at=data_ruim)
    assert dados.startswith(b"%PDF")


def test_tabela_de_itens_repete_o_cabecalho_na_quebra_de_pagina():
    """Com 60 itens o documento passa de uma página; o cabeçalho da tabela tem
    que reaparecer, senão a segunda página vira uma lista de números sem
    rótulo."""
    itens = [
        {"codigo": f"COD-{i:03d}", "descricao": f"Item de catálogo número {i}",
         "unidade": "UN", "quantidade": 1, "valor_unitario": 10.0,
         "desconto_percentual": 0, "total": 10.0, "ordem": i}
        for i in range(60)
    ]
    texto = pdf_text(build_quote_pdf(_quote(), itens, seller=VENDEDOR,
                                     compress=False))
    assert texto.count("Descrição") >= 2


def test_itens_saem_na_ordem_da_coluna_ordem():
    """A API pode devolver as linhas em qualquer ordem; a `ordem` é quem manda."""
    itens = list(reversed(_items()))
    texto = pdf_text(build_quote_pdf(_quote(), itens, seller=VENDEDOR,
                                     compress=False))
    assert texto.index("CAN-250") < texto.index("CAN-GR1")


def test_documento_do_cliente_sai_formatado():
    """CNPJ e CPF sao guardados so em digitos, mas o orcamento vai para o
    cliente, que confere o proprio documento formatado como esta na nota."""
    from app.quotes.pdf import _documento

    assert _documento("12345678000190") == "12.345.678/0001-90"
    assert _documento("12345678901") == "123.456.789-01"
    # Ja formatado na origem: normaliza em vez de duplicar pontuacao.
    assert _documento("12.345.678/0001-90") == "12.345.678/0001-90"
    # Contagem de digitos desconhecida volta intacta — melhor cru que deformado.
    assert _documento("XPTO-999") == "XPTO-999"
    assert _documento(None) == ""
    assert _documento("") == ""
