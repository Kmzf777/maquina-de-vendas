"""Recuperação de buffers órfãos.

Timers de buffer (`_wait_and_flush` em manager.py) são asyncio Tasks in-process:
um restart de container (deploy, crash, OOM) mata a task e a memória de que existe
um timer ativo — mas a lista `buffer:{phone}:{channel_id}` e as chaves auxiliares
(`pending_wamid`/`pending_quoted`) sobrevivem no Redis. Sem essa varredura, essas
mensagens ficam paradas para sempre (nenhum timer vivo vai flushá-las).

Módulo extraído de main.py para ser reutilizável: chamado no startup do processo
(`main.py`, `source="startup"`) e também pelo futuro watchdog periódico (task
separada, `source="watchdog"`, `require_no_deadline=True`), que reconcilia buffers
órfãos enquanto o processo já está rodando — nesse caso NÃO pode brigar com um
timer vivo, por isso ganha a guarda extra do `:deadline` (ver docstring da função).
"""
import asyncio
import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


async def recover_orphaned_buffers(
    redis: aioredis.Redis,
    *,
    require_no_deadline: bool = False,
    source: str = "startup",
) -> int:
    """Varre `buffer:*` no Redis e reprocessa listas órfãs (sem timer vivo).

    - Pula chaves auxiliares (sufixo `:lock`/`:deadline`) e chaves malformadas
      (que não têm exatamente `buffer:{phone}:{channel_id}`).
    - Pula quando `:lock` existe — timer ainda ativo, ele mesmo vai flushar.
    - Se `require_no_deadline=True`, também pula quando `:deadline` existe. Uso:
      o watchdog periódico roda com o processo de pé; se o `:lock` já expirou mas
      o `:deadline` ainda não, a janela de buffer ainda está contando (ex.: reset
      de TTL entre o expire do lock e a próxima mensagem) — não é órfão de
      verdade, e brigar com esse timer duplicaria o flush. No startup
      (`require_no_deadline=False`), não existe timer vivo (o processo acabou de
      subir), então um `:deadline` residual não impede a recuperação.

    Retorna quantos buffers foram recuperados (o caller decide o que fazer com a
    contagem — logar, expor em métrica, etc.).
    """
    from app.buffer.processor import process_buffered_messages

    recovered = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="buffer:*", count=200)
        for key in keys:
            if key.endswith(":lock") or key.endswith(":deadline"):
                continue
            parts = key.split(":", 2)
            if len(parts) != 3:
                continue
            _, phone, channel_id = parts

            lock_key = f"buffer:{phone}:{channel_id}:lock"
            has_lock = await redis.exists(lock_key)
            if has_lock:
                continue

            if require_no_deadline:
                deadline_key = f"buffer:{phone}:{channel_id}:deadline"
                has_deadline = await redis.exists(deadline_key)
                if has_deadline:
                    continue

            messages = await redis.lrange(key, 0, -1)
            if not messages:
                await redis.delete(key)
                continue

            await redis.delete(key)
            pending_wamid = await redis.get(f"pending_wamid:{phone}:{channel_id}")
            pending_quoted = await redis.get(f"pending_quoted:{phone}:{channel_id}")
            await redis.delete(f"pending_wamid:{phone}:{channel_id}")
            await redis.delete(f"pending_quoted:{phone}:{channel_id}")

            combined = "\n".join(messages)
            logger.warning(
                "[BUFFER RECOVERY] source=%s %d mensagem(ns) órfã(s) recuperada(s) para phone=%s channel=%s",
                source, len(messages), phone, channel_id,
            )
            asyncio.create_task(
                process_buffered_messages(
                    phone, combined, channel_id,
                    wamid=pending_wamid,
                    quoted_wamid=pending_quoted,
                )
            )
            recovered += 1

        if cursor == 0:
            break

    if recovered:
        logger.warning(
            "[BUFFER RECOVERY] source=%s %d buffer(s) órfão(s) reprocessado(s)",
            source, recovered,
        )

    return recovered
