"""Mecanismos comuns aos classificadores de botões (Recuperação e ValerIA v2).

Extraídos de `classifier.py` sem mudar comportamento: teto de gasto, registro em
`token_usage`, chamada com timeout e leitura de env. Cada classificador continua
dono do seu prompt, da sua validação e do seu `call_type`.

Detalhe que importa para os testes: `chamar_com_timeout` recebe a função de geração
como argumento em vez de importar `generate` aqui. Assim cada classificador segue
chamando o `generate` do PRÓPRIO módulo, e os patches existentes
(`app.button_flow.classifier.generate`) continuam valendo.

Os motivos de cada mecanismo (FinOps P0 de 12/07, resumo off-book, worker pendurado,
`extra: "allow"` no Settings) estão no cabeçalho de `classifier.py`.
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

PREFIXO_PADRAO = "[BUTTON FLOW]"


def budget_estourado(prefixo_log: str = PREFIXO_PADRAO) -> bool:
    """True se o kill-switch diário está ativo. Fail-open: erro aqui não bloqueia.

    Import tardio pelo mesmo motivo de app/buffer/parking.py:438 — budget_guard puxa
    o cliente Supabase e não deve carregar no import deste módulo.
    """
    try:
        from app.agent import budget_guard
        return budget_guard.is_exceeded()
    except Exception as exc:
        logger.warning("%s falha ao ler o budget guard (seguindo): %s", prefixo_log, exc)
        return False


def contabilizar(
    resultado, modelo_usado: str, lead_id: str | None, *,
    call_type: str, prefixo_log: str = PREFIXO_PADRAO,
) -> None:
    """Grava a linha em token_usage. Fail-soft: contabilidade nunca derruba o turno."""
    try:
        uso = getattr(resultado, "usage_metadata", None)
        if not uso:
            return
        from app.agent import token_tracker
        token_tracker.track_token_usage(
            lead_id=lead_id,
            stage="",
            model=modelo_usado,
            call_type=call_type,
            prompt_tokens=uso.prompt_token_count or 0,
            completion_tokens=uso.billed_output_tokens or 0,
            cached_tokens=uso.cached_content_token_count or 0,
            reasoning_tokens=uso.thoughts_token_count or 0,
        )
    except Exception as exc:
        logger.warning("%s falha ao contabilizar token_usage (ignorado): %s", prefixo_log, exc)


async def chamar_com_timeout(gerar, modelo_usado: str, *, timeout: float, **kwargs):
    """`await gerar(modelo_usado, **kwargs)` com teto de espera.

    `gemini_client.generate` não tem knob de timeout. Exceções (inclusive
    `asyncio.TimeoutError`) sobem: quem chama decide o fallback (os dois
    classificadores devolvem RUIDO).
    """
    return await asyncio.wait_for(gerar(modelo_usado, **kwargs), timeout=timeout)


def ler_modelo(nome_env: str, padrao: str) -> str:
    """Modelo vindo do env por `os.getenv` (nunca `Settings`); vazio → padrão."""
    return (os.getenv(nome_env) or "").strip() or padrao


def ler_timeout(nome_env: str, padrao: float, prefixo_log: str = PREFIXO_PADRAO) -> float:
    """Timeout em segundos vindo do env; ausente, inválido ou <= 0 → padrão."""
    bruto = (os.getenv(nome_env) or "").strip()
    if not bruto:
        return padrao
    try:
        valor = float(bruto)
    except ValueError:
        logger.warning(
            "%s %s invalido (%r) — usando %.1fs", prefixo_log, nome_env, bruto, padrao,
        )
        return padrao
    return valor if valor > 0 else padrao
