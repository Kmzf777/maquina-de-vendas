"""Check 5 (handoff_sla_breach): reação do lead não é pergunta pendente (QA 10/07).

Caso real (Nayara, run DSP 10-07-26 10-57): o João respondeu por áudio às 15:07 e a
Nayara reagiu com 👍 às 15:08. A reação bumpa `last_customer_message_at`, o watchdog
viu "última mensagem = do lead, sem resposta" e disparou `handoff_sla_breach` às
16:28 — falso: um 👍 depois da resposta do vendedor é encerramento social, não
mensagem aguardando retorno.

Fix: antes de contar a violação, o check consulta a ÚLTIMA mensagem do lead na
conversa; `message_type='reaction'` → não é violação. Fail-open: erro na leitura de
messages mantém a violação (ruído é melhor que a cegueira que escondeu o caso
Juliana).
"""
from datetime import timedelta

from app.watchdog.service import check_handoff_sla

from tests.test_watchdog_checks_2026_07_02 import FakeSupabase
from tests.test_watchdog_handoff_sla_2026_07_03 import (
    _fake_db,
    _local,
    _seed_conversation_check5,
)


def _seed_user_message(fake, conversation_id, created_at, message_type=None, msg_id=None):
    fake.tables["messages"].append({
        "id": msg_id or f"msg-{len(fake.tables['messages'])}",
        "conversation_id": conversation_id,
        "role": "user",
        "content": "x",
        "message_type": message_type,
        "created_at": created_at.isoformat(),
    })


def test_reaction_tail_is_not_a_violation(monkeypatch):
    """Última msg do lead é uma REAÇÃO (👍 pós-resposta do vendedor) → 0 violações."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 10, 14, 0)
    _seed_conversation_check5(
        fake, "conv-nayara",
        last_customer_message_at=now - timedelta(minutes=80),
        last_seller_response_at=now - timedelta(minutes=81),
        name="Nayara",
    )
    _seed_user_message(fake, "conv-nayara", now - timedelta(minutes=80), message_type="reaction")

    assert check_handoff_sla(now) == 0
    assert fake.tables["system_alerts"] == []


def test_text_tail_still_violates(monkeypatch):
    """Não-regressão (caso Juliana): última msg do lead é TEXTO → violação + alerta."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 10, 14, 0)
    _seed_conversation_check5(
        fake, "conv-juliana",
        last_customer_message_at=now - timedelta(minutes=30),
        last_seller_response_at=now - timedelta(hours=2),
        name="Juliana",
    )
    _seed_user_message(fake, "conv-juliana", now - timedelta(minutes=30), message_type=None)

    assert check_handoff_sla(now) == 1
    alerts = fake.tables["system_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["metadata"]["conversation_ids"] == ["conv-juliana"]


def test_reaction_followed_by_text_still_violates(monkeypatch):
    """Lead reagiu E depois mandou texto → a última é texto → violação normal."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 10, 14, 0)
    _seed_conversation_check5(
        fake, "conv-mista",
        last_customer_message_at=now - timedelta(minutes=30),
        last_seller_response_at=now - timedelta(hours=2),
        name="Mista",
    )
    _seed_user_message(fake, "conv-mista", now - timedelta(minutes=50), message_type="reaction", msg_id="m1")
    _seed_user_message(fake, "conv-mista", now - timedelta(minutes=30), message_type=None, msg_id="m2")

    assert check_handoff_sla(now) == 1


def test_messages_read_failure_fails_open_and_alerts(monkeypatch):
    """Erro ao ler messages → mantém a violação (contrato do caso Juliana:
    o silêncio é pior que o ruído)."""

    class _MessagesBoom:
        def __getattr__(self, _name):
            return self

        def __call__(self, *args, **kwargs):
            return self

        def execute(self):
            raise RuntimeError("messages indisponível (falha simulada)")

    fake = FakeSupabase()
    real_table = fake.table

    def _table(name):
        if name == "messages":
            return _MessagesBoom()
        return real_table(name)

    fake.table = _table
    monkeypatch.setattr("app.watchdog.service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.alerts.service.get_supabase", lambda: fake)

    now = _local(2026, 7, 10, 14, 0)
    _seed_conversation_check5(
        fake, "conv-boom",
        last_customer_message_at=now - timedelta(minutes=30),
        last_seller_response_at=None,
        name="Boom",
    )

    assert check_handoff_sla(now) == 1
    alerts = fake.tables["system_alerts"]
    assert len(alerts) == 1
