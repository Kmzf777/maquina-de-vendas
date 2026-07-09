"""Config-as-code da cadência multi-touch (Feature 3).

Esqueleto determinístico (offset + objetivo por toque); o TEXTO de cada toque é
gerado pelo LLM em runtime a partir do objetivo (Next Best Action). Ver
docs/superpowers/specs/2026-06-26-multitouch-cadence-design.md
"""
from __future__ import annotations

import random as _random
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.follow_up.service import _clamp_to_business_window


@dataclass(frozen=True)
class Touch:
    sequence: int
    offset: timedelta
    jitter_minutes: tuple[int, int] | None
    objective: str
    objective_prompt: str


# Espaçamento mínimo entre toques consecutivos (R2): impede encavalamento quando o
# clamp empurra vários toques para a mesma abertura comercial (ex.: seg 09h pós fim de semana).
MIN_GAP = timedelta(hours=2)

# Nudge outbound "Sim-e-sumiu" (Onda 2, auditoria 08/07): o lead confirmou a identidade
# ("Sim"), ouviu o pitch e sumiu. O T2 padrão (D+1 clampado) cai FORA da janela de 24h da
# Meta para respostas noturnas — viraria template de reabertura em vez de mensagem livre.
# +18h clampado fica dentro da janela p/ qualquer resposta entre ~9h e ~22h, no calor da
# conversa. Substitui o T1 SUPRIMIDO da cadência fria só no fluxo outbound.
OUTBOUND_NUDGE = Touch(
    1, timedelta(hours=18), None, "retomar_pos_sim",
    "Este é o toque de RETOMADA PÓS-CONFIRMAÇÃO: o lead confirmou que era ele, trocou "
    "algumas mensagens e silenciou depois da apresentação. Retome ancorando no ÚLTIMO "
    "assunto que ELE trouxe (releia as mensagens dele), com UMA pergunta leve e fácil de "
    "responder. Não reapresente a empresa, não repita o pitch, não pressione.",
)

CADENCE: tuple[Touch, ...] = (
    Touch(
        1, timedelta(0), (90, 210), "reengajar",
        "Este é o 1º toque (REENGAJAR): retome o assunto com leveza e desperte curiosidade. "
        "Uma única pergunta aberta; não repita o que já foi dito; não pressione.",
    ),
    Touch(
        2, timedelta(days=1), None, "reforco_valor",
        "Este é o toque de REFORÇO DE VALOR (WIIFM): conecte o nosso diferencial à realidade "
        "do lead (o que ele ganha). Uma pergunta de reflexão; nada de tabela de preço.",
    ),
    Touch(
        3, timedelta(days=3), None, "prova_social",
        "Este é o toque de PROVA SOCIAL / quebra de objeção: traga um caso real curto de outro "
        "parceiro e uma pergunta que ajude o lead a se ver no exemplo. Sem repetir toques anteriores.",
    ),
    Touch(
        4, timedelta(days=6, hours=20), None, "ultima_chamada",
        "Este é o toque de ÚLTIMA CHAMADA: sinalize com elegância que vai pausar o contato e "
        "deixe a porta aberta. Tom respeitoso, sem culpa nem urgência artificial.",
    ),
)


def build_touch_jobs(
    now: datetime,
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    env_tag: str,
    warm: bool = True,
    outbound: bool = False,
    rng=_random,
) -> list[dict]:
    """Constrói os jobs da cadência com fire_at monotônico (>= MIN_GAP) e clampado.

    `warm=True` (default): cadência completa de 4 toques, com T1 same-day (offset 0 + jitter).
    `warm=False` (lead frio, sem interesse marcado): SUPRIME o T1 same-day — a cadência começa no
    T2 (dia seguinte). Anti-bombardeio: lead que só engajou (sem sinal de interesse) não recebe
    cobrança no mesmo dia.
    `outbound=True` + `warm=False` (Onda 2, "Sim-e-sumiu"): o lugar do T1 suprimido é ocupado
    pelo OUTBOUND_NUDGE (+18h, dentro da janela de 24h da Meta) — retomada livre no calor da
    conversa em vez de esperar o T2 cair fora da janela e virar template de reabertura.

    Função pura: sem I/O. `rng` injetável para teste do jitter do T1.
    """
    jobs: list[dict] = []
    prev_fire: datetime | None = None
    if warm:
        touches = CADENCE
    elif outbound:
        touches = (OUTBOUND_NUDGE,) + CADENCE[1:]
    else:
        touches = CADENCE[1:]
    for touch in touches:
        offset = touch.offset
        if touch.jitter_minutes:
            lo, hi = touch.jitter_minutes
            offset = offset + timedelta(minutes=rng.randint(lo, hi))
        fire_at = _clamp_to_business_window(now + offset)
        if prev_fire is not None and fire_at <= prev_fire + MIN_GAP:
            fire_at = _clamp_to_business_window(prev_fire + MIN_GAP)
        prev_fire = fire_at
        jobs.append({
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": touch.sequence,
            "fire_at": fire_at.isoformat(),
            "status": "pending",
            "env_tag": env_tag,
            "metadata": {
                "objetivo": touch.objective,
                "objective_prompt": touch.objective_prompt,
                "contexto": touch.objective,
            },
        })
    return jobs
