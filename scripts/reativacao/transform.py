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
    if digitos.startswith("55") and len(digitos) in (12, 13):
        return digitos
    if len(digitos) in (10, 11):
        return "55" + digitos
    if len(digitos) in (12, 13):
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
