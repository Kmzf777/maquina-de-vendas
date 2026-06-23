"""Geolocalização aproximada a partir do telefone (DDD → região).

Usado para personalização de outbound: o DDD é o único proxy geográfico disponível
em escala (telefone preenchido em ~99% dos leads; campos de endereço/cidade vazios).
A região é uma APROXIMAÇÃO — o DDD não é a cidade exata e o número pode ter sido
portado. Quem consome este dado deve tratá-lo como hipótese, nunca como certeza.
"""

# DDD → unidade federativa de referência. Fonte: plano nacional de numeração (Anatel).
_DDD_TO_REGION: dict[str, str] = {
    # Sudeste
    "11": "São Paulo", "12": "São Paulo", "13": "São Paulo", "14": "São Paulo",
    "15": "São Paulo", "16": "São Paulo", "17": "São Paulo", "18": "São Paulo",
    "19": "São Paulo",
    "21": "Rio de Janeiro", "22": "Rio de Janeiro", "24": "Rio de Janeiro",
    "27": "Espírito Santo", "28": "Espírito Santo",
    "31": "Minas Gerais", "32": "Minas Gerais", "33": "Minas Gerais",
    "34": "Minas Gerais", "35": "Minas Gerais", "37": "Minas Gerais",
    "38": "Minas Gerais",
    # Sul
    "41": "Paraná", "42": "Paraná", "43": "Paraná", "44": "Paraná",
    "45": "Paraná", "46": "Paraná",
    "47": "Santa Catarina", "48": "Santa Catarina", "49": "Santa Catarina",
    "51": "Rio Grande do Sul", "53": "Rio Grande do Sul",
    "54": "Rio Grande do Sul", "55": "Rio Grande do Sul",
    # Centro-Oeste
    "61": "Distrito Federal",
    "62": "Goiás", "64": "Goiás",
    "63": "Tocantins",
    "65": "Mato Grosso", "66": "Mato Grosso",
    "67": "Mato Grosso do Sul",
    # Norte
    "68": "Acre",
    "69": "Rondônia",
    "91": "Pará", "93": "Pará", "94": "Pará",
    "92": "Amazonas", "97": "Amazonas",
    "95": "Roraima",
    "96": "Amapá",
    "98": "Maranhão", "99": "Maranhão",
    # Nordeste
    "71": "Bahia", "73": "Bahia", "74": "Bahia", "75": "Bahia", "77": "Bahia",
    "79": "Sergipe",
    "81": "Pernambuco", "87": "Pernambuco",
    "82": "Alagoas",
    "83": "Paraíba",
    "84": "Rio Grande do Norte",
    "85": "Ceará", "88": "Ceará",
    "86": "Piauí", "89": "Piauí",
}


def ddd_to_region(phone: str | None) -> str | None:
    """Retorna a UF de referência do DDD de um telefone brasileiro, ou None.

    Aceita o número cru (com/sem '+55', com espaços, parênteses e hífens). Retorna
    None para telefones internacionais, números curtos demais ou DDD desconhecido.
    """
    if not phone:
        return None

    digits = "".join(ch for ch in str(phone) if ch.isdigit())

    # Remove o código de país (55) quando presente num número longo o bastante para
    # ainda sobrar um número nacional válido (>= 12 dígitos: 55 + DDD + 8/9).
    if len(digits) >= 12 and digits.startswith("55"):
        national = digits[2:]
    else:
        national = digits

    # Número nacional válido: 11 (celular: DDD + 9XXXXXXXX) ou 10 (fixo: DDD + 8 díg.).
    if len(national) == 11:
        # Celular brasileiro tem o 9º dígito: o primeiro dígito do assinante é '9'.
        # Filtra falsos positivos (ex.: número estrangeiro de 11 dígitos).
        if national[2] != "9":
            return None
    elif len(national) != 10:
        return None

    ddd = national[:2]
    return _DDD_TO_REGION.get(ddd)
