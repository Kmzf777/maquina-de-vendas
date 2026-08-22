"""Conversao de data para o formato que a API do Bling exige.

Modulo pequeno e sem dependencias de `sync.py`/`products.py` de proposito:
`sync.py` importa `sync_products` de `products.py`, entao se a conversao
morasse em `sync.py` e `products.py` precisasse importa-la de volta, isso
seria um import circular.
"""
from datetime import datetime, timedelta, timezone

# Margem de seguranca ao converter `last_sync_at` (gravado em UTC) para o
# formato que `dataAlteracaoInicial` exige no Bling ('Y-m-d H:i:s', SEM
# timezone). O Bling interpreta essa string na hora da conta (Brasil,
# UTC-3) -- entao formatar o UTC cru e mandar como se ja fosse hora local
# faria a janela comecar 3h ADIANTE do pretendido (o Bling soma +3h ao
# converter para UTC internamente), perdendo em silencio tudo que mudou
# nesse intervalo. Subtrair umas horas antes de formatar cobre esse
# deslocamento de fuso com folga, mais qualquer deriva de relogio/latencia
# entre o `started_at` salvo e o proximo sync. O vies e sempre para tras
# (reprocessar registro repetido e inofensivo -- todo sync grava por upsert
# com on_conflict="id"), nunca para frente (perder registro e dado errado
# no CRM sem aviso).
BLING_DATE_MARGIN_HOURS = 6


def to_bling_datetime(last_sync_at: str | None,
                       *, margin_hours: int = BLING_DATE_MARGIN_HOURS) -> str | None:
    """Converte `last_sync_at` (ISO 8601, como gravado em `bling_sync_state`)
    para o formato 'Y-m-d H:i:s' que `dataAlteracaoInicial`/`dataAlteracaoFinal`
    exigem no Bling.

    Devolve None para entrada vazia ou invalida -- o chamador deve cair para o
    caminho `full` (criterio=Todos) em vez de mandar lixo ao Bling, que
    responde 400 para formato invalido.
    """
    if not last_sync_at:
        return None
    try:
        dt = datetime.fromisoformat(last_sync_at)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    dt -= timedelta(hours=margin_hours)
    return dt.strftime("%Y-%m-%d %H:%M:%S")
