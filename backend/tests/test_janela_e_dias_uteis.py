"""Disparos das esteiras só em dias comerciais, dentro de uma janela configurável
(pedido do dono, 13/09/2026 — 8h-12h, segunda a sexta, porque o João trabalha das 9h
às 16h e a resposta do lead precisa cair dentro do expediente dele).

A funcionalidade estava 90% construída e quebrada em quatro pontos, cada um coberto
aqui por um motivo específico:

1. `test_select_de_get_due_enrollments_inclui_skip_weekends` — a guarda de fim de
   semana em `_is_within_window` (engine.py) SEMPRE EXISTIU e trata `skip_weekends`
   corretamente, mas o SELECT que carrega a matrícula (`engine.get_due_enrollments`)
   nunca trazia essa coluna da campanha. `campaign.get("skip_weekends", False)`
   devolvia `False` sempre, e a guarda virava código morto — nenhum teste testava o
   SELECT em si, só a função pura isolada, e por isso ninguém via.

2/3. `test_wait_target_*` — `_wait_target` não recebia `skip_weekends` nem a janela
   da campanha: ele só lia `cfg` (o nó), com defaults fixos 7/18 e sem fim de semana.
   O seed das esteiras do João (apagado em 18/09/2026) só gravava `{"days": dias}` no
   nó — a janela e o flag vivem exclusivamente na CAMPANHA — então todo `wait` de uma
   esteira multi-toque ignorava silenciosamente a janela configurada pelo dono e um
   toque que caía num sábado era agendado PARA o sábado. Isso vale para QUALQUER
   campanha do builder, não só para as do João: o nó `wait` do builder
   (`campaigns/node_registry.py`) também nasce sem janela própria de propósito.

4. Havia aqui um quarto teste, de regressão do seed das 6 esteiras do João (janela
   8h-12h, skip_weekends=True). Ele morreu em 18/09/2026 junto com o seed: as
   cadências do João deixaram de ser campanhas do builder e passaram a rodar como
   novos `job_type` em `follow_up_jobs`
   (docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md). A janela
   comercial do motor novo é a do scheduler, não a de uma linha de `campaigns` —
   quem a cobre é a suíte do follow-up, não este arquivo. Os três testes acima
   continuam valendo: eles são sobre `automation/engine.py`, que segue em produção.

É seguro testar contra os valores exatos de data/hora abaixo porque não existe
nenhuma matrícula viva (`campaign_enrollments` = 0 linhas em toda a história,
13/09/2026) — mudar o comportamento não move nenhum toque em produção.
"""

import inspect
from datetime import datetime, timezone

from app.automation import engine
from app.automation.engine import _wait_target

# Sexta-feira, 09:00 BRT (12:00 UTC). weekday() == 4 (segunda=0).
_SEXTA = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)

# Segunda-feira, 14:00 BRT (17:00 UTC) — fora da janela 8h-12h.
_SEGUNDA_TARDE = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)


def test_wait_target_sexta_com_skip_weekends_pula_para_segunda():
    """Toque que cairia no sábado, com a campanha pedindo skip_weekends=True, tem
    que ser empurrado para a segunda — não pode parar no sábado."""
    campanha = {"send_start_hour": 8, "send_end_hour": 12, "skip_weekends": True}
    alvo = _wait_target({"days": 1}, _SEXTA, campanha)
    assert alvo == datetime(2026, 9, 14, 11, 0, tzinfo=timezone.utc)
    assert alvo.weekday() == 0, f"esperava segunda-feira (weekday=0), veio weekday={alvo.weekday()}"


def test_wait_target_sexta_sem_skip_weekends_preserva_comportamento_antigo():
    """Mesmo cenário, mas com skip_weekends=False na campanha: o comportamento
    histórico (sem checagem de fim de semana) precisa continuar valendo — o toque
    cai no sábado normalmente."""
    campanha = {"send_start_hour": 8, "send_end_hour": 12, "skip_weekends": False}
    alvo = _wait_target({"days": 1}, _SEXTA, campanha)
    assert alvo == datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    assert alvo.weekday() == 5, f"esperava sábado (weekday=5), veio weekday={alvo.weekday()}"


def test_wait_target_no_sem_janela_usa_a_da_campanha():
    """Nó `wait` sem send_start_hour/send_end_hour próprios (o caso real do seed das
    esteiras — `_wait()` só grava `{"days": dias}`) herda 8/12 da campanha."""
    campanha = {"send_start_hour": 8, "send_end_hour": 12}
    alvo = _wait_target({"days": 0, "hours": 0}, _SEGUNDA_TARDE, campanha)
    # 11:00 UTC == 08:00 BRT — confirma que start_h=8 (da campanha) foi usado, não o
    # default fixo 7 que a função tinha antes de aceitar a campanha.
    assert alvo == datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc)


def test_wait_target_no_que_opina_vence_a_campanha():
    """Nó com send_start_hour próprio (caso avançado, gerado pelo builder em
    helpers.ts) tem que vencer o valor da campanha."""
    campanha = {"send_start_hour": 8, "send_end_hour": 12}
    alvo = _wait_target({"days": 0, "hours": 0, "send_start_hour": 10}, _SEGUNDA_TARDE, campanha)
    # 13:00 UTC == 10:00 BRT — confirma que o send_start_hour=10 do NÓ venceu o 8 da
    # campanha.
    assert alvo == datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)


def test_wait_target_com_dois_argumentos_continua_funcionando():
    """Retrocompatibilidade: `campaign` é opcional (default None) de propósito —
    testes existentes (test_wait_node_hours_2026_07_11.py) chamam `_wait_target(cfg,
    now)` com dois argumentos só, e continuam precisando funcionar sem tocar em
    `campaign`."""
    _NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    alvo = _wait_target({"days": 3, "hours": 20, "send_start_hour": 0, "send_end_hour": 24}, _NOW)
    assert alvo == datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)


def test_select_de_get_due_enrollments_inclui_skip_weekends():
    """A guarda de fim de semana em `_is_within_window` sempre existiu — o defeito
    era que a coluna `skip_weekends` nunca chegava até `campaign.get(...)` porque o
    SELECT de `engine.get_due_enrollments` não a trazia. Sem este teste, a guarda
    podia voltar a virar código morto silenciosamente: nenhum outro teste bate no
    texto da query, só na função pura isolada `_is_within_window`."""
    fonte = inspect.getsource(engine.get_due_enrollments)
    assert "skip_weekends" in fonte, (
        "skip_weekends sumiu do SELECT de get_due_enrollments — "
        "campaign.get('skip_weekends') volta a ser sempre False e a guarda de fim "
        "de semana volta a ser código morto"
    )
