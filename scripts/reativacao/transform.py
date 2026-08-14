# scripts/reativacao/transform.py
"""Logica pura da preparacao de reativacao: sem I/O, sem SQL, sem rede.

Tudo aqui e testavel isoladamente. Decisoes de conteudo (qual nome usar, como
classificar o produto, o que escrever no briefing) vivem neste modulo; o
generate_sql.py apenas consome.
"""
import re
import unicodedata

# Sufixos e termos empresariais que poluem uma saudacao de WhatsApp.
SUFIXOS_EMPRESARIAIS = (
    r"\b(ltda|eireli|me|epp|s/?a|mei|com[eé]rcio|comercial|distribuidora|"
    r"ind[uú]stria|e servi[cç]os|do brasil|importa[cç][aã]o)\b"
)


def normalizar_telefone(valor):
    """Devolve o telefone em E.164 sem '+', ou '' se nao for normalizavel.

    O CRM conviveu com formatos diferentes (13, 11 e 10 digitos), e a coluna
    phone e UNIQUE pela string exata — normalizar evita duplicata logica.
    """
    digitos = re.sub(r"\D", "", valor or "")
    if not digitos:
        return ""
    if len(digitos) in (10, 11):
        return "55" + digitos
    if len(digitos) in (12, 13):
        # Ja esta em formato internacional (E.164 sem '+') — nao adicionar 55.
        # Cobre tanto BR ja prefixado (55XX9XXXXXXXX) quanto numeros de
        # outros paises que o CRM tambem guarda, ex.: Portugal (351...) e
        # Emirados Arabes (971...). Prefixar 55 aqui corromperia o numero.
        return digitos
    return ""


# DDDs em uso no Brasil. Um numero de 10-11 digitos sem DDI cujo prefixo nao
# esteja aqui nao e brasileiro — prefixar 55 fabricaria um celular real de
# outra pessoa (ex.: +31 6 39758812 da Holanda viraria DDD 31, Belo Horizonte).
DDD_VALIDOS = frozenset((
    "11", "12", "13", "14", "15", "16", "17", "18", "19",
    "21", "22", "24", "27", "28",
    "31", "32", "33", "34", "35", "37", "38",
    "41", "42", "43", "44", "45", "46", "47", "48", "49",
    "51", "53", "54", "55",
    "61", "62", "63", "64", "65", "66", "67", "68", "69",
    "71", "73", "74", "75", "77", "79",
    "81", "82", "83", "84", "85", "86", "87", "88", "89",
    "91", "92", "93", "94", "95", "96", "97", "98", "99",
))


def normalizar_telefone_canonico(valor):
    """E.164 sem '+' com o 9o digito injetado APENAS em celular brasileiro.

    Converge com backend/app/leads/service.py::normalize_phone para celulares —
    a forma que o webhook do WhatsApp grava em leads.phone — e diverge dele de
    proposito em fixos. Nao cobre BSUID nem telefone dobrado, que sao entradas
    do webhook, nunca do CSV do Bling.

    Por que a forma de 13 digitos importa: gravar um celular com 12 digitos cria
    duplicata logica — quando a pessoa responder, o webhook grava o registro de
    13 digitos e a conversa fica partida entre dois leads (leads.phone e UNIQUE
    pela string exata).

    Por que fixo NAO recebe o 9: no plano de numeracao brasileiro o assinante
    movel comeca em 6-9 e o fixo em 2-5. Injetar o 9 em (34) 3215-1234 produz
    34 9 3215-1234 — um celular valido que provavelmente pertence a OUTRA
    pessoa. Como este lote alimenta disparo de template, isso mandaria
    marketing para estranhos. Sao 244 fixos nos 1.218 leads do lote.
    normalize_phone tem esse defeito; aqui ele nao e reproduzido.

    Como o DDI e detectado: '+' ou '00' no inicio do valor bruto, lidos ANTES
    do re.sub que os apaga. Com DDI o numero passa como esta — nunca ganha 55 —
    e so e validado por comprimento (8-15, a faixa da E.164). Sem DDI, um numero
    de 10-11 digitos precisa comecar por DDD em uso no Brasil; se nao comecar e
    recusado ('') em vez de virar um BR fabricado: era assim que +31 6 39758812
    (Holanda) virava 5531639758812, um celular valido com DDD 31 (Belo
    Horizonte), que receberia o disparo de marketing no lugar do dono real.

    Limite conhecido: a protecao depende do '+'/'00' estar presente. Um numero
    estrangeiro sem DDI cujo prefixo coincida com um DDD brasileiro (ex.: o
    33 6 1234-5678 da Franca colide com o DDD 33, Espirito Santo) ainda ganha
    o 55 — sem o DDI a ambiguidade e irredutivel.
    """
    bruto = (valor or "").strip()
    # O '+' e o '00' dizem "ja tem DDI". Precisam ser lidos ANTES do re.sub,
    # que os apaga — foi assim que 17 numeros estrangeiros viravam celular BR.
    tem_ddi = bruto.startswith("+") or bruto.startswith("00")
    digitos = re.sub(r"\D", "", bruto)
    if not digitos:
        return ""

    if tem_ddi:
        if digitos.startswith("00"):
            digitos = digitos[2:]
        # Ja em E.164: nunca prefixar 55, e aceitar o comprimento que vier.
        if not 8 <= len(digitos) <= 15:
            return ""
    else:
        # Zero inicial e prefixo de tronco/selecao de operadora nos exports do
        # Bling ("0 34 9146-1669"), nao parte do numero.
        if digitos.startswith("0"):
            digitos = digitos[1:]
        if len(digitos) in (10, 11):
            if digitos[:2] not in DDD_VALIDOS:
                return ""
            digitos = "55" + digitos
        if len(digitos) not in (12, 13):
            return ""

    if (len(digitos) == 12 and digitos.startswith("55")
            and digitos[2:4] in DDD_VALIDOS and digitos[4] in "6789"):
        digitos = digitos[:4] + "9" + digitos[4:]
    return digitos


def escolher_saudacao(nome_crm, nome_bling):
    """Nome para a variavel {{1}} do template.

    O CRM guarda como a pessoa se identificou ('Carina'); o Bling guarda a razao
    social ('Divina Terra - BALNEARIO CAMBORIU'). Para uma mensagem que pergunta
    'Falo com {{1}} neste numero?', o nome da pessoa e sempre melhor.
    """
    if (nome_crm or "").strip():
        return nome_crm.strip()
    base = (nome_bling or "").strip()
    base = re.sub(r"^\d[\d.\-/]*\s*", "", base)          # codigo/CNPJ no inicio
    base = re.sub(SUFIXOS_EMPRESARIAIS, "", base, flags=re.IGNORECASE)
    base = re.sub(r"[\s.,\-]+$", "", base).strip()
    base = re.sub(r"\s{2,}", " ", base)
    if base.isupper():
        base = base.title()
    return base or (nome_bling or "").strip()


# Ordem importa: o primeiro padrao que casar define o perfil. Capsula vem antes
# de granel porque e o sinal mais especifico (mercado e recompra diferentes:
# 29,2% contra 50,7% do grao 1kg).
PERFIS_PRODUTO = (
    ("cápsula", (r"c[aá]psul",)),
    ("café verde/industrial", (r"\bcru\b", r"beneficiad")),
    ("drip", (r"\bdrip\b",)),
    ("granel/volume", (r"granel", r"\b2\s*kg\b")),
    ("kit/presente", (r"\bkit\b", r"caneca", r"camiseta")),
)


def classificar_perfil(produto):
    """Rotula perfis de produto que exigem abordagem diferente do café torrado.

    Retorna '' para o café convencional (186 dos 232 casos), onde a linha PERFIL
    do briefing e omitida.
    """
    texto = _sem_acento(produto)
    for rotulo, padroes in PERFIS_PRODUTO:
        for padrao in padroes:
            if re.search(_sem_acento(padrao), texto):
                return rotulo
    return ""


def _sem_acento(texto):
    """Minusculas sem diacriticos, para casar 'Cápsula' e 'Capsula' igualmente."""
    normalizado = unicodedata.normalize("NFKD", texto or "")
    return normalizado.encode("ascii", "ignore").decode().lower()


PREFIXO_BRIEFING = "REATIVAÇÃO 10/08/2026 — lote reativacao_bling_2026-08-10"


def _num(valor):
    """Converte string numerica (formato BR ou US) para float. Invalido -> 0.0.

    Regra para distinguir os formatos quando '.' e ',' aparecem juntos: o que
    aparecer por ultimo na string e o separador decimal, o outro e separador de
    milhar (ex.: '1.234,56' -> 1234.56; '1,234.56' -> 1234.56). Se so houver
    ',', ela e tratada como separador decimal (ex.: '1234,56' -> 1234.56).
    """
    texto = str(valor or "0").strip()
    if "." in texto and "," in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _int(valor):
    try:
        return int(_num(valor))
    except ValueError:
        return 0


def formatar_reais(valor):
    """1234.56 -> '1.234,56' (padrao brasileiro).

    O '@' e um pivo: troca-se ',' por '@', depois '.' por ',', depois '@' por
    '.', invertendo os separadores sem colisao.
    """
    return "{:,.2f}".format(_num(valor)).replace(",", "@").replace(".", ",").replace("@", ".")


def formatar_inteiro(valor):
    """1200 -> '1.200'."""
    return "{:,}".format(_int(valor)).replace(",", ".")


def formatar_data(iso):
    """'2019-07-23' -> '23/07/2019'. Devolve '' para vazio/invalido.

    O Bling usa '0000-00-00' (e variantes com ano zero, ex.: '0000-01-01') como
    sentinela de data nao definida — ano zero nunca e uma data valida, entao e
    tratado como invalido tambem.
    """
    partes = (iso or "").strip()[:10].split("-")
    if len(partes) != 3 or not all(partes):
        return ""
    if partes[0] == "0000":
        return ""
    return "%s/%s/%s" % (partes[2], partes[1], partes[0])


def formatar_documento(doc):
    """CNPJ/CPF so com digitos -> mascarado. Devolve o original se nao casar."""
    d = re.sub(r"\D", "", doc or "")
    if len(d) == 14:
        return "%s.%s.%s/%s-%s" % (d[:2], d[2:5], d[5:8], d[8:12], d[12:])
    if len(d) == 11:
        return "%s.%s.%s-%s" % (d[:3], d[3:6], d[6:9], d[9:])
    return doc or ""


def montar_briefing(dados, prefixo=None):
    """Monta o texto da nota que o vendedor le no card do lead.

    `prefixo` permite reuso entre lotes (o de 10/08 usa o default). Regras em
    docs/superpowers/specs/2026-08-08-reativacao-crm-preparacao-design.md e
    docs/superpowers/specs/2026-08-14-reativacao-bling-lote-completo-design.md
    """
    linhas = []

    motivo = (dados.get("motivo_exclusao") or "").strip()
    if motivo:
        linhas.append("⚠ FORA DA CAMPANHA: %s" % motivo)
        linhas.append("")

    linhas.append(prefixo or PREFIXO_BRIEFING)
    linhas.append("")

    # Fix round 3 (menor): PERFIL precisa renderizar sempre que o produto e
    # conhecido, independente de o lead ter historico de compra — antes,
    # essa linha vivia dentro do ramo "tem compra" e os 3 dos 46 leads de
    # perfil atipico que nunca compraram (produto_para_citar preenchido
    # mesmo sem faturamento) ficavam sem a linha PERFIL. Calcular produto e
    # perfil aqui, fora dos dois ramos, e so decidir a linha no final.
    produto = (dados.get("produto_para_citar") or "").strip()
    perfil = classificar_perfil(produto)

    if _num(dados.get("total_gasto")) > 0:
        dias = formatar_inteiro(dados.get("dias_sem_comprar"))
        data = formatar_data(dados.get("ultima_compra"))
        sufixo_data = " (última compra: %s)" % data if data else ""
        linhas.append("CLIENTE INATIVO há %s dias%s" % (dias, sufixo_data))
        pedidos = _int(dados.get("pedidos_faturados"))
        linhas.append("Histórico: %d %s · R$ %s · ticket médio R$ %s" % (
            pedidos,
            "pedido" if pedidos == 1 else "pedidos",
            formatar_reais(dados.get("total_gasto")),
            formatar_reais(dados.get("ticket_medio")),
        ))
        if produto:
            qtd = _int(dados.get("qtd_top1"))
            sufixo = " (%s un)" % formatar_inteiro(qtd) if qtd else ""
            linhas.append("Comprava: %s%s" % (produto, sufixo))
    else:
        linhas.append("LEAD SEM COMPRA — cadastrado no Bling, nunca faturou")

    if perfil:
        linhas.append("PERFIL: %s — abordagem diferente do café torrado de varejo" % perfil)

    linhas.append("")

    doc_bruto = dados.get("cpf_cnpj")
    qtd_digitos = len(re.sub(r"\D", "", doc_bruto or ""))
    if qtd_digitos == 14:
        rotulo_doc = "CNPJ"
    elif qtd_digitos == 11:
        rotulo_doc = "CPF"
    else:
        rotulo_doc = ""
    doc_formatado = formatar_documento(doc_bruto)
    partes_cadastro = ["Cadastro:"]
    if rotulo_doc:
        partes_cadastro.append(rotulo_doc)
    if doc_formatado:
        partes_cadastro.append(doc_formatado)
    cadastro = " ".join(partes_cadastro)
    local = "/".join(p for p in [(dados.get("cidade") or "").strip(),
                                 (dados.get("uf") or "").strip()] if p)
    if local:
        cadastro += " · %s" % local
    linhas.append(cadastro)

    cnae = (dados.get("cnae") or "").strip()
    porte = (dados.get("porte") or "").strip()
    if cnae or porte:
        linhas.append("Atividade: %s" % " · ".join(p for p in [cnae, porte] if p))

    if _num(dados.get("valor_vencido")) > 0:
        linhas.append("DÉBITO VENCIDO: R$ %s (%d títulos, máx %s dias de atraso) — tratar como cobrança" % (
            formatar_reais(dados.get("valor_vencido")),
            _int(dados.get("titulos_vencidos")),
            (dados.get("dias_atraso_max") or "?"),
        ))
    else:
        linhas.append("NF-e emitidas: %d · Orçamentos: %d · Sem débito em aberto" % (
            _int(dados.get("qtd_nfe")), _int(dados.get("orcamentos"))))

    vendedor = (dados.get("vendedor") or "").strip()
    if vendedor:
        linhas.append("Vendedor anterior: %s" % vendedor)

    icp = (dados.get("icp_score") or "").strip()
    if icp:
        linhas.append("ICP %s (%s) · id_bling %s" % (
            icp,
            dados.get("icp_faixa") or "?",
            dados.get("id_bling") or "?",
        ))
    else:
        # Lotes sem enriquecimento de ICP (ex.: reativacao_bling_2026-08-14)
        # nao devem renderizar "ICP ? (?)".
        linhas.append("id_bling %s" % (dados.get("id_bling") or "?"))

    return "\n".join(linhas)


# Aliases publicos dos parsers: outros modulos do pacote (lote_completo.py)
# precisam deles, e depender de nome com underscore atravessa fronteira de API.
parse_numero = _num
parse_inteiro = _int
