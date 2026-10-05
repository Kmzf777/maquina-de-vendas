# P6 — Follow-up (call semanal 01/10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a esteira do João para de tocar quem acabou de comprar (na matrícula E no envio) e
ganha a cadência `kit` (follow-up do kit de degustação ~20 dias depois da venda) nos dois
funis de Reposição, nascendo desligada.

**Architecture:** regras de venda PURAS em `follow_up/service.py`, alimentadas por leituras
paginadas de `sales`/`sale_items`/`deals` na varredura (`_varrer_cadencia_joao`) e por uma
leitura por lead no envio (`scheduler._process_joao_touch`, ao lado da guarda
`card_mudou_de_etapa`). O que é "kit" mora em `follow_up/kit.py`. A cadência `kit` é
declarada em `cadence_joao.py` como **cadência complementar** do funil (ver "Desvio 1").
A migração `20261006c_followup_kit.sql` só alarga três CHECKs; nada é semeado.

**Tech Stack:** FastAPI + supabase-py, pytest no container `canastra-api`, Postgres 17
descartável (`crm-scratch-pg`) para a migração.

Spec: `docs/superpowers/specs/2026-10-06-call-semanal-0110-design.md` (Diagnóstico 7, P6).
Plano mestre: `docs/superpowers/plans/2026-10-06-call-semanal-0110.md` (P6 e "Regras de
execução" — flock, só os testes do pacote, produção só leitura, sem push).

---

## Desvios conscientes do plano mestre (decididos lendo o código real)

1. **`kit` não entra em `FUNIS[*].cadencias`; entra em `CADENCIAS_COMPLEMENTARES`.**
   Medido em 06/10: pôr `kit` em `FUNIS` deixa **11 testes existentes vermelhos**
   (`test_cadence_joao_2026_09_18.py`, `test_api_definicao_joao_2026_09_18.py`,
   `test_scheduler_joao_2026_09_18.py`) que fixam "Reposição tem exatamente 2 cadências",
   "JOB_TYPES são 5" e cruzam o CHECK da migration **20260918** (já aplicada, de outro dono)
   com `FUNIS`. Esses arquivos estão fora do pacote (regra 7: parar e reportar). Então:
   `FUNIS` continua sendo o contrato da TELA (GET de definição: 5 cadências), e
   `cadencias_do_funil()` / `cadencia_do_funil()` passam a enxergar também as
   complementares — é por elas que o agendador, a sobreposição do banco, o `resolver`, o
   PUT da API e o handler acham o `kit`. Consequência: o kit **não aparece na tela** até a
   integração mover `kit` para `FUNIS` e atualizar os 11 testes (lista no relatório).
2. **Toques do kit nascem com `template_name=None`, não `followjoao_kit_1/2`.** É a
   doutrina da decisão 1 de `cadence_joao.py` ("Em atenção"): nome de template que não
   existe na Meta troca a RECUSA de ligar por um envio que morre em runtime. Com `None`,
   `ativa=true` gravado à mão sem template é inerte (o agendador recusa). Os nomes previstos
   (`followjoao_kit_1`, `followjoao_kit_2`) entram pela sobreposição `followup_joao_toque`
   (ou pelo PUT da API, que confere APPROVED na Meta) quando forem aprovados.
3. **Ajuste `dias_sem_prospeccao_apos_venda` fora de `AJUSTES_PADRAO`.** `AJUSTES_PADRAO` é
   o contrato da tela de ajustes e está fixado em testes existentes (`== {2 chaves}`) e no
   CHECK da 20260926. Leitura própria (`carregar_dias_sem_prospeccao_apos_venda`), mesma
   tabela, mesmo fail-closed para o default (30). Editável por SQL, não pela tela.
4. **Kit também é checado no envio:** toque de kit é cancelado (`lead_comprou`) se o lead
   comprou de novo depois da matrícula. "Na dúvida, pula."

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| Create `backend/app/follow_up/kit.py` | `SKUS_KIT`, `SKUS_KIT_TODOS`, `item_e_kit`, `venda_e_kit` — PURO |
| Modify `backend/app/follow_up/cadence_joao.py` | cadência `kit` + `CADENCIAS_COMPLEMENTARES`, `cadencias_do_funil`, `JOB_TYPES_TODOS`; `cadencia_do_funil` olha as duas |
| Modify `backend/app/follow_up/service.py` | regras puras de venda, `motivo_para_pular_joao(…, vendas=, deal_criado_em=, dias_sem_prospeccao=)`, leitores paginados, ajuste N, varredura, `motivo_venda_no_envio` |
| Modify `backend/app/follow_up/scheduler.py` | `joao_kit` em `JOAO_JOB_TYPES`; checagem de venda no envio |
| Create `supabase/migrations/20261006c_followup_kit.sql` | alarga 3 CHECKs (par `kit`, toques 1..2, chave do ajuste) |
| Tests `backend/tests/test_cs_p6_*.py` | um arquivo por tarefa |

Comando de teste (sempre com flock; troque `<arquivos>`):

```bash
cd /root/crm-wt/cs-p6 && flock /root/crm-wt/_heavy.lock docker run --rm --user root \
  -v $PWD:/repo -w /repo/backend -e SUPABASE_URL=https://example.supabase.co \
  -e SUPABASE_SERVICE_KEY=ci-dummy canastra-api:latest sh -c \
  "pip install -q -r requirements-dev.txt >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider <arquivos>"
```

---

### Task 1: `follow_up/kit.py` — o que é kit

**Files:**
- Create: `backend/app/follow_up/kit.py`
- Test: `backend/tests/test_cs_p6_kit.py`

- [ ] **Step 1: teste falhando**

```python
"""P6 / Task 6.3 — o que conta como venda de KIT DE DEGUSTAÇÃO."""
import pytest

from app.follow_up import kit as K


def test_skus_de_kit_das_duas_contas_bling():
    assert K.SKUS_KIT["default"] == frozenset(
        {16536419853, 16637692216, 16658150270, 9256328993})
    assert K.SKUS_KIT["secundaria"] == frozenset({16697411791, 16701798396})
    assert K.SKUS_KIT_TODOS == K.SKUS_KIT["default"] | K.SKUS_KIT["secundaria"]


@pytest.mark.parametrize("sku", sorted(K.SKUS_KIT_TODOS))
def test_sku_de_kit_e_kit_mesmo_com_descricao_qualquer(sku):
    assert K.venda_e_kit([{"bling_product_id": sku, "descricao": "Pedido 123"}])


def test_sku_em_texto_tambem_casa():
    assert K.venda_e_kit([{"bling_product_id": "16536419853", "descricao": None}])


@pytest.mark.parametrize("descricao", [
    "Kit Degustação", "KIT DEGUSTAÇÃO 1°", "kit degustacao", "Kit  Degustação 2",
    "Meu KIT degust. especial",
])
def test_descricao_kit_degust_casa_sem_acento_sem_caixa(descricao):
    assert K.venda_e_kit([{"bling_product_id": 0, "descricao": descricao}])


@pytest.mark.parametrize("descricao", [
    "Kit Café Filtrado Drip Coffee Canastra Suave 30un",  # existe em produção: NÃO é kit
    "Café Clássico Moído 250g", "", None,
])
def test_o_que_nao_e_kit(descricao):
    assert not K.venda_e_kit([{"bling_product_id": 0, "descricao": descricao}])


def test_venda_com_kit_e_outro_produto_e_kit():
    assert K.venda_e_kit([
        {"bling_product_id": 1, "descricao": "Café Clássico"},
        {"bling_product_id": 9256328993, "descricao": "KIT DEGUSTAÇÃO"},
    ])


def test_venda_sem_itens_nao_e_kit():
    assert not K.venda_e_kit([])
    assert not K.venda_e_kit(None)
```

- [ ] **Step 2: rodar** `tests/test_cs_p6_kit.py` → FAIL (`ImportError: cannot import name 'kit'`).

- [ ] **Step 3: implementação**

```python
"""O que é "kit de degustação" para o follow-up do João (spec 2026-10-06, P6.2). PURO.

Kit = algum item da venda com `bling_product_id` na lista de SKUs de kit das DUAS contas
Bling, OU com "kit degust" na descrição (sem acento, sem caixa, espaços colapsados). A
descrição cobre o item lançado à mão no CRM (sem SKU) e o SKU novo que ninguém lembrou de
pôr aqui. "Kit Café Filtrado Drip…" existe em produção e NÃO é kit de degustação — por
isso o trecho é "kit degust", e não "kit".
"""
from __future__ import annotations

import unicodedata
from typing import Any, Iterable, Mapping

# SKUs medidos em `sale_items` de produção em 06/10/2026 (por conta Bling).
SKUS_KIT: Mapping[str, frozenset[int]] = {
    "default": frozenset({16536419853, 16637692216, 16658150270, 9256328993}),
    "secundaria": frozenset({16697411791, 16701798396}),
}
SKUS_KIT_TODOS: frozenset[int] = frozenset().union(*SKUS_KIT.values())

_TRECHO_KIT = "kit degust"


def _normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def _sku(valor: Any) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def item_e_kit(item: Mapping[str, Any]) -> bool:
    """Este item de venda é kit de degustação?"""
    if _sku(item.get("bling_product_id")) in SKUS_KIT_TODOS:
        return True
    return _TRECHO_KIT in _normalizar(str(item.get("descricao") or ""))


def venda_e_kit(itens: Iterable[Mapping[str, Any]] | None) -> bool:
    """A venda tem ALGUM item de kit? Venda sem itens não é kit."""
    return any(item_e_kit(item) for item in (itens or ()))
```

- [ ] **Step 4: rodar** → PASS.
- [ ] **Step 5: commit** `feat(follow-up): kit.py — SKUs e regra de venda de kit de degustação`

---

### Task 2: cadência `kit` como complementar dos funis de Reposição

**Files:**
- Modify: `backend/app/follow_up/cadence_joao.py` (depois de `FUNIS`, e `cadencia_do_funil`)
- Modify: `backend/app/follow_up/service.py:14-28` (import `JOB_TYPES_TODOS as JOAO_JOB_TYPES`, `cadencias_do_funil`)
- Modify: `backend/app/follow_up/scheduler.py:108-111` (`"joao_kit"`)
- Test: `backend/tests/test_cs_p6_cadencia_kit.py`

- [ ] **Step 1: teste falhando**

```python
"""P6 / Task 6.4 — a cadência `kit` existe nos dois funis de Reposição, desligada."""
from unittest.mock import patch

import pytest

from app.follow_up import cadence_joao as C
from app.follow_up import scheduler as SCH
from app.follow_up import service as S
from tests.test_agendador_joao_2026_09_18 import _FakeSupabase

REPOSICAO = ("reposicao_atacado", "reposicao_private_label")


@pytest.mark.parametrize("funil", REPOSICAO)
def test_kit_existe_nos_dois_funis_de_reposicao(funil):
    kit = C.cadencia_do_funil(funil, "kit")
    assert kit is not None
    assert (kit.gatilho_stage_key, kit.gatilho_stage_rotulo) == ("novo", "Cliente Ativo")
    assert kit.gatilho_dias == 20
    assert [t.offset.days for t in kit.touches] == [0, 7]
    assert kit.job_type == "joao_kit"


@pytest.mark.parametrize("funil", ["atacado", "private_label", "recuperacao"])
def test_kit_nao_existe_fora_da_reposicao(funil):
    assert C.cadencia_do_funil(funil, "kit") is None


@pytest.mark.parametrize("funil", REPOSICAO)
def test_kit_nasce_desligado_e_sem_template(funil):
    assert C.resolver(funil, "kit", {}).ativa is False
    assert C.toques_sem_template(funil, "kit") == (1, 2)


def test_kit_nao_move_card_nem_se_repete():
    kit = C.cadencia_do_funil("reposicao_atacado", "kit")
    assert kit.etapa_final_key is None
    assert all(t.move_para is None for t in kit.touches)
    assert kit.etapas_vivas_efetivas == ("novo",)
    assert kit.repete_ultimo is False


def test_ligar_o_kit_pela_sobreposicao_do_banco():
    r = C.resolver("reposicao_atacado", "kit", {
        "ativa": True,
        "toques": {1: {"template_name": "followjoao_kit_1"},
                   2: {"template_name": "followjoao_kit_2"}},
    })
    assert r.ativa is True
    assert [t.template_name for t in r.touches] == ["followjoao_kit_1", "followjoao_kit_2"]


def test_o_contrato_da_tela_nao_muda_e_a_lista_completa_tem_o_kit():
    assert [c.codigo for c in C.funil("reposicao_atacado").cadencias] == \
        ["reposicao", "em_atencao"]
    assert [c.codigo for c in C.cadencias_do_funil("reposicao_atacado")] == \
        ["reposicao", "em_atencao", "kit"]
    assert C.cadencias_do_funil("inexistente") == ()


def test_job_types_todos_e_os_cinco_mais_o_kit():
    assert C.JOB_TYPES_TODOS == C.JOB_TYPES | {"joao_kit"}


def test_service_e_scheduler_enxergam_joao_kit():
    # Sem isto o job de kit escapa do teto diário, da trava de "cadência em andamento" e
    # da trava de "1 template por lead por dia".
    assert "joao_kit" in S.JOAO_JOB_TYPES
    assert "joao_kit" in SCH.JOAO_JOB_TYPES
    assert SCH._stop_reason_applies("ai_disabled", "joao_kit") is False


def test_sobreposicao_do_banco_le_a_linha_do_kit():
    fake = _FakeSupabase(rows={
        "followup_joao_cadencia": [{"funil": "reposicao_atacado", "cadencia": "kit",
                                    "gatilho_dias": None, "ativa": True}],
        "followup_joao_toque": [{"funil": "reposicao_atacado", "cadencia": "kit",
                                 "toque": 1, "dias": None,
                                 "template_name": "followjoao_kit_1"}],
    })
    with patch("app.follow_up.service.get_supabase", return_value=fake):
        ov = S.carregar_overrides_joao()
    assert ov["reposicao_atacado"]["kit"]["ativa"] is True
    assert ov["reposicao_atacado"]["kit"]["toques"][1]["template_name"] == "followjoao_kit_1"
```

- [ ] **Step 2: rodar** → FAIL (`cadencia_do_funil(..., "kit")` é None; `cadencias_do_funil` não existe).

- [ ] **Step 3: implementação**

Em `cadence_joao.py`, logo depois do bloco `FUNIS = (...)`:

```python
# ═══════════════════════════════════════════════════════════════════════════════
# Cadências COMPLEMENTARES — existem no funil, ainda não na TELA (spec 2026-10-06, P6)
# ═══════════════════════════════════════════════════════════════════════════════
#
# `FUNIS[*].cadencias` é o contrato da tela (GET de definição) e está fixado pela suíte
# em 5 cadências. A `kit` foi pedida na call de 01/10 e mora nos MESMOS funis de
# Reposição, mas entra por aqui até a tela ganhar a coluna: `cadencias_do_funil` e
# `cadencia_do_funil` enxergam as duas listas, e é por elas que o agendador, a
# sobreposição do banco, o `resolver`, o PUT da API e o handler acham o kit.
#
# ── "Kit degustação" — follow-up de quem comprou o kit ───────────────────────────
# Gatilho: card em "Cliente Ativo" (key `novo` da Reposição) há >= 20 dias E a ÚLTIMA
# venda não cancelada do lead é kit (`follow_up/kit.py`) — a segunda metade é regra de
# VENDA, aplicada pelo agendador (`service.motivo_venda_para_matricula`). Toques nos
# dias 0 e 7. Não move card: ele segue em "Cliente Ativo" e a Reposição (45 dias) o
# pega depois — "um card, uma cadência por vez" impede as duas ao mesmo tempo.
#
# `template_name=None` nos dois toques, de propósito (decisão 1 no cabeçalho): os
# templates previstos (`followjoao_kit_1`, `followjoao_kit_2`) não existem na Meta em
# 06/10/2026. Eles entram por `followup_joao_toque` quando aprovados; até lá ligar a
# cadência é RECUSADO (API e agendador), em vez de matricular e morrer no envio.
_KIT_OFFSETS = (0, 7)


def _cadencia_kit() -> Cadencia:
    return Cadencia(
        codigo="kit",
        rotulo="Kit degustação",
        gatilho_stage_key="novo",
        gatilho_stage_rotulo="Cliente Ativo",
        gatilho_dias=20,
        touches=_toques(_KIT_OFFSETS, (None,) * len(_KIT_OFFSETS)),
    )


CADENCIAS_COMPLEMENTARES: Mapping[str, tuple[Cadencia, ...]] = {
    "reposicao_atacado": (_cadencia_kit(),),
    "reposicao_private_label": (_cadencia_kit(),),
}
```

Depois de `JOB_TYPES = frozenset(...)`:

```python
# `JOB_TYPES` acima é o das cadências da TELA (fixado em 5 pela suíte). Quem lê/conta
# jobs do João (teto diário, trava de matrícula, 1 template por dia) usa ESTE: um job
# de kit fora dessas contas escaparia de todas as travas.
JOB_TYPES_TODOS: frozenset[str] = JOB_TYPES | frozenset(
    c.job_type for cs in CADENCIAS_COMPLEMENTARES.values() for c in cs
)
```

Trocar o corpo de `cadencia_do_funil` e acrescentar `cadencias_do_funil` antes dela:

```python
def cadencias_do_funil(funil_codigo: str) -> tuple[Cadencia, ...]:
    """TODAS as cadências do funil: as da tela (`Funil.cadencias`) e as complementares.
    `()` para funil inexistente. É esta a lista que o agendador percorre."""
    f = _POR_FUNIL.get(funil_codigo)
    if not f:
        return ()
    return f.cadencias + tuple(CADENCIAS_COMPLEMENTARES.get(funil_codigo, ()))


def cadencia_do_funil(funil_codigo: str, cadencia_codigo: str) -> Cadencia | None:
    """(docstring existente mantida) ... Enxerga também as cadências complementares."""
    return next(
        (c for c in cadencias_do_funil(funil_codigo) if c.codigo == cadencia_codigo),
        None,
    )
```

Em `service.py`, no import de `cadence_joao`: trocar `JOB_TYPES as JOAO_JOB_TYPES` por
`JOB_TYPES_TODOS as JOAO_JOB_TYPES` e acrescentar `cadencias_do_funil`.

Em `scheduler.py:108-111` acrescentar `"joao_kit"` ao frozenset `JOAO_JOB_TYPES`.

- [ ] **Step 4: rodar** `tests/test_cs_p6_cadencia_kit.py tests/test_cadence_joao_2026_09_18.py tests/test_api_definicao_joao_2026_09_18.py` → PASS.
- [ ] **Step 5: commit** `feat(follow-up): cadência kit nos funis de Reposição, nascendo desligada`

---

### Task 3: regras PURAS de venda + `motivo_para_pular_joao`

**Files:**
- Modify: `backend/app/follow_up/service.py` (antes de `motivo_para_pular_joao`, e a função)
- Test: `backend/tests/test_cs_p6_regra_venda.py`

- [ ] **Step 1: teste falhando**

```python
"""P6 / Task 6.1 e 6.4 — quem comprou não recebe prospecção; o kit só pega kit."""
from datetime import datetime, timedelta, timezone

import pytest

from app.follow_up import service as S

NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)
PROPOSTA = S.resolver_para_agendar("atacado", "proposta", {})
KIT = S.resolver_para_agendar("reposicao_atacado", "kit", {"ativa": True})


def _venda(dias_atras, *, id="s1", status="registrada", kit=None, **extra):
    quando = (NOW - timedelta(days=dias_atras)).isoformat()
    v = {"id": id, "lead_id": "lead-1", "sold_at": quando, "created_at": quando,
         "status": status, **extra}
    if kit is not None:
        v["kit"] = kit
    return v


def _pular(cad, vendas, *, deal_dias=None, dias=30, jobs=()):
    criado = None if deal_dias is None else NOW - timedelta(days=deal_dias)
    return S.motivo_para_pular_joao(cad, list(jobs), NOW, vendas=vendas,
                                    deal_criado_em=criado, dias_sem_prospeccao=dias)


# ── prospecção ────────────────────────────────────────────────────────────────
def test_caso_real_joao_proposta_para_lead_com_venda_manual_em_outro_deal():
    venda = _venda(3, deal_id="deal-de-outro-card", origin="manual")
    assert _pular(PROPOSTA, [venda], deal_dias=10) == "lead_comprou"


@pytest.mark.parametrize("funil,codigo", [
    ("atacado", "novo"), ("private_label", "em_conversa"), ("private_label", "proposta")])
def test_venda_recente_pula_as_tres_de_prospeccao(funil, codigo):
    cad = S.resolver_para_agendar(funil, codigo, {})
    assert _pular(cad, [_venda(29)], deal_dias=200) == "lead_comprou"


def test_venda_depois_da_criacao_do_card_pula_mesmo_fora_dos_n_dias():
    assert _pular(PROPOSTA, [_venda(60)], deal_dias=90) == "lead_comprou"


def test_venda_antiga_anterior_ao_card_nao_pula():
    assert _pular(PROPOSTA, [_venda(60)], deal_dias=40) is None


def test_venda_cancelada_nao_conta():
    assert _pular(PROPOSTA, [_venda(2, status="cancelada")], deal_dias=10) is None


def test_n_vem_do_ajuste():
    assert _pular(PROPOSTA, [_venda(45)], deal_dias=30, dias=60) == "lead_comprou"
    assert _pular(PROPOSTA, [_venda(45)], deal_dias=30, dias=30) is None


def test_venda_sem_data_na_duvida_pula():
    v = _venda(5)
    v["sold_at"] = v["created_at"] = None
    assert _pular(PROPOSTA, [v], deal_dias=10) == "lead_comprou"


def test_sem_vendas_informadas_a_funcao_pura_nao_aplica_a_regra():
    # O contrato antigo (3 argumentos) continua valendo. A varredura SEMPRE informa.
    assert S.motivo_para_pular_joao(PROPOSTA, [], NOW) is None


def test_reposicao_ignora_a_regra_de_venda():
    rep = S.resolver_para_agendar("reposicao_atacado", "reposicao", {})
    assert _pular(rep, [_venda(1)], deal_dias=1) is None


def test_cadencia_em_andamento_continua_vindo_primeiro():
    pendente = {"id": "j1", "status": "pending", "job_type": "joao_proposta",
                "metadata": {}}
    assert _pular(PROPOSTA, [_venda(1)], deal_dias=5, jobs=[pendente]) == \
        "cadencia_em_andamento"


# ── kit ───────────────────────────────────────────────────────────────────────
def test_kit_ha_20_dias_entra():
    assert _pular(KIT, [_venda(20, kit=True)]) is None


def test_kit_ha_19_dias_nao_entra():
    assert _pular(KIT, [_venda(19, kit=True)]) == "venda_kit_recente"


def test_ultima_venda_nao_kit_nao_entra():
    vendas = [_venda(60, id="a", kit=True), _venda(25, id="b", kit=False)]
    assert _pular(KIT, vendas) == "ultima_venda_nao_e_kit"


def test_kit_depois_de_uma_venda_normal_entra():
    vendas = [_venda(90, id="a", kit=False), _venda(21, id="b", kit=True)]
    assert _pular(KIT, vendas) is None


def test_kit_cancelado_nao_e_a_ultima_venda():
    vendas = [_venda(60, id="a", kit=False), _venda(25, id="b", kit=True, status="cancelada")]
    assert _pular(KIT, vendas) == "ultima_venda_nao_e_kit"


def test_kit_sem_venda_ou_sem_leitura():
    assert _pular(KIT, []) == "sem_venda"
    assert _pular(KIT, None) == "vendas_desconhecidas"


def test_venda_sem_marca_de_kit_na_duvida_nao_e_kit():
    assert _pular(KIT, [_venda(25)]) == "ultima_venda_nao_e_kit"


def test_kit_respeita_o_gatilho_sobreposto():
    kit30 = S.resolver_para_agendar("reposicao_atacado", "kit",
                                    {"ativa": True, "gatilho_dias": 30})
    assert _pular(kit30, [_venda(25, kit=True)]) == "venda_kit_recente"


def test_kit_que_ja_rodou_respeita_o_cooldown():
    enviado = {"id": "j1", "status": "sent", "job_type": "joao_kit",
               "created_at": (NOW - timedelta(days=10)).isoformat(),
               "metadata": {"matricula_id": "m1"}}
    assert _pular(KIT, [_venda(30, kit=True)], jobs=[enviado]) == "cooldown"


# ── envio do kit ───────────────────────────────────────────────────────────────
def test_comprou_depois_da_matricula():
    matricula = NOW - timedelta(days=7)
    assert S.comprou_depois_da_matricula([_venda(1)], matricula_em=matricula)
    assert not S.comprou_depois_da_matricula([_venda(27, kit=True)], matricula_em=matricula)
    assert not S.comprou_depois_da_matricula(
        [_venda(1, status="cancelada")], matricula_em=matricula)
```

- [ ] **Step 2: rodar** → FAIL (`motivo_para_pular_joao() got an unexpected keyword argument 'vendas'`).

- [ ] **Step 3: implementação** (em `service.py`, logo antes de `def motivo_para_pular_joao`)

```python
# ── Quem comprou não recebe prospecção (spec 2026-10-06, P6.1) ─────────────────
#
# A call de 01/10 viu a esteira mandar "Proposta Enviada" para quem tinha acabado de
# comprar: o motor só olhava o CARD, e venda em outro deal, venda do Bling (sem deal) ou
# card não movido deixavam o card de prospecção vivo. A regra olha `sales` do LEAD.
CADENCIAS_DE_PROSPECCAO: frozenset[str] = frozenset({"novo", "em_conversa", "proposta"})
CADENCIA_KIT = "kit"
CADENCIAS_COM_REGRA_DE_VENDA: frozenset[str] = CADENCIAS_DE_PROSPECCAO | {CADENCIA_KIT}
MOTIVO_LEAD_COMPROU = "lead_comprou"


def _venda_cancelada(venda: Mapping[str, Any]) -> bool:
    return str(venda.get("status") or "").strip().lower().startswith("cancel")


def _momento_da_venda(venda: Mapping[str, Any]) -> datetime | None:
    return _parse_ts(venda.get("sold_at")) or _parse_ts(venda.get("created_at"))


def _vendas_validas(vendas) -> list[Mapping[str, Any]]:
    return [v for v in (vendas or ()) if not _venda_cancelada(v)]


def lead_comprou(
    vendas, *, now: datetime, deal_criado_em: datetime | None, dias: int,
) -> bool:
    """Venda NÃO cancelada nos últimos `dias` dias OU depois da criação do card. PURA.

    Venda sem data nenhuma conta como compra: na dúvida, a esteira pula.
    """
    corte = now - timedelta(days=dias)
    for venda in _vendas_validas(vendas):
        quando = _momento_da_venda(venda)
        if quando is None or quando >= corte:
            return True
        if deal_criado_em is not None and quando > deal_criado_em:
            return True
    return False


def motivo_kit_para_matricula(vendas, *, now: datetime, gatilho_dias: int) -> str | None:
    """A ÚLTIMA venda não cancelada é kit e tem >= `gatilho_dias` dias? PURA.

    `venda["kit"]` é gravado pelo leitor (`_vendas_dos_leads`); ausente = não é kit.
    Empate de data com venda que não é kit também não é "a última foi kit".
    """
    validas = _vendas_validas(vendas)
    if not validas:
        return "sem_venda"
    momentos = [_momento_da_venda(v) for v in validas]
    if any(m is None for m in momentos):
        return "venda_sem_data"
    ultimo = max(momentos)
    ultimas = [v for v, m in zip(validas, momentos) if m == ultimo]
    if not all(v.get("kit") is True for v in ultimas):
        return "ultima_venda_nao_e_kit"
    if ultimo > now - timedelta(days=gatilho_dias):
        return "venda_kit_recente"
    return None


def motivo_venda_para_matricula(
    cadencia: CadenciaResolvida, vendas, *, now: datetime,
    deal_criado_em: datetime | None, dias_sem_prospeccao: int,
) -> str | None:
    """A regra de VENDA da matrícula, por cadência. PURA.

    `vendas=None` é "não li". No kit isso PULA (o gatilho É uma venda). Na prospecção a
    regra só não se aplica — é o contrato antigo da função pura; a varredura sempre lê.
    """
    if cadencia.codigo == CADENCIA_KIT:
        if vendas is None:
            return "vendas_desconhecidas"
        return motivo_kit_para_matricula(
            vendas, now=now, gatilho_dias=int(cadencia.gatilho_dias or 0))
    if cadencia.codigo in CADENCIAS_DE_PROSPECCAO and vendas is not None:
        if lead_comprou(vendas, now=now, deal_criado_em=deal_criado_em,
                        dias=dias_sem_prospeccao):
            return MOTIVO_LEAD_COMPROU
    return None


def comprou_depois_da_matricula(vendas, *, matricula_em: datetime) -> bool:
    """Venda não cancelada vendida OU registrada depois da matrícula (envio do kit). PURA."""
    for venda in _vendas_validas(vendas):
        quando = _momento_da_venda(venda)
        registrada = _parse_ts(venda.get("created_at"))
        if quando is None or quando > matricula_em or (
                registrada is not None and registrada > matricula_em):
            return True
    return False
```

E em `motivo_para_pular_joao`: assinatura

```python
def motivo_para_pular_joao(
    cadencia: CadenciaResolvida, jobs_do_card: list[dict], now: datetime, *,
    vendas: list[dict] | None = None,
    deal_criado_em: datetime | None = None,
    dias_sem_prospeccao: int = DIAS_SEM_PROSPECCAO_PADRAO,
) -> str | None:
```

(`DIAS_SEM_PROSPECCAO_PADRAO = 30` declarado junto das constantes acima), docstring com a
regra "2b. venda" na lista de ordem, e logo depois do bloco "2. A PARTIÇÃO":

```python
    # 2b. VENDA (spec 2026-10-06, P6): prospecção pula quem comprou; o kit só pega quem
    #     tem um kit como última compra, há pelo menos `gatilho_dias`.
    motivo_venda = motivo_venda_para_matricula(
        cadencia, vendas, now=now, deal_criado_em=deal_criado_em,
        dias_sem_prospeccao=dias_sem_prospeccao)
    if motivo_venda:
        return motivo_venda
```

- [ ] **Step 4: rodar** `tests/test_cs_p6_regra_venda.py tests/test_agendador_joao_2026_09_18.py` → PASS.
- [ ] **Step 5: commit** `feat(follow-up): regra pura — prospecção pula quem comprou, kit só pega kit`

---

### Task 4: ajuste `dias_sem_prospeccao_apos_venda`

**Files:**
- Modify: `backend/app/follow_up/service.py` (depois de `carregar_ajustes_joao`)
- Test: `backend/tests/test_cs_p6_ajuste_dias.py`

- [ ] **Step 1: teste falhando**

```python
"""P6 / Task 6.1 — N vem de `followup_joao_ajustes`, default 30, fail-closed."""
from app.follow_up import service as S
from tests.test_agendador_joao_2026_09_18 import _FakeSupabase


def test_sem_linha_vale_30():
    assert S.carregar_dias_sem_prospeccao_apos_venda(_FakeSupabase(rows={})) == 30


def test_le_a_linha_e_ignora_as_outras_chaves():
    fake = _FakeSupabase(rows={"followup_joao_ajustes": [
        {"chave": "teto_diario_disparos", "valor": 50},
        {"chave": "dias_sem_prospeccao_apos_venda", "valor": 45},
    ]})
    assert S.carregar_dias_sem_prospeccao_apos_venda(fake) == 45


def test_tabela_quebrada_vale_o_default():
    fake = _FakeSupabase(tabelas_quebradas={"followup_joao_ajustes"})
    assert S.carregar_dias_sem_prospeccao_apos_venda(fake) == 30


def test_valor_invalido_vale_o_default():
    for valor in (0, -3, "abc", None):
        fake = _FakeSupabase(rows={"followup_joao_ajustes": [
            {"chave": "dias_sem_prospeccao_apos_venda", "valor": valor}]})
        assert S.carregar_dias_sem_prospeccao_apos_venda(fake) == 30, valor


def test_o_contrato_da_tela_de_ajustes_nao_muda():
    assert set(S.AJUSTES_PADRAO) == {"teto_diario_disparos", "adiamento_estoque_dias"}
    assert S.AJUSTE_DIAS_SEM_PROSPECCAO == "dias_sem_prospeccao_apos_venda"
```

- [ ] **Step 2: rodar** → FAIL (`AttributeError: carregar_dias_sem_prospeccao_apos_venda`).

- [ ] **Step 3: implementação**

```python
# ── O N da regra "quem comprou não recebe prospecção" (spec 2026-10-06, P6.1) ─────
# Mesma tabela dos ajustes globais, chave própria. FORA de `AJUSTES_PADRAO` de
# propósito: aquele dict é o contrato da TELA de ajustes (GET/PUT), e este número ainda
# não tem campo lá — é editado por SQL. Mesma disciplina fail-closed para o default.
AJUSTE_DIAS_SEM_PROSPECCAO = "dias_sem_prospeccao_apos_venda"
_dias_sem_prospeccao_aviso_dado = False


def carregar_dias_sem_prospeccao_apos_venda(sb=None) -> int:
    """`followup_joao_ajustes[dias_sem_prospeccao_apos_venda]`, ou 30. Nunca levanta."""
    global _dias_sem_prospeccao_aviso_dado
    try:
        linhas = (sb or get_supabase()).table("followup_joao_ajustes").select(
            "chave, valor"
        ).eq("chave", AJUSTE_DIAS_SEM_PROSPECCAO).execute().data or []
    except Exception as exc:
        if not _dias_sem_prospeccao_aviso_dado:
            logger.warning(
                "[JOAO_CADENCIA] %s não lido (%s) — vale o default %d",
                AJUSTE_DIAS_SEM_PROSPECCAO, exc, DIAS_SEM_PROSPECCAO_PADRAO)
            _dias_sem_prospeccao_aviso_dado = True
        return DIAS_SEM_PROSPECCAO_PADRAO
    for row in linhas if isinstance(linhas, list) else []:
        if row.get("chave") != AJUSTE_DIAS_SEM_PROSPECCAO:
            continue
        try:
            valor = int(row.get("valor"))
        except (TypeError, ValueError):
            continue
        if valor >= 1:
            return valor
    return DIAS_SEM_PROSPECCAO_PADRAO
```

(`DIAS_SEM_PROSPECCAO_PADRAO = 30` fica junto de `AJUSTES_PADRAO` para estar definido aqui
e na Task 3.)

- [ ] **Step 4: rodar** → PASS.
- [ ] **Step 5: commit** `feat(follow-up): ajuste dias_sem_prospeccao_apos_venda (default 30)`

---

### Task 5: varredura lê vendas (paginando) e aplica as regras

**Files:**
- Modify: `backend/app/follow_up/service.py` (`_vendas_dos_leads`, `_deals_criados_em` depois de `_jobs_joao_dos_leads`; `_varrer_cadencia_joao`; `agendar_cadencias_joao` usa `cadencias_do_funil`)
- Test: `backend/tests/test_cs_p6_varredura.py`

- [ ] **Step 1: teste falhando**

```python
"""P6 — a varredura do João consulta `sales` (paginando) antes de matricular."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.follow_up import service as S
from tests.test_agendador_joao_2026_09_18 import JOAO_CHANNEL, _ligada, _linha_rpc
from tests.test_followup_joao_duplicacao_2026_10_05 import (
    _BancoComTeto, _leads_matriculados)

# Terça 06/10/2026 12:00 BRT — dentro da janela comercial.
NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)
KIT_LIGADO = {"reposicao_atacado": {"kit": {"ativa": True, "toques": {
    1: {"template_name": "followjoao_kit_1"}, 2: {"template_name": "followjoao_kit_2"}}}}}


def _iso(dias):
    return (NOW - timedelta(days=dias)).isoformat()


def _venda(lead, dias, *, id=None, status="registrada", deal=None):
    return {"id": id or f"s-{lead}-{dias}", "lead_id": lead, "deal_id": deal,
            "sold_at": _iso(dias), "created_at": _iso(dias), "status": status}


def _rodar(banco, overrides):
    with (
        patch("app.follow_up.service.get_supabase", return_value=banco),
        patch("app.follow_up.service.carregar_overrides_joao", return_value=overrides),
        patch("app.follow_up.service.carregar_ajustes_joao",
              return_value={"teto_diario_disparos": 100, "adiamento_estoque_dias": 30}),
        patch("app.follow_up.service.get_channel_by_provider_config",
              return_value=JOAO_CHANNEL),
        patch("app.follow_up.service.get_or_create_conversation",
              side_effect=lambda lead_id, ch: {"id": f"conv-{lead_id}"}),
        patch("app.leads.service.is_lead_blacklisted", return_value=False),
        patch("app.follow_up.service.emit_event"),
    ):
        return S.agendar_cadencias_joao(now=NOW, teto=500)


def _proposta_so_no_atacado():
    return {"atacado": _ligada("proposta")["atacado"]}


def test_caso_real_proposta_nao_matricula_quem_comprou_em_outro_deal():
    banco = _BancoComTeto({
        "sales": [_venda("lead-comprou", 3, deal="deal-de-outro-card")],
        "deals": [{"id": "deal-comprou", "created_at": _iso(10)},
                  {"id": "deal-livre", "created_at": _iso(10)}],
    }, rpc_rows=[_linha_rpc(lead="lead-comprou", deal="deal-comprou"),
                 _linha_rpc(lead="lead-livre", deal="deal-livre")])
    _rodar(banco, _proposta_so_no_atacado())
    assert _leads_matriculados(banco) == {"lead-livre"}


def test_venda_depois_da_criacao_do_card_tambem_pula():
    banco = _BancoComTeto({
        "sales": [_venda("lead-a", 60)],
        "deals": [{"id": "deal-a", "created_at": _iso(90)}],
    }, rpc_rows=[_linha_rpc(lead="lead-a", deal="deal-a")])
    _rodar(banco, _proposta_so_no_atacado())
    assert banco.inserts == []


def test_leitura_de_vendas_pagina_acima_de_1000_linhas():
    # 1.200 vendas CANCELADAS antigas na frente; a venda que conta é a 1.201ª.
    antigas = [_venda("lead-a", 400, id=f"c{i:05d}", status="cancelada") for i in range(1200)]
    recente = _venda("lead-a", 2, id="z-recente")
    banco = _BancoComTeto({
        "sales": antigas + [recente],
        "deals": [{"id": "deal-a", "created_at": _iso(10)}],
    }, rpc_rows=[_linha_rpc(lead="lead-a", deal="deal-a")])
    _rodar(banco, _proposta_so_no_atacado())
    assert banco.inserts == []


def test_vendas_pedidas_em_lotes_de_ate_200_leads():
    linhas = [_linha_rpc(lead=f"lead-{i}", deal=f"deal-{i}") for i in range(450)]
    banco = _BancoComTeto({"sales": [], "deals": []}, rpc_rows=linhas)
    _rodar(banco, _proposta_so_no_atacado())
    lotes = [len(val) for nome, filtros, _f in banco.selects if nome == "sales"
             for op, col, val in filtros if op == "in" and col == "lead_id"]
    assert lotes and max(lotes) <= 200


def test_falha_ao_ler_vendas_nao_matricula_ninguem():
    class _SemVendas(_BancoComTeto):
        def table(self, nome):
            if nome == "sales":
                raise RuntimeError("statement timeout")
            return super().table(nome)

    banco = _SemVendas({"deals": []}, rpc_rows=[_linha_rpc(lead="lead-a", deal="deal-a")])
    _rodar(banco, _proposta_so_no_atacado())
    assert banco.inserts == []


def test_kit_matricula_so_quem_tem_kit_como_ultima_compra_ha_20_dias():
    banco = _BancoComTeto({
        "sales": [_venda("lead-kit", 20, id="s-kit"), _venda("lead-normal", 25, id="s-cafe"),
                  _venda("lead-recente", 19, id="s-kit-novo")],
        "sale_items": [
            {"id": "i1", "sale_id": "s-kit", "bling_product_id": 16536419853,
             "descricao": "Kit Degustação"},
            {"id": "i2", "sale_id": "s-cafe", "bling_product_id": 1,
             "descricao": "Café Clássico Moído 250g"},
            {"id": "i3", "sale_id": "s-kit-novo", "bling_product_id": 9256328993,
             "descricao": "KIT DEGUSTAÇÃO"},
        ],
    }, rpc_rows=[_linha_rpc(lead="lead-kit", deal="deal-kit"),
                 _linha_rpc(lead="lead-normal", deal="deal-normal"),
                 _linha_rpc(lead="lead-recente", deal="deal-recente")])
    _rodar(banco, KIT_LIGADO)

    assert _leads_matriculados(banco) == {"lead-kit"}
    jobs = [row for _t, rows in banco.inserts for row in rows]
    assert [j["job_type"] for j in jobs] == ["joao_kit", "joao_kit"]  # sem job de mover
    assert [j["metadata"]["template_name"] for j in jobs] == \
        ["followjoao_kit_1", "followjoao_kit_2"]
    assert {j["metadata"]["funil"] for j in jobs} == {"reposicao_atacado"}


def test_kit_desligado_nao_varre_nem_le_vendas():
    banco = _BancoComTeto({"sales": [_venda("lead-kit", 30)]},
                          rpc_rows=[_linha_rpc(lead="lead-kit", deal="deal-kit")])
    assert _rodar(banco, {}) == 0
    assert banco.inserts == []
    assert not any(nome == "sales" for nome, _f, _r in banco.selects)
```

- [ ] **Step 2: rodar** → FAIL (proposta matricula `lead-comprou`; kit não varre).

- [ ] **Step 3: implementação**

Leitores (depois de `_jobs_do_card`):

```python
def _lotes(ids: list[str]):
    for i in range(0, len(ids), _LOTE_DE_LEADS):
        yield ids[i:i + _LOTE_DE_LEADS]


def _vendas_dos_leads(
    sb, lead_ids: list[str], *, com_kit: bool,
) -> dict[str, list[dict]] | None:
    """`{lead_id: [vendas]}` dos candidatos, paginando (teto de 1.000 do PostgREST).

    Com `com_kit`, cada venda não cancelada ganha `kit: bool` lido de `sale_items`.
    Lead sem venda simplesmente não aparece (`.get(lead, [])` = "li, e não há").
    FAIL-CLOSED: qualquer erro devolve None e a passagem não matricula ninguém — sem
    saber se o lead comprou, não se manda prospecção (nem kit).
    """
    from app.follow_up.kit import venda_e_kit

    vendas: dict[str, list[dict]] = {}
    try:
        for lote in _lotes(lead_ids):
            for linha in _ler_todas_as_paginas(lambda lote=lote: sb.table("sales").select(
                    "id, lead_id, sold_at, created_at, status"
            ).in_("lead_id", lote).order("id")):
                vendas.setdefault(linha.get("lead_id"), []).append(dict(linha))
        if com_kit:
            por_id = {v["id"]: v for vs in vendas.values() for v in vs
                      if v.get("id") and not _venda_cancelada(v)}
            itens: dict[str, list[dict]] = {}
            for lote in _lotes(sorted(por_id)):
                for item in _ler_todas_as_paginas(
                        lambda lote=lote: sb.table("sale_items").select(
                            "id, sale_id, bling_product_id, descricao"
                        ).in_("sale_id", lote).order("id")):
                    itens.setdefault(item.get("sale_id"), []).append(item)
            for sale_id, venda in por_id.items():
                venda["kit"] = venda_e_kit(itens.get(sale_id))
    except Exception as exc:
        logger.error("[JOAO_CADENCIA] falha ao ler as vendas dos candidatos: %s", exc)
        return None
    return vendas


def _deals_criados_em(sb, deal_ids: list[str]) -> dict[str, datetime | None] | None:
    """`{deal_id: created_at}` dos cards candidatos, paginando. None = erro (fail-closed)."""
    criados: dict[str, datetime | None] = {}
    try:
        for lote in _lotes(deal_ids):
            for linha in _ler_todas_as_paginas(lambda lote=lote: sb.table("deals").select(
                    "id, created_at").in_("id", lote).order("id")):
                criados[str(linha.get("id"))] = _parse_ts(linha.get("created_at"))
    except Exception as exc:
        logger.error("[JOAO_CADENCIA] falha ao ler a criação dos cards: %s", exc)
        return None
    return criados
```

Em `_varrer_cadencia_joao`, depois do `if jobs is None: return 0, 0`:

```python
    # REGRA DE VENDA (spec 2026-10-06, P6). Lida em LOTE, uma vez por passagem, e
    # fail-closed: sem saber se o lead comprou, ninguém entra nesta passagem.
    vendas_por_lead: dict[str, list[dict]] | None = None
    criado_em_por_deal: dict[str, datetime | None] = {}
    dias_sem_prospeccao = DIAS_SEM_PROSPECCAO_PADRAO
    if cadencia.codigo in CADENCIAS_COM_REGRA_DE_VENDA:
        lead_ids = sorted({l["lead_id"] for l in linhas if l.get("lead_id")})
        vendas_por_lead = _vendas_dos_leads(
            sb, lead_ids, com_kit=cadencia.codigo == CADENCIA_KIT)
        if vendas_por_lead is None:
            return 0, 0
        if cadencia.codigo in CADENCIAS_DE_PROSPECCAO:
            deal_ids = sorted({str(l["deal_id"]) for l in linhas if l.get("deal_id")})
            criados = _deals_criados_em(sb, deal_ids)
            if criados is None:
                return 0, 0
            criado_em_por_deal = criados
            dias_sem_prospeccao = carregar_dias_sem_prospeccao_apos_venda(sb)
```

e a chamada no laço vira:

```python
        motivo = motivo_para_pular_joao(
            cadencia, do_card, now,
            vendas=(None if vendas_por_lead is None
                    else vendas_por_lead.get(lead_id, [])),
            deal_criado_em=criado_em_por_deal.get(str(deal_id)),
            dias_sem_prospeccao=dias_sem_prospeccao,
        )
```

Em `agendar_cadencias_joao`: `for cadencia_do_codigo in f.cadencias:` →
`for cadencia_do_codigo in cadencias_do_funil(f.codigo):` (comentário: inclui as
complementares, como o kit).

- [ ] **Step 4: rodar** `tests/test_cs_p6_varredura.py tests/test_agendador_joao_2026_09_18.py tests/test_followup_joao_duplicacao_2026_10_05.py` → PASS.
- [ ] **Step 5: commit** `feat(follow-up): varredura do João pula quem comprou e matricula o kit`

---

### Task 6: mesma checagem no envio (`lead_comprou`)

**Files:**
- Modify: `backend/app/follow_up/service.py` (`motivo_venda_no_envio`)
- Modify: `backend/app/follow_up/scheduler.py` (import + bloco depois de `card_mudou_de_etapa`)
- Test: `backend/tests/test_cs_p6_envio.py`

- [ ] **Step 1: teste falhando**

```python
"""P6 / Task 6.2 — o envio relê as vendas e cancela com `lead_comprou`."""
from datetime import timedelta
from types import SimpleNamespace

from app.follow_up import scheduler as S
from tests import test_scheduler_joao_2026_09_18 as T

NOW = T.NOW


def _iso(dias):
    return (NOW - timedelta(days=dias)).isoformat()


def _venda(dias, *, id="s1", status="registrada", lead="lead-1"):
    return {"id": id, "lead_id": lead, "sold_at": _iso(dias), "created_at": _iso(dias),
            "status": status}


class _TabelaVendas:
    def __init__(self, vendas):
        self.vendas, self.lead = vendas, None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        if col == "lead_id":
            self.lead = val
        return self

    def execute(self):
        return SimpleNamespace(data=[v for v in self.vendas if v["lead_id"] == self.lead])


class _ComVendas(T._FakeSupabase):
    def __init__(self, deals, vendas, stages=None, quebra=False):
        super().__init__(deals, stages)
        self.vendas, self.quebra = vendas, quebra

    def table(self, nome):
        if nome == "sales":
            if self.quebra:
                raise RuntimeError("statement timeout")
            return _TabelaVendas(self.vendas)
        return super().table(nome)


def _db(vendas, *, deal_criado_dias=200, quebra=False):
    return _ComVendas(
        deals={"deal-1": {"id": "deal-1", "pipeline_id": S.PIPELINE_JOAO_ATACADO,
                          "stage_id": T.ETAPA_NOVO_ATACADO,
                          "created_at": _iso(deal_criado_dias)}},
        vendas=vendas, quebra=quebra)


def _db_kit(vendas):
    return _ComVendas(
        deals={"deal-1": {"id": "deal-1", "pipeline_id": S.PIPELINE_JOAO_REPOSICAO_ATACADO,
                          "stage_id": T.ETAPA_CLIENTE_ATIVO_REPOSICAO,
                          "created_at": _iso(30)}},
        vendas=vendas, stages=T.ETAPAS_COM_REPOSICAO)


def _job_kit():
    return T._joao_job(job_type="joao_kit", metadata={
        "cadencia": "kit", "funil": "reposicao_atacado", "toque": 2,
        "template_name": "followjoao_kit_2", "matricula_em": _iso(7)})


def test_toque_de_prospeccao_e_cancelado_quando_o_lead_comprou():
    calls = T._run_handler(T._joao_job(), sb=_db([_venda(2)]))
    calls["cancel"].assert_called_once_with("job-joao-1", "lead_comprou")
    calls["meta"].send_template.assert_not_awaited()


def test_venda_depois_da_criacao_do_card_cancela_mesmo_antiga():
    calls = T._run_handler(T._joao_job(), sb=_db([_venda(60)], deal_criado_dias=90))
    calls["cancel"].assert_called_once_with("job-joao-1", "lead_comprou")


def test_sem_venda_o_toque_sai():
    calls = T._run_handler(T._joao_job(), sb=_db([]))
    calls["meta"].send_template.assert_awaited_once()
    calls["cancel"].assert_not_called()


def test_venda_cancelada_nao_segura_o_toque():
    calls = T._run_handler(T._joao_job(), sb=_db([_venda(2, status="cancelada")]))
    calls["meta"].send_template.assert_awaited_once()


def test_falha_ao_ler_vendas_adia_sem_estado_terminal():
    calls = T._run_handler(T._joao_job(), sb=_db([], quebra=True))
    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_not_called()
    calls["sent"].assert_not_called()


def test_kit_cancela_se_o_lead_comprou_depois_da_matricula():
    calls = T._run_handler(_job_kit(), sb=_db_kit([_venda(27, id="kit"), _venda(1, id="nova")]))
    calls["cancel"].assert_called_once_with("job-joao-1", "lead_comprou")
    calls["meta"].send_template.assert_not_awaited()


def test_kit_sem_compra_nova_sai():
    calls = T._run_handler(_job_kit(), sb=_db_kit([_venda(27, id="kit")]))
    calls["meta"].send_template.assert_awaited_once()


def test_reposicao_nao_e_afetada_pela_regra():
    job = T._joao_job(job_type="joao_reposicao", metadata={
        "cadencia": "reposicao", "funil": "reposicao_atacado", "toque": 2,
        "template_name": "joao_reposicao_atacado_t2"})
    calls = T._run_handler(job, sb=_db_kit([_venda(1)]))
    calls["meta"].send_template.assert_awaited_once()
```

- [ ] **Step 2: rodar** → FAIL (envio sai mesmo com venda).

- [ ] **Step 3: implementação**

Em `service.py`, depois de `comprou_depois_da_matricula`... (precisa de
`carregar_dias_sem_prospeccao_apos_venda`, então fica depois dela):

```python
def motivo_venda_no_envio(
    sb, codigo: str, *, lead_id: str | None, deal_id: str | None,
    matricula_em: Any, now: datetime,
) -> str | None:
    """A regra de venda na HORA DO ENVIO (spec 2026-10-06, P6.1). None = pode enviar.

    Uma leitura por lead e não paginada — mesmo raciocínio de `templates_do_joao_hoje`:
    as vendas de UM lead são poucas. Erro PROPAGA: quem chama não envia sem a resposta.

      prospecção -> `lead_comprou` (mesma regra da matrícula, com o N do ajuste)
      kit        -> `lead_comprou` se houve venda nova depois da matrícula
    """
    if codigo not in CADENCIAS_COM_REGRA_DE_VENDA:
        return None
    if not lead_id:
        return "sem_lead_para_verificar"
    res = sb.table("sales").select(
        "id, lead_id, sold_at, created_at, status").eq("lead_id", lead_id).execute()
    vendas = res.data if isinstance(res.data, list) else []

    if codigo == CADENCIA_KIT:
        referencia = _parse_ts(matricula_em)
        if referencia is None:
            return "kit_sem_matricula"
        return (MOTIVO_LEAD_COMPROU
                if comprou_depois_da_matricula(vendas, matricula_em=referencia) else None)

    deal_criado_em = None
    if deal_id:
        res_deal = sb.table("deals").select("id, created_at").eq(
            "id", deal_id).limit(1).execute()
        linhas = res_deal.data if isinstance(res_deal.data, list) else []
        deal_criado_em = _parse_ts(linhas[0].get("created_at")) if linhas else None
    dias = carregar_dias_sem_prospeccao_apos_venda(sb)
    if lead_comprou(vendas, now=now, deal_criado_em=deal_criado_em, dias=dias):
        return MOTIVO_LEAD_COMPROU
    return None
```

Em `scheduler.py`, importar `CADENCIAS_COM_REGRA_DE_VENDA` e `motivo_venda_no_envio` de
`app.follow_up.service` (o bloco de import que já traz `carregar_ajustes_joao`) e, logo
depois do `return` do `card_mudou_de_etapa`:

```python
    # ── Quem comprou não recebe prospecção (spec 2026-10-06, P6.1) ───────────────
    # A matrícula já pula quem comprou, mas agenda todos os toques de uma vez: a venda
    # que acontece no meio da cadência só é vista AQUI. Mesmo tratamento da guarda de
    # etapa: erro de leitura não envia e não encerra (transitório).
    if cadencia.codigo in CADENCIAS_COM_REGRA_DE_VENDA:
        try:
            motivo_venda = motivo_venda_no_envio(
                get_supabase(), cadencia.codigo, lead_id=job.get("lead_id"),
                deal_id=deal_id,
                matricula_em=metadata.get("matricula_em") or job.get("created_at"),
                now=now,
            )
        except Exception as exc:
            logger.error(
                "[JOAO_TOUCH] falha ao conferir as vendas do lead %s: %s — toque ADIADO "
                "para o próximo tick", job.get("lead_id"), exc, exc_info=True)
            return  # transitório → nada de estado terminal
        if motivo_venda:
            _cancel_job(job["id"], motivo_venda)
            logger.info(
                "[JOAO_TOUCH] lead %s comprou — esteira %s/%s encerrada no toque %s "
                "(job %s, motivo %s)", job.get("lead_id"), funil, cadencia.codigo,
                metadata.get("toque"), job["id"], motivo_venda)
            return
```

- [ ] **Step 4: rodar** `tests/test_cs_p6_envio.py tests/test_scheduler_joao_2026_09_18.py` → PASS.
- [ ] **Step 5: commit** `feat(follow-up): envio do João cancela com lead_comprou`

---

### Task 7: migração `20261006c_followup_kit.sql`

**Files:**
- Create: `supabase/migrations/20261006c_followup_kit.sql`
- Test: `backend/tests/test_cs_p6_migracao_kit.py`

- [ ] **Step 1: teste falhando (texto cruzado com o código)**

```python
"""P6 — a migração 20261006c espelha o código: pares, toques e a chave do ajuste."""
import re
from pathlib import Path

import pytest

from app.follow_up import cadence_joao as C
from app.follow_up import service as S

SQL = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
       / "20261006c_followup_kit.sql")


@pytest.fixture(scope="module")
def sql():
    return SQL.read_text(encoding="utf-8")


def test_cada_funil_aceita_exatamente_as_cadencias_do_codigo(sql):
    for f in C.FUNIS:
        esperado = sorted(c.codigo for c in C.cadencias_do_funil(f.codigo))
        m = re.search(rf"funil\s*=\s*'{f.codigo}'\s+AND\s+cadencia\s+IN\s*\(([^)]*)\)",
                      sql, re.I)
        if not esperado:
            assert m is None, f.codigo
            continue
        assert m, f.codigo
        assert sorted(t.strip().strip("'") for t in m.group(1).split(",")) == esperado


def test_o_check_de_toques_bate_com_o_codigo(sql):
    maior: dict[str, int] = {}
    for f in C.FUNIS:
        for c in C.cadencias_do_funil(f.codigo):
            maior[c.codigo] = max(maior.get(c.codigo, 0), len(c.touches))
    for codigo, n in maior.items():
        if n == 1:
            assert re.search(rf"cadencia = '{codigo}'\s+AND\s+toque = 1", sql), codigo
        else:
            assert re.search(
                rf"cadencia = '{codigo}'\s+AND\s+toque BETWEEN 1 AND {n}\b", sql), codigo


def test_a_chave_do_ajuste_novo_e_as_antigas(sql):
    m = re.search(r"chave\s+IN\s*\(([^)]*)\)", sql, re.I)
    assert m
    chaves = {t.strip().strip("'") for t in m.group(1).split(",")}
    assert chaves == set(S.AJUSTES_PADRAO) | {S.AJUSTE_DIAS_SEM_PROSPECCAO}


def test_reexecutavel_e_nao_semeia_nem_apaga(sql):
    assert len(re.findall(r"DROP CONSTRAINT IF EXISTS", sql)) == 3
    assert len(re.findall(r"ADD CONSTRAINT", sql)) == 3
    for proibido in (r"\bINSERT\b", r"\bDELETE\b", r"DROP\s+TABLE", r"TRUNCATE",
                     r"\bUPDATE\b"):
        assert not re.search(proibido, sql, re.I), proibido
    assert "follow_up_jobs" not in sql
    assert "NOTIFY pgrst" in sql
```

- [ ] **Step 2: rodar** → FAIL (arquivo não existe).

- [ ] **Step 3: a migração**

```sql
-- 20261006c_followup_kit.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. Roda a MAO, depois de revisada (como 20260918/20260926).
--
-- Pacote P6 da call semanal de 01/10 (spec 2026-10-06-call-semanal-0110-design.md, P6).
-- So ALARGA tres CHECKs; nao cria tabela, nao semeia, nao apaga, nao encosta em
-- follow_up_jobs. Toda linha que ja existe continua valida (os CHECKs novos sao
-- superconjuntos dos antigos).
--
--   followup_joao_cadencia_par_valido      + 'kit' nos dois funis de Reposicao
--   followup_joao_toque_dentro_da_cadencia + kit com toques 1..2
--   followup_joao_ajustes_chave_valida     + 'dias_sem_prospeccao_apos_venda'
--
-- A cadencia `kit` NASCE DESLIGADA sem linha nenhuma aqui: ausencia de linha = vale o
-- codigo, e o codigo traz `ativa=False` e os toques SEM template. Ligar (quando os
-- templates forem aprovados na Meta) e um INSERT a mao — ver o relatorio do P6.
-- O ajuste novo tambem nasce sem linha: vale o default de codigo (30 dias).
--
-- Reexecutar e seguro: DROP CONSTRAINT IF EXISTS + ADD, numa transacao.

BEGIN;

ALTER TABLE followup_joao_cadencia
  DROP CONSTRAINT IF EXISTS followup_joao_cadencia_par_valido;
ALTER TABLE followup_joao_cadencia
  ADD CONSTRAINT followup_joao_cadencia_par_valido CHECK (
       (funil = 'atacado'                 AND cadencia IN ('novo', 'em_conversa', 'proposta'))
    OR (funil = 'private_label'           AND cadencia IN ('novo', 'em_conversa', 'proposta'))
    OR (funil = 'reposicao_atacado'       AND cadencia IN ('reposicao', 'em_atencao', 'kit'))
    OR (funil = 'reposicao_private_label' AND cadencia IN ('reposicao', 'em_atencao', 'kit'))
  );

ALTER TABLE followup_joao_toque
  DROP CONSTRAINT IF EXISTS followup_joao_toque_dentro_da_cadencia;
ALTER TABLE followup_joao_toque
  ADD CONSTRAINT followup_joao_toque_dentro_da_cadencia CHECK (
       (cadencia = 'novo'        AND toque BETWEEN 1 AND 3)
    OR (cadencia = 'em_conversa' AND toque BETWEEN 1 AND 4)
    OR (cadencia = 'proposta'    AND toque BETWEEN 1 AND 4)
    OR (cadencia = 'reposicao'   AND toque BETWEEN 1 AND 4)
    OR (cadencia = 'em_atencao'  AND toque = 1)
    OR (cadencia = 'kit'         AND toque BETWEEN 1 AND 2)
  );

ALTER TABLE followup_joao_ajustes
  DROP CONSTRAINT IF EXISTS followup_joao_ajustes_chave_valida;
ALTER TABLE followup_joao_ajustes
  ADD CONSTRAINT followup_joao_ajustes_chave_valida CHECK (
    chave IN ('teto_diario_disparos', 'adiamento_estoque_dias',
              'dias_sem_prospeccao_apos_venda')
  );

COMMIT;

NOTIFY pgrst, 'reload schema';

-- Conferencia (nao altera nada):
--   SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conname IN ('followup_joao_cadencia_par_valido',
--                      'followup_joao_toque_dentro_da_cadencia',
--                      'followup_joao_ajustes_chave_valida');
```

- [ ] **Step 4: rodar** o teste de texto → PASS.
- [ ] **Step 5: teste real no Postgres descartável**

```bash
docker exec crm-scratch-pg psql -U postgres -c "drop database if exists p6;" \
  -c "create database p6 template crm_schema;"
cp /root/crm-wt/cs-p6/supabase/migrations/20261006_call_semanal_base.sql \
   /root/crm-wt/cs-p6/supabase/migrations/20261006c_followup_kit.sql /root/crm-wt/_scratchdb/
docker exec crm-scratch-pg psql -U postgres -d p6 -v ON_ERROR_STOP=1 -f /seed/20261006_call_semanal_base.sql
for i in 1 2; do docker exec crm-scratch-pg psql -U postgres -d p6 -v ON_ERROR_STOP=1 \
  -f /seed/20261006c_followup_kit.sql; done
```

Esperado: as duas execuções `COMMIT`. Depois, em transação com `ROLLBACK`:
- `insert into followup_joao_cadencia(funil,cadencia,ativa) values ('reposicao_atacado','kit',false)` → OK
- `... ('atacado','kit',false)` → ERRO `followup_joao_cadencia_par_valido`
- `insert into followup_joao_toque(funil,cadencia,toque,template_name) values ('reposicao_private_label','kit',2,'followjoao_kit_2')` → OK; toque 3 → ERRO
- `insert into followup_joao_ajustes(chave,valor) values ('dias_sem_prospeccao_apos_venda',30)` → OK; valor 0 → ERRO

- [ ] **Step 6: commit** `feat(follow-up): migração 20261006c — CHECKs aceitam o kit e o ajuste novo`

---

### Task 8: verificação e números de produção (somente leitura)

- [ ] Rodar com flock: `tests/test_cs_p6_*.py` + `tests/test_*joao*.py` +
  `tests/test_*cadenc*.py` + `tests/test_followup_*.py` (baseline sem P6: 1320 passed).
- [ ] Contagem em produção (SELECT puro) de jobs `pending` de prospecção que a regra
  cancelaria hoje no envio:

```sql
with j as (
  select id, lead_id, job_type, (metadata->>'deal_id')::uuid as deal_id
    from follow_up_jobs
   where status = 'pending'
     and job_type in ('joao_novo','joao_em_conversa','joao_proposta')
     and coalesce(metadata->>'acao','') <> 'mover_etapa')
select count(*) as jobs, count(distinct lead_id) as leads, count(distinct deal_id) as cards
  from j
 where exists (
   select 1 from sales s left join deals d on d.id = j.deal_id
    where s.lead_id = j.lead_id
      and lower(coalesce(s.status,'')) not like 'cancel%'
      and (coalesce(s.sold_at, s.created_at) is null
           or coalesce(s.sold_at, s.created_at) >= now() - interval '30 days'
           or coalesce(s.sold_at, s.created_at) > d.created_at));
```
