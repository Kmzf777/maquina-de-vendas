"""Backfill do Lead Score dos leads que a trava "só B2B" barrou (F3, 06/11/2026).

De 24/10 (publicação do b67f1c6b) até a correção da F3, `aplicar_criterios` recusou o
score de todo lead que tocava os botões do ramo de atacado/PL sem ter `segmento`
gravado — que é justamente o lead novo do anúncio. O log dizia
"score não gravado p/ lead …: não é B2B (segmento=None)".

Este script reconstrói os critérios a partir do `conversations.flow_state` do fluxo de
botões v2 (`respostas` {nó: botão} + `interesse`, o card tocado) e grava com
`source="backfill"` — que NUNCA sobrescreve um critério gravado ao vivo
(`lead_score.repository.save_score_evidence`).

Só a v2 guarda as respostas no estado. Conversas da v1 (`valeria_botoes_v1`) só têm o
nó atual e são contadas como `sem_respostas`, sem gravar nada.

NÃO roda sozinho e NÃO é chamado pelo app. Padrão = ensaio (não escreve). Uso:

    python -m scripts.backfill_score_ramo_f3                  # ensaio, desde 2026-10-24
    python -m scripts.backfill_score_ramo_f3 --desde 2026-10-24 --aplicar
    python -m scripts.backfill_score_ramo_f3 --aplicar --registrar-qualificado

`--registrar-qualificado` grava também o evento `lead_events.qualificado`
(criterio='score') para quem fechar `final_score >= 5` definitivo, como o fluxo ao vivo
faria. Esse evento NÃO muda o que vai para Meta/Google: a varredura de conversões
(`conversions/sweep.py`) lê o carimbo `leads.metadata.handoff`, não `lead_events`. Mas
ele muda o número de "qualificados" do CRM (D2), por isso fica atrás de uma flag.
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter

from app.button_flow import valeria_registry as reg1
from app.button_flow import valeria_registry_v2 as r2
from app.db.supabase import get_supabase
from app.lead_score.repository import save_score_evidence
from app.leads.qualificado import registrar_qualificado, score_qualifica
from app.leads.segmento import SEGMENTOS_B2B

logger = logging.getLogger(__name__)

DESDE_PADRAO = "2026-10-24"
_PAGINA = 500


def _botao(no_id: str, botao_id: str):
    no = r2.NOS.get(no_id) or reg1.NOS.get(no_id)
    for b in getattr(no, "botoes", ()) if no is not None else ():
        if b.id == botao_id:
            return b
    return None


def ramo_do_estado(estado: dict) -> str | None:
    ramo = estado.get("ramo")
    if isinstance(ramo, str) and ramo:
        return ramo
    node = estado.get("node")
    ramo = r2.RAMO_DO_NO.get(node) if isinstance(node, str) else None
    return ramo if ramo and ramo != "entrada" else None


def criterios_do_estado(estado) -> tuple[str | None, dict]:
    """(ramo, critérios) que o `flow_state` da v2 revela. Puro.

    Mesma regra do fluxo ao vivo: `grava` de cada botão respondido; card tocado ou
    "Fazer pedido" no ramo de atacado = `purchase_intent: clear`.
    """
    if not isinstance(estado, dict) or estado.get("flow") != r2.FLOW_ID:
        return None, {}
    ramo = ramo_do_estado(estado)
    criterios: dict = {}
    respostas = estado.get("respostas")
    for no_id, botao_id in (respostas.items() if isinstance(respostas, dict) else ()):
        if not isinstance(botao_id, str):
            continue
        botao = _botao(no_id, botao_id)
        if botao is not None:
            criterios.update(dict(botao.grava))
    if ramo == "atacado" and (estado.get("interesse") or
                              (isinstance(respostas, dict) and respostas.get("VA") == "pedido")):
        criterios["purchase_intent"] = "clear"
    return ramo, criterios


def _conversas(desde: str):
    db = get_supabase()
    inicio = 0
    while True:
        # `conversations` não tem `updated_at`: a data do último turno do fluxo é o
        # `flow_state.updated_at` (ISO em UTC, gravado por `_persistir_estado`), e a
        # comparação de texto ISO no mesmo formato ordena certo.
        res = (db.table("conversations").select("id, lead_id, flow_state")
               .gte("flow_state->>updated_at", desde)
               .order("created_at").order("id").range(inicio, inicio + _PAGINA - 1).execute())
        linhas = res.data or []
        yield from linhas
        if len(linhas) < _PAGINA:
            return
        inicio += _PAGINA


def run(*, desde: str = DESDE_PADRAO, aplicar: bool = False,
        registrar_qualif: bool = False) -> dict:
    conta: Counter = Counter()
    exemplos: list[dict] = []
    for conv in _conversas(desde):
        estado = conv.get("flow_state")
        flow = estado.get("flow") if isinstance(estado, dict) else None
        if flow == reg1.FLOW_ID:
            conta["sem_respostas_v1"] += 1
            continue
        if flow != r2.FLOW_ID:
            continue
        conta["conversas_v2"] += 1
        ramo, criterios = criterios_do_estado(estado)
        if ramo not in SEGMENTOS_B2B or not criterios or not conv.get("lead_id"):
            conta["fora_do_ramo_ou_sem_criterio"] += 1
            continue
        conta["com_criterio"] += 1
        if len(exemplos) < 5:
            exemplos.append({"lead_id": conv["lead_id"], "ramo": ramo, "criterios": criterios})
        if not aplicar:
            continue
        try:
            snap = save_score_evidence(lead_id=conv["lead_id"], updates=criterios,
                                       evidence=None, source="backfill")
            conta["gravados"] += 1
        except Exception as exc:  # um lead ruim não para o lote
            logger.warning("lead %s: %s", conv["lead_id"], exc)
            conta["erros"] += 1
            continue
        if registrar_qualif and score_qualifica(snap):
            if registrar_qualificado(lead_id=conv["lead_id"], criterio="score",
                                     source="score", b2b=True, segmento=ramo):
                conta["qualificados"] += 1
    return {"desde": desde, "aplicar": aplicar, **conta, "exemplos": exemplos}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--desde", default=DESDE_PADRAO)
    p.add_argument("--aplicar", action="store_true", help="grava (sem isto é só ensaio)")
    p.add_argument("--registrar-qualificado", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(desde=a.desde, aplicar=a.aplicar,
                         registrar_qualif=a.registrar_qualificado),
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
