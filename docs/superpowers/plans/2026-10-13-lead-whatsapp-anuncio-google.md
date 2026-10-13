# Lead do botão de WhatsApp do anúncio Google — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Marcar como Google Ads (pago) o lead cuja mensagem é o texto pronto do botão de WhatsApp do anúncio Google, na entrada e retroativamente.

**Architecture:** Módulo novo `app/leads/google_message_asset.py` com a regra pura (texto → tracking) e o carimbo fail-soft no lead. Os `_register_lead` da Meta e da Evolution chamam o carimbo com o texto. Script de backfill com dry-run/apply/revert.

**Tech Stack:** Python 3.12, FastAPI, supabase-py, pytest (`backend/`, rodar com `SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_KEY=dummy python -m pytest -q -m "not integration" -p no:cacheprovider`).

Spec: `docs/superpowers/specs/2026-10-13-lead-whatsapp-anuncio-google-design.md`.

---

## File Structure

- Create `backend/app/leads/google_message_asset.py` — regra pura + carimbo.
- Create `backend/tests/test_google_message_asset.py` — testes da regra, do carimbo e do canal.
- Modify `backend/app/webhook/meta_router.py` — `_register_lead` ganha `text`; call site passa `msg.text`.
- Modify `backend/app/webhook/router.py` — `_register_lead` (Evolution) ganha `text`; call site passa `msg.text`.
- Create `backend/tests/test_google_message_asset_webhooks.py`.
- Create `backend/scripts/backfill_google_message_asset.py` + `backend/tests/test_backfill_google_message_asset.py`.

---

### Task 1: Regra pura + carimbo

**Files:** Create `backend/app/leads/google_message_asset.py`, `backend/tests/test_google_message_asset.py`

- [ ] **Step 1: Testes (falhando)**

```python
"""Lead do botão de WhatsApp do anúncio Google (message asset): o texto pronto é a única pista."""
from unittest.mock import patch

import pytest

from app.leads.google_message_asset import (
    GOOGLE_ASSET_TRACKING,
    google_message_asset_tracking,
    stamp_google_message_asset,
)

TEXTO = "Olá, encontrei vocês pelo Google e gostaria de obter mais informações."


@pytest.mark.parametrize("text", [
    TEXTO,
    "ola, encontrei voces pelo google e gostaria de obter mais informacoes",
    "  OLÁ,   ENCONTREI VOCÊS PELO GOOGLE  ",
    TEXTO + " Quero revender café.",
])
def test_reconhece_texto_do_botao(text):
    assert google_message_asset_tracking(text) == {"utm_source": "google", "utm_medium": "cpc"}


@pytest.mark.parametrize("text", [None, "", "Olá", "Boa tarde", "achei no google maps", "vi no google"])
def test_nao_reconhece_outros_textos(text):
    assert google_message_asset_tracking(text) is None


def test_carimba_lead_sem_atribuicao():
    with patch("app.leads.google_message_asset.update_lead") as upd:
        assert stamp_google_message_asset({"id": "L1"}, TEXTO) is True
    upd.assert_called_once_with("L1", utm_source="google", utm_medium="cpc", traffic_type="paid")


@pytest.mark.parametrize("col", ["gclid", "fbclid", "ctwa_clid", "meta_ad_id", "utm_source", "utm_medium", "utm_campaign"])
def test_nao_sobrescreve_atribuicao_existente(col):
    with patch("app.leads.google_message_asset.update_lead") as upd:
        assert stamp_google_message_asset({"id": "L1", col: "x"}, TEXTO) is False
    upd.assert_not_called()


def test_texto_comum_nao_carimba():
    with patch("app.leads.google_message_asset.update_lead") as upd:
        assert stamp_google_message_asset({"id": "L1"}, "Bom dia") is False
    upd.assert_not_called()


def test_sem_lead_nao_carimba():
    with patch("app.leads.google_message_asset.update_lead") as upd:
        assert stamp_google_message_asset(None, TEXTO) is False
        assert stamp_google_message_asset({}, TEXTO) is False
    upd.assert_not_called()


def test_erro_do_banco_nao_propaga():
    with patch("app.leads.google_message_asset.update_lead", side_effect=RuntimeError("boom")):
        assert stamp_google_message_asset({"id": "L1"}, TEXTO) is False


def test_lead_carimbado_vira_google_ads_no_trafego():
    from app.campaigns.traffic_report import derive_channel
    assert derive_channel({**GOOGLE_ASSET_TRACKING, "traffic_type": "paid"}) == "Google Ads"
```

- [ ] **Step 2:** `python -m pytest tests/test_google_message_asset.py -q` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementação**

```python
"""Lead que chega pelo botão de WhatsApp do anúncio Google ("Iniciar conversa").

O Google não manda gclid nem UTM para o WhatsApp: a única pista é o texto pronto do botão,
"Olá, encontrei vocês pelo Google e gostaria de obter mais informações.". Quem chega com ele
é marcado como Google Ads pago (utm_source=google + utm_medium=cpc — o que derive_channel e o
lead-origin.ts do CRM já entendem como Google Ads). Sem campanha: o texto não a identifica.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any

from app.leads.service import update_lead

logger = logging.getLogger(__name__)

# Trecho do texto pronto, já normalizado (minúsculas, sem acento, espaços colapsados).
_MARCA = "encontrei voces pelo google"

GOOGLE_ASSET_TRACKING: dict[str, str] = {"utm_source": "google", "utm_medium": "cpc"}

# Qualquer uma preenchida = o lead já tem origem; o carimbo não sobrescreve.
_ATTRIBUTION_COLUMNS: tuple[str, ...] = (
    "gclid", "fbclid", "ctwa_clid", "meta_ad_id", "utm_source", "utm_medium", "utm_campaign",
)


def _normalize(text: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def google_message_asset_tracking(text: str | None) -> dict[str, str] | None:
    """Tracking de Google Ads se `text` for o texto pronto do botão; senão None."""
    if not text or _MARCA not in _normalize(text):
        return None
    return dict(GOOGLE_ASSET_TRACKING)


def has_attribution(lead: dict[str, Any]) -> bool:
    return any(str(lead.get(col) or "").strip() for col in _ATTRIBUTION_COLUMNS)


def stamp_google_message_asset(lead: dict[str, Any] | None, text: str | None) -> bool:
    """Carimba Google Ads no lead sem origem que mandou o texto do botão. Fail-soft.

    Retorna True se gravou."""
    if not lead or not lead.get("id"):
        return False
    tracking = google_message_asset_tracking(text)
    if not tracking or has_attribution(lead):
        return False
    try:
        update_lead(lead["id"], **tracking, traffic_type="paid")
    except Exception as exc:
        logger.warning("google_message_asset: falha ao carimbar lead %s: %s", lead.get("id"), exc)
        return False
    logger.info("google_message_asset: lead %s marcado como Google Ads (botao WhatsApp)", lead["id"])
    return True
```

- [ ] **Step 4:** rodar de novo → PASS.
- [ ] **Step 5:** `git add backend/app/leads/google_message_asset.py backend/tests/test_google_message_asset.py && git commit -m "feat(google-whatsapp): regra e carimbo do lead do botao de WhatsApp do anuncio Google"`

---

### Task 2: Ligar nos webhooks (Meta e Evolution)

**Files:** Modify `backend/app/webhook/meta_router.py` (`_register_lead` linha ~35 e call site linha ~595), `backend/app/webhook/router.py` (`_register_lead` linha ~22 e call site no loop); Create `backend/tests/test_google_message_asset_webhooks.py`

- [ ] **Step 1: Testes (falhando)**

```python
from unittest.mock import patch

TEXTO = "Olá, encontrei vocês pelo Google e gostaria de obter mais informações."


def test_meta_register_lead_carimba_com_o_texto():
    from app.webhook.meta_router import _register_lead
    lead = {"id": "L1", "wa_id": "5511999999999", "wa_id_confirmed_at": "x"}
    with patch("app.webhook.meta_router.get_or_create_lead", return_value=lead), \
         patch("app.webhook.meta_router.update_lead"), \
         patch("app.webhook.meta_router.stamp_google_message_asset") as stamp:
        _register_lead("5511999999999", "Maria", text=TEXTO)
    stamp.assert_called_once_with(lead, TEXTO)


def test_meta_register_lead_sem_texto_continua_funcionando():
    from app.webhook.meta_router import _register_lead
    lead = {"id": "L1", "wa_id": "5511999999999", "wa_id_confirmed_at": "x"}
    with patch("app.webhook.meta_router.get_or_create_lead", return_value=lead), \
         patch("app.webhook.meta_router.update_lead"), \
         patch("app.webhook.meta_router.stamp_google_message_asset") as stamp:
        _register_lead("5511999999999", "Maria")
    stamp.assert_called_once_with(lead, None)


def test_meta_register_lead_carimbo_que_explode_nao_derruba():
    from app.webhook.meta_router import _register_lead
    lead = {"id": "L1", "wa_id": "5511999999999", "wa_id_confirmed_at": "x"}
    with patch("app.webhook.meta_router.get_or_create_lead", return_value=lead), \
         patch("app.webhook.meta_router.update_lead"), \
         patch("app.webhook.meta_router.stamp_google_message_asset", side_effect=RuntimeError("x")):
        _register_lead("5511999999999", "Maria", text=TEXTO)  # não levanta


def test_evolution_register_lead_carimba_com_o_texto():
    from app.webhook.router import _register_lead
    lead = {"id": "L2"}
    with patch("app.webhook.router.get_or_create_lead", return_value=lead), \
         patch("app.webhook.router.stamp_google_message_asset") as stamp:
        _register_lead("5511988887777", "Joao", TEXTO)
    stamp.assert_called_once_with(lead, TEXTO)
```

E um teste de call site para garantir que o webhook Meta passa `msg.text` (seguir o padrão de `tests/test_ctwa_clid_tracking.py` / `tests/test_wa_id_and_resilience.py` para montar o request; se o call site for difícil de exercitar, basta verificar via `inspect.getsource` que o `add_task(_register_lead, ...)` passa `text=msg.text` — prefira o teste comportamental se houver padrão pronto).

- [ ] **Step 2:** rodar → FAIL.

- [ ] **Step 3: Implementação**

`meta_router.py`:
- import: `from app.leads.google_message_asset import stamp_google_message_asset`
- assinatura: acrescentar `text: str | None = None` como ÚLTIMO parâmetro de `_register_lead` (depois de `meta_ad_id`), e uma frase na docstring: "Botão de WhatsApp do anúncio Google: o texto pronto marca o lead sem origem como Google Ads (ver app.leads.google_message_asset)."
- no fim do corpo de `_register_lead` (depois do bloco do BSUID), novo bloco fail-soft:

```python
    # Botao de WhatsApp do anuncio Google: o texto pronto e a unica pista (sem gclid/UTM).
    try:
        stamp_google_message_asset(lead, text)
    except Exception as exc:
        logger.warning("Failed to stamp google message asset for lead %s: %s", lead.get("id") if lead else None, exc)
```

- call site: `background_tasks.add_task(_register_lead, msg.from_number, msg.push_name, msg.ctwa_clid, msg.ctwa_origem, msg.bsuid, msg.meta_ad_id, text=msg.text)`

`router.py` (Evolution, legado):

```python
from app.leads.google_message_asset import stamp_google_message_asset

def _register_lead(from_number: str, push_name: str | None, text: str | None = None) -> None:
    ...
    try:
        lead = get_or_create_lead(from_number, name=push_name, channel="whatsapp")
        stamp_google_message_asset(lead, text)
    except Exception as exc:
        logger.warning("Failed to register lead for %s: %s", from_number, exc)
```

- call site: `background_tasks.add_task(_register_lead, msg.from_number, msg.push_name, msg.text)`
- Não mexer no Dev Router (continua antes do parsing).

- [ ] **Step 4:** rodar os testes novos + `tests/test_ctwa_clid_tracking.py tests/test_ctwa_origem_attribution.py tests/test_wa_id_and_resilience.py tests/test_bsuid_dev_router_2026_07_01.py` → PASS.
- [ ] **Step 5:** commit `feat(google-whatsapp): webhooks Meta e Evolution carimbam o lead do botao Google`.

---

### Task 3: Backfill (dry-run / --apply / --revert)

**Files:** Create `backend/scripts/backfill_google_message_asset.py`, `backend/tests/test_backfill_google_message_asset.py`

Contrato:
- `find_candidates(sb) -> list[dict]`: busca mensagens `role='user'` com `content ilike '%encontrei voc%pelo google%'` (paginado de 1000 em 1000 via `.range`), pega os `lead_id` distintos; para cada lead, busca a PRIMEIRA mensagem `role='user'` (order `created_at` asc, limit 1) e só segue se `google_message_asset_tracking(content)` reconhecer; busca o lead (`id, phone, name, gclid, fbclid, ctwa_clid, meta_ad_id, utm_source, utm_medium, utm_campaign`) e só segue se `not has_attribution(lead)`. Retorna lista de `{"id", "phone", "name"}`.
- `apply(sb, candidates, out_dir) -> Path`: para cada id, `update({"utm_source":"google","utm_medium":"cpc","traffic_type":"paid"}).eq("id", id).is_("utm_source", "null")`; grava JSON `backfill_google_message_asset_<UTC yyyymmddTHHMMSS>.json` com `{"lead_ids": [...]}` e retorna o caminho.
- `revert(sb, path)`: para cada id do JSON, `update({"utm_source": None, "utm_medium": None, "traffic_type": None}).eq("id", id).eq("utm_source","google").eq("utm_medium","cpc")`.
- `main()`: argparse `--apply`, `--revert PATH`, `--out-dir` (default cwd). Sem flag = dry-run: imprime contagem e até 10 amostras (id, nome, telefone mascarado nos 4 últimos dígitos) e "DRY-RUN: nada gravado". Roda com `python -m scripts.backfill_google_message_asset` de dentro de `backend/`.

- [ ] **Step 1: Testes (falhando)** com um fake do supabase em memória: classe `FakeSB` que implementa `table(name)` retornando um query builder encadeável (`select`, `eq`, `ilike`, `is_`, `order`, `limit`, `range`, `update`, `execute`) sobre listas de dicts `messages` e `leads`. Casos:
  1. lead sem origem cuja 1ª mensagem é o texto → candidato;
  2. lead cuja 1ª mensagem é "Oi" e a 2ª é o texto → NÃO candidato;
  3. lead com `gclid` → NÃO candidato;
  4. `apply` grava os 3 campos só nos candidatos e o JSON contém exatamente os ids;
  5. `revert` volta os 3 campos a None só nos ids do JSON e não toca lead que já não está como google/cpc;
  6. dry-run (`main([])`) não chama `update`.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar o script (usa `from app.db.supabase import get_supabase` e importa `google_message_asset_tracking`, `has_attribution`, `GOOGLE_ASSET_TRACKING` de `app.leads.google_message_asset`; `main(argv=None)`).
- [ ] **Step 4:** rodar → PASS.
- [ ] **Step 5:** commit `feat(google-whatsapp): backfill dos leads antigos do botao Google (dry-run por padrao)`.

---

### Task 4: Verificação em modo teste

- [ ] Suíte inteira: `SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_KEY=dummy python -m pytest -q -m "not integration" -p no:cacheprovider` → tudo verde.
- [ ] Dry-run REAL contra produção, somente leitura: copiar `google_message_asset.py` e o script do branch para um diretório temporário dentro do container `canastra_api` (fora de `/app`, sem tocar no código em execução) e rodar o script SEM flag, com `PYTHONPATH` apontando primeiro para o temporário. Conferir ~130 candidatos e cruzar com um SELECT independente. Apagar o temporário depois.
- [ ] Prova do carimbo: rodar `stamp_google_message_asset` + `derive_channel` contra um lead fake (mocks), já coberto nos testes. Não há banco de teste nem tela nova.
