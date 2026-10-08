"""Runner da ValerIA de botões v2 — stub — substituído na Task 8.

Existe só para o despacho do processor (`_runner_do_fluxo`) já ter o nome do runner
da v2 para importar. Não faz nada e devolve None ("atendeu o turno"), então com o
perfil apontando para a v2 antes da Task 8 o inbound é absorvido em silêncio — por
isso a v2 não deve ser ativada em canal nenhum até a Task 8 entrar.
"""
from __future__ import annotations


async def processar_inbound(**kwargs):
    """stub — substituído na Task 8."""
    return None
