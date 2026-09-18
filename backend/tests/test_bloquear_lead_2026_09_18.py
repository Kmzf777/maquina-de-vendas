"""Bloquear/desbloquear lead pelo CRM (2026-09-18) — Task 1 do plano de bloqueio.

Plano: docs/superpowers/plans/2026-09-18-bloquear-lead-plan.md

O que estes testes protegem, em uma frase cada:
  - O caminho MANUAL grava `opt_out=true`. Até 18/09/2026 não gravava: o bloqueio do
    operador ficava apoiado só no braço "tem deal na Blacklist" de `is_lead_blacklisted`
    e sumia quando alguém arrastava o card no Kanban.
  - A degradação PGRST204 salva o booleano. Migration de evidência pendente não pode
    virar opt-out não honrado (o incidente dos cliques em "Não tenho interesse" com
    opt_out=false já custou caro uma vez).
  - O snapshot de origem dos cards é tirado ANTES de mover, e a segunda chamada de
    `block_lead` não o sobrescreve com "a origem é a Blacklist".
  - O desbloqueio NUNCA apaga a prova (`opt_out_at`/`opt_out_channel`/evidência) e NÃO
    adivinha destino de card sem snapshot.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.leads.service import (
    BLACKLIST_PIPELINE_ID,
    BLACKLIST_STAGE_ID,
    block_lead,
    unblock_lead,
)
from app.main import app

client = TestClient(app)

LEAD = "lead-bloq-1"
PHONE = "5534999990000"
ORIGEM_PIPELINE = "11111111-1111-1111-1111-111111111111"
ORIGEM_STAGE = "22222222-2222-2222-2222-222222222222"


# ---------------------------------------------------------------------------
# Fake do PostgREST: mínimo para select/update com filtros .eq(), gravando os writes.
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, sb, name):
        self._sb, self._name = sb, name
        self._filters: dict = {}
        self._op = "select"
        self._payload = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        linhas = self._sb.rows_for(self._name, self._filters)
        if self._op != "select":
            self._sb.writes.append((self._name, self._op, self._payload, dict(self._filters)))
        return _Resp(linhas)


class _SB:
    def __init__(self, **tabelas):
        self.data = {nome: [dict(r) for r in linhas] for nome, linhas in tabelas.items()}
        self.writes: list = []

    def table(self, name):
        return _Table(self, name)

    def rows_for(self, name, filters):
        return [
            r for r in self.data.get(name, [])
            if all(r.get(col) == val for col, val in filters.items())
        ]

    def updates(self, name):
        return [(p, f) for n, op, p, f in self.writes if n == name and op == "update"]


def _sb_padrao():
    """Um card fora da Blacklist e duas conversas ativas — o estado típico do bloqueio."""
    return _SB(
        deals=[{
            "id": "deal-1", "lead_id": LEAD,
            "pipeline_id": ORIGEM_PIPELINE, "stage_id": ORIGEM_STAGE,
        }],
        conversations=[
            {"id": "conv-1", "lead_id": LEAD, "status": "active"},
            {"id": "conv-2", "lead_id": LEAD, "status": "active"},
        ],
    )


def _lead_ativo(**extra):
    return {"id": LEAD, "phone": PHONE, "ai_enabled": True, "opt_out": False, **extra}


# ---------------------------------------------------------------------------
# block_lead — gravação canônica
# ---------------------------------------------------------------------------

def test_block_lead_grava_opt_out_e_desliga_ia():
    """O furo que a Task 1 conserta: o caminho manual precisa gravar o booleano canônico."""
    sb = _sb_padrao()
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=_lead_ativo()), \
         patch("app.leads.service.update_lead") as upd, \
         patch("app.leads.service.apply_optout_side_effects"), \
         patch("app.leads.service.save_message"):
        result = block_lead(LEAD, by="operador@canastra", reason="pediu no telefone")

    campos = upd.call_args.kwargs
    assert campos["opt_out"] is True
    assert campos["ai_enabled"] is False
    assert campos["opt_out_channel"] == "manual_crm"
    assert campos["opt_out_at"]
    prova = campos["opt_out_evidence"]
    assert prova["source"] == "crm_manual"
    assert prova["by"] == "operador@canastra"
    assert prova["reason"] == "pediu no telefone"
    assert result == {"blocked": True, "already": False, "deals": 1, "conversations": 2}


def test_block_lead_guarda_a_origem_dos_cards_na_evidencia():
    """Sem `restore` o desbloqueio não tem para onde devolver o card — o Kanban não guarda histórico."""
    sb = _sb_padrao()
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=_lead_ativo()), \
         patch("app.leads.service.update_lead") as upd, \
         patch("app.leads.service.apply_optout_side_effects"), \
         patch("app.leads.service.save_message"):
        block_lead(LEAD)

    snapshot = upd.call_args.kwargs["opt_out_evidence"]["restore"]
    assert snapshot["ai_enabled"] is True
    assert snapshot["deals"] == [
        {"id": "deal-1", "pipeline_id": ORIGEM_PIPELINE, "stage_id": ORIGEM_STAGE}
    ]
    assert {c["id"] for c in snapshot["conversations"]} == {"conv-1", "conv-2"}


def test_snapshot_e_tirado_antes_dos_side_effects():
    """Ordem é o ponto: `apply_optout_side_effects` move os cards e apaga a origem."""
    sb = _sb_padrao()

    def mover_para_blacklist(_lead_id, _phone, reason=None):
        for d in sb.data["deals"]:
            d["pipeline_id"] = BLACKLIST_PIPELINE_ID
            d["stage_id"] = BLACKLIST_STAGE_ID

    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=_lead_ativo()), \
         patch("app.leads.service.update_lead") as upd, \
         patch("app.leads.service.apply_optout_side_effects", side_effect=mover_para_blacklist), \
         patch("app.leads.service.save_message"):
        block_lead(LEAD)

    origem = upd.call_args.kwargs["opt_out_evidence"]["restore"]["deals"][0]
    assert origem["pipeline_id"] == ORIGEM_PIPELINE, "snapshot foi tirado depois de mover"
    assert origem["stage_id"] == ORIGEM_STAGE


# ---------------------------------------------------------------------------
# block_lead — degradação PGRST204 e fail-hard
# ---------------------------------------------------------------------------

def test_block_lead_degrada_para_o_booleano_quando_a_evidencia_falha():
    """Migration de evidência pendente → PGRST204 no update inteiro. O opt_out sobrevive."""
    gravacoes: list[dict] = []

    def fake_update(_lead_id, **fields):
        gravacoes.append(fields)
        if "opt_out_evidence" in fields:
            raise RuntimeError("PGRST204: column leads.opt_out_evidence does not exist")
        return {}

    sb = _sb_padrao()
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=_lead_ativo()), \
         patch("app.leads.service.update_lead", side_effect=fake_update), \
         patch("app.leads.service.apply_optout_side_effects") as side, \
         patch("app.leads.service.save_message"):
        result = block_lead(LEAD)

    assert len(gravacoes) == 2, "deveria ter tentado o completo e depois o nu"
    assert gravacoes[1] == {"ai_enabled": False, "opt_out": True}
    side.assert_called_once()  # o bloqueio segue inteiro, só sem a prova
    assert result["blocked"] is True


def test_block_lead_fail_hard_quando_nem_o_booleano_grava():
    """Fail-hard só aqui: sem `opt_out` não há bloqueio, e o operador precisa saber."""
    sb = _sb_padrao()
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=_lead_ativo()), \
         patch("app.leads.service.update_lead", side_effect=RuntimeError("db down")), \
         patch("app.leads.service.apply_optout_side_effects") as side, \
         patch("app.leads.service.save_message"):
        with pytest.raises(RuntimeError):
            block_lead(LEAD)

    side.assert_not_called()
    assert sb.updates("conversations") == []


def test_block_lead_fail_soft_nos_efeitos_colaterais():
    """Efeito colateral quebrado não desfaz um opt-out já gravado no banco."""
    sb = _sb_padrao()
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=_lead_ativo()), \
         patch("app.leads.service.update_lead"), \
         patch("app.leads.service.apply_optout_side_effects", side_effect=RuntimeError("blacklist off")), \
         patch("app.leads.service.save_message", side_effect=RuntimeError("messages off")):
        result = block_lead(LEAD)  # não pode levantar

    assert result["blocked"] is True
    assert sb.updates("conversations"), "conversas continuam sendo bloqueadas"


def test_block_lead_lead_inexistente_levanta_value_error():
    with patch("app.leads.service.get_lead", return_value=None):
        with pytest.raises(ValueError):
            block_lead("lead-fantasma")


# ---------------------------------------------------------------------------
# block_lead — idempotência e conversas
# ---------------------------------------------------------------------------

def test_block_lead_idempotente_nao_reaplica_efeitos():
    sb = _sb_padrao()
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=_lead_ativo(opt_out=True)), \
         patch("app.leads.service.update_lead") as upd, \
         patch("app.leads.service.apply_optout_side_effects") as side, \
         patch("app.leads.service.save_message") as msg:
        result = block_lead(LEAD)

    assert result == {"blocked": True, "already": True, "deals": 0, "conversations": 0}
    upd.assert_not_called()
    side.assert_not_called()
    msg.assert_not_called()


def test_segundo_block_nao_sobrescreve_o_snapshot_original():
    """O risco concreto: refotografar cards JÁ na Blacklist gravaria 'a origem é a Blacklist'."""
    lead = _lead_ativo()
    gravacoes: list[dict] = []

    def fake_update(_lead_id, **fields):
        gravacoes.append(fields)
        lead.update(fields)  # o lead em memória passa a refletir o que foi gravado
        return {}

    sb = _sb_padrao()
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", side_effect=lambda _id: dict(lead)), \
         patch("app.leads.service.update_lead", side_effect=fake_update), \
         patch("app.leads.service.apply_optout_side_effects"), \
         patch("app.leads.service.save_message"):
        block_lead(LEAD)
        # entre as duas chamadas o card foi para a Blacklist (é o que os side effects fazem)
        sb.data["deals"][0]["pipeline_id"] = BLACKLIST_PIPELINE_ID
        sb.data["deals"][0]["stage_id"] = BLACKLIST_STAGE_ID
        segundo = block_lead(LEAD)

    assert segundo["already"] is True
    assert len(gravacoes) == 1, "a segunda chamada não pode regravar nada"
    assert gravacoes[0]["opt_out_evidence"]["restore"]["deals"][0]["pipeline_id"] == ORIGEM_PIPELINE


def test_block_lead_chama_side_effects_e_zera_unread_count():
    sb = _sb_padrao()
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=_lead_ativo()), \
         patch("app.leads.service.update_lead"), \
         patch("app.leads.service.apply_optout_side_effects") as side, \
         patch("app.leads.service.save_message"):
        result = block_lead(LEAD)

    side.assert_called_once_with(LEAD, PHONE, reason="block_manual")
    payload, filtros = sb.updates("conversations")[0]
    assert payload == {"status": "blocked", "unread_count": 0}
    assert filtros == {"lead_id": LEAD}
    assert result["conversations"] == 2


# ---------------------------------------------------------------------------
# unblock_lead
# ---------------------------------------------------------------------------

def _evidencia_com_snapshot(**snapshot_extra):
    return {
        "source": "crm_manual",
        "registrado_em": "2026-09-18T10:00:00+00:00",
        "lead_id": LEAD,
        "canal": "manual_crm",
        "by": "operador@canastra",
        "restore": {
            "ai_enabled": False,
            "deals": [{"id": "deal-1", "pipeline_id": ORIGEM_PIPELINE, "stage_id": ORIGEM_STAGE}],
            "conversations": [{"id": "conv-1", "status": "active"}],
            **snapshot_extra,
        },
    }


def _sb_bloqueado():
    return _SB(
        deals=[{
            "id": "deal-1", "lead_id": LEAD,
            "pipeline_id": BLACKLIST_PIPELINE_ID, "stage_id": BLACKLIST_STAGE_ID,
        }],
        conversations=[{"id": "conv-1", "lead_id": LEAD, "status": "blocked"}],
    )


def test_unblock_lead_restaura_o_card_para_o_funil_de_origem():
    sb = _sb_bloqueado()
    lead = {
        "id": LEAD, "phone": PHONE, "opt_out": True,
        "opt_out_at": "2026-09-18T10:00:00+00:00", "opt_out_channel": "manual_crm",
        "opt_out_evidence": _evidencia_com_snapshot(),
    }
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=lead), \
         patch("app.leads.service.update_lead") as upd, \
         patch("app.leads.service.save_message"):
        result = unblock_lead(LEAD, by="gerente@canastra")

    payload, filtros = sb.updates("deals")[0]
    assert payload["pipeline_id"] == ORIGEM_PIPELINE
    assert payload["stage_id"] == ORIGEM_STAGE
    assert filtros == {"id": "deal-1"}
    # `ai_enabled` volta como estava ANTES do bloqueio (aqui: já desligado)
    assert upd.call_args.kwargs["ai_enabled"] is False
    assert upd.call_args.kwargs["opt_out"] is False
    assert result == {"blocked": False, "deals_restaurados": 1, "deals_pendentes": 0}


def test_unblock_lead_preserva_a_prova_e_so_acrescenta_a_revogacao():
    """LGPD art. 18 §2: quando e por onde a pessoa se opôs continua sendo verdade."""
    sb = _sb_bloqueado()
    lead = {
        "id": LEAD, "opt_out": True,
        "opt_out_at": "2026-09-18T10:00:00+00:00", "opt_out_channel": "manual_crm",
        "opt_out_evidence": _evidencia_com_snapshot(),
    }
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=lead), \
         patch("app.leads.service.update_lead") as upd, \
         patch("app.leads.service.save_message"):
        unblock_lead(LEAD, by="gerente@canastra")

    campos = upd.call_args.kwargs
    assert "opt_out_at" not in campos, "a data do opt-out nunca é reescrita"
    assert "opt_out_channel" not in campos, "o canal do opt-out nunca é reescrito"
    prova = campos["opt_out_evidence"]
    assert prova["registrado_em"] == "2026-09-18T10:00:00+00:00"
    assert prova["canal"] == "manual_crm"
    assert prova["by"] == "operador@canastra"
    assert prova["restore"]["deals"][0]["pipeline_id"] == ORIGEM_PIPELINE
    assert prova["revogado"]["por"] == "gerente@canastra"
    assert prova["revogado"]["em"]


def test_unblock_lead_sem_snapshot_nao_inventa_destino():
    """Lead bloqueado antes desta entrega: contar em `deals_pendentes` e deixar o card parado."""
    sb = _sb_bloqueado()
    lead = {"id": LEAD, "opt_out": True, "opt_out_evidence": None}
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=lead), \
         patch("app.leads.service.update_lead") as upd, \
         patch("app.leads.service.save_message"):
        result = unblock_lead(LEAD)

    assert result == {"blocked": False, "deals_restaurados": 0, "deals_pendentes": 1}
    assert sb.updates("deals") == [], "nenhum card pode ser movido no chute"
    # Sem snapshot, a IA volta ligada (default explícito).
    assert upd.call_args.kwargs["ai_enabled"] is True


def test_unblock_lead_degrada_para_o_booleano_quando_a_evidencia_falha():
    gravacoes: list[dict] = []

    def fake_update(_lead_id, **fields):
        gravacoes.append(fields)
        if "opt_out_evidence" in fields:
            raise RuntimeError("PGRST204: column leads.opt_out_evidence does not exist")
        return {}

    sb = _sb_bloqueado()
    lead = {"id": LEAD, "opt_out": True, "opt_out_evidence": _evidencia_com_snapshot()}
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=lead), \
         patch("app.leads.service.update_lead", side_effect=fake_update), \
         patch("app.leads.service.save_message"):
        result = unblock_lead(LEAD)

    assert gravacoes[1] == {"opt_out": False, "ai_enabled": False}
    assert result["blocked"] is False


def test_unblock_lead_reativa_a_conversa_bloqueada():
    sb = _sb_bloqueado()
    lead = {"id": LEAD, "opt_out": True, "opt_out_evidence": _evidencia_com_snapshot()}
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=lead), \
         patch("app.leads.service.update_lead"), \
         patch("app.leads.service.save_message"):
        unblock_lead(LEAD)

    payload, filtros = sb.updates("conversations")[0]
    assert payload == {"status": "active"}
    assert filtros == {"id": "conv-1"}


def test_unblock_lead_lead_inexistente_levanta_value_error():
    with patch("app.leads.service.get_lead", return_value=None):
        with pytest.raises(ValueError):
            unblock_lead("lead-fantasma")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _patches_de_bloqueio(sb, lead):
    return (
        patch("app.leads.service.get_supabase", return_value=sb),
        patch("app.leads.service.get_lead", return_value=lead),
        patch("app.leads.service.apply_optout_side_effects"),
        patch("app.leads.service.save_message"),
    )


def test_endpoint_optout_agora_grava_opt_out():
    """Regressão do furo: POST /optout resultava em opt_out=False. Nunca mais."""
    sb = _sb_padrao()
    p1, p2, p3, p4 = _patches_de_bloqueio(sb, _lead_ativo())
    with p1, p2, p3, p4, patch("app.leads.service.update_lead") as upd:
        r = client.post(f"/api/leads/{LEAD}/optout")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"      # contrato que o chat-view.tsx já consome
    assert body["blocked"] is True
    assert upd.call_args.kwargs["opt_out"] is True
    assert upd.call_args.kwargs["opt_out_evidence"]["reason"] == "optout_manual"


def test_endpoint_block_devolve_contadores():
    sb = _sb_padrao()
    p1, p2, p3, p4 = _patches_de_bloqueio(sb, _lead_ativo())
    with p1, p2, p3, p4, patch("app.leads.service.update_lead"):
        r = client.post(f"/api/leads/{LEAD}/block", json={"by": "operador@canastra"})

    assert r.status_code == 200
    assert r.json() == {
        "status": "ok", "blocked": True, "already": False, "deals": 1, "conversations": 2,
    }


def test_endpoint_block_404_para_lead_inexistente():
    with patch("app.leads.service.get_lead", return_value=None):
        r = client.post("/api/leads/lead-fantasma/block")
    assert r.status_code == 404


def test_endpoint_unblock_devolve_deals_pendentes():
    sb = _sb_bloqueado()
    lead = {"id": LEAD, "opt_out": True, "opt_out_evidence": None}
    with patch("app.leads.service.get_supabase", return_value=sb), \
         patch("app.leads.service.get_lead", return_value=lead), \
         patch("app.leads.service.update_lead"), \
         patch("app.leads.service.save_message"):
        r = client.post(f"/api/leads/{LEAD}/unblock")

    assert r.status_code == 200
    assert r.json() == {
        "status": "ok", "blocked": False, "deals_restaurados": 0, "deals_pendentes": 1,
    }


def test_endpoint_unblock_404_para_lead_inexistente():
    with patch("app.leads.service.get_lead", return_value=None):
        r = client.post("/api/leads/lead-fantasma/unblock")
    assert r.status_code == 404


@pytest.mark.parametrize("bloqueado", [True, False])
def test_endpoint_blocked_reflete_o_criterio_canonico(bloqueado):
    with patch("app.leads.service.is_lead_blacklisted", return_value=bloqueado):
        r = client.get(f"/api/leads/{LEAD}/blocked")
    assert r.status_code == 200
    assert r.json() == {"blocked": bloqueado}
