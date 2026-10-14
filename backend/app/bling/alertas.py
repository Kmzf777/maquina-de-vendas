"""Alerta dos jobs de pedidos do Bling, no mecanismo que o sistema ja tem
(`system_alerts` via `create_system_alert`, que tambem despacha para o Sentry
quando a severidade e `warning`/`critical`).

Dedup por (tipo, conta) numa janela: a varredura roda a cada 1-3 h e a
reconciliacao todo dia; sem dedup, um problema que persiste viraria um banner
novo a cada rodada e o operador passaria a ignorar todos. A conta entra no
dedup porque um problema na conta 2 nao pode esconder um da conta 1.

Fail-soft absoluto: alerta nunca derruba o job que o disparou.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

DEDUP_HORAS = 12


def _ja_alertado(tipo: str, account: str, horas: int, chave: str | None = None) -> bool:
    corte = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    consulta = (get_supabase().table("system_alerts").select("id")
                .eq("type", tipo).eq("resolved", False)
                .eq("metadata->>conta", account))
    if chave is not None:
        consulta = consulta.eq("metadata->>chave", chave)
    res = consulta.gte("created_at", corte).limit(1).execute()
    return bool(getattr(res, "data", None))


def alertar(tipo: str, account: str, titulo: str, mensagem: str, *,
            severidade: str = "warning", metadata: dict | None = None,
            dedup_horas: int = DEDUP_HORAS, chave: str | None = None) -> bool:
    """Grava o alerta (com dedup). Devolve True se gravou. Nunca levanta.

    `chave` refina o dedup alem de (tipo, conta): alertas que REGISTRAM um fato
    por item (pedido ignorado, devolucao parcial de um pedido) usam a chave do
    item, para o segundo pedido nao ser engolido pelo dedup do primeiro. Vai
    gravada em `metadata.chave`.

    O log em ERROR sai SEMPRE, mesmo quando o dedup segura o banner: quem le o
    log do worker precisa ver cada ocorrencia.
    """
    logger.error("[BLING ALERTA] %s conta=%s: %s — %s", tipo, account, titulo, mensagem)
    extra = {"chave": chave} if chave is not None else {}
    try:
        try:
            if dedup_horas and _ja_alertado(tipo, account, dedup_horas, **extra):
                return False
        except Exception:  # noqa: BLE001 — melhor alerta duplicado que nenhum
            logger.warning("[BLING ALERTA] dedup de %s falhou; gravando mesmo assim",
                           tipo, exc_info=True)
        from app.alerts.service import create_system_alert
        create_system_alert(tipo, titulo, mensagem, severity=severidade,
                            metadata={**(metadata or {}), **extra, "conta": account})
        return True
    except Exception:  # noqa: BLE001
        logger.warning("[BLING ALERTA] falha ao gravar o alerta %s", tipo, exc_info=True)
        return False
