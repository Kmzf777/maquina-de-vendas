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
