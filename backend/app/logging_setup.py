"""Logging estruturado (stdlib, sem dependência): uma linha JSON por registro.

Produção emite JSON (parseável por máquina — `docker service logs ... | jq`);
dev local pode voltar ao texto com LOG_FORMAT=text no .env.local. As mensagens
existentes não mudam — os prefixos-tag ([FOLLOWUP], [BROADCAST], ...) seguem
dentro do campo `msg`, grep-áveis como sempre.
"""
import json
import logging
import os
from datetime import datetime, timezone

_TEXT_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    """Configura o root logger. LOG_FORMAT=text preserva o formato antigo (dev)."""
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    if os.environ.get("LOG_FORMAT", "json").lower() == "text":
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))
    else:
        handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # O httpx loga em INFO a URL COMPLETA de cada request ("HTTP Request: GET https://...").
    # Com o token na query string (`access_token=` da Graph, em campaigns/meta_ads.py) o segredo
    # ia parar no log do worker. Os clientes passaram a mandar o token no header, mas isto fica
    # como segunda trava: só WARNING ou acima desses dois loggers chega ao log.
    for nome in ("httpx", "httpcore"):
        logging.getLogger(nome).setLevel(logging.WARNING)
