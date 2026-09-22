from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.backfill_valeria_score import extract_score_evidence, run_backfill


def test_extract_score_evidence_keeps_ambiguous_volume_unknown():
    """A vague amount must never become a concrete volume criterion."""
    response = MagicMock(text='{"updates": {"monthly_volume_kg": null}, "evidence": {}}')
    with patch("scripts.backfill_valeria_score.generate", new=AsyncMock(return_value=response)):
        result = extract_score_evidence([{"role": "user", "content": "depende, talvez bastante"}])
    assert result["updates"] == {}


def test_extract_score_evidence_rejects_model_quote_absent_from_user_history():
    response = MagicMock(text='{"updates": {"supplier_reason": "replace"}, "evidence": {"supplier_reason": {"text": "quero trocar"}}}')
    with patch("scripts.backfill_valeria_score.generate", new=AsyncMock(return_value=response)):
        result = extract_score_evidence([{"role": "user", "content": "só estou pesquisando", "wamid": "wamid-2"}])
    assert result == {"updates": {}, "evidence": {}}


def test_extract_score_evidence_rejects_quote_that_normalizes_to_empty():
    response = MagicMock(text='{"updates": {"supplier_reason": "replace"}, "evidence": {"supplier_reason": {"text": "👀\\u200b"}}}')
    with patch("scripts.backfill_valeria_score.generate", new=AsyncMock(return_value=response)):
        result = extract_score_evidence([{"role": "user", "content": "quero trocar fornecedor"}])
    assert result == {"updates": {}, "evidence": {}}


def test_run_backfill_processes_all_pages_and_skips_dry_run_writes():
    """Returning after page one would miss recent eligible leads."""
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.gte.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.or_.return_value = query
    first_page = [{"id": f"lead-{index}"} for index in range(100)]
    query.execute.side_effect = [MagicMock(data=[{"lead_id": f"lead-{index}", "last_interaction_at": "2026-09-22T10:00:00Z"} for index in range(100)]), MagicMock(data=[{"lead_id": "lead-101", "last_interaction_at": "2026-09-21T10:00:00Z"}])]
    db = MagicMock()
    db.table.return_value = query
    with patch("scripts.backfill_valeria_score.get_supabase", return_value=db), \
         patch("scripts.backfill_valeria_score.get_history", return_value=[{"role": "user", "content": "quero trocar"}]), \
         patch("scripts.backfill_valeria_score.extract_score_evidence", return_value={"updates": {"supplier_reason": "replace"}, "evidence": {}}), \
         patch("scripts.backfill_valeria_score.save_score_evidence") as save_score:
        result = run_backfill(days=60, dry_run=True)
    assert result == {"scanned": 101, "updated": 0, "errors": 0, "dry_run": True, "next_cursor": "2026-09-21T10:00:00Z|lead-101"}
    save_score.assert_not_called()
    assert db.table.call_args.args == ("valeria_score_recent_leads",)


def test_run_backfill_writes_with_backfill_source_when_not_dry_run():
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.gte.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.side_effect = [MagicMock(data=[{"lead_id": "lead-1", "last_interaction_at": "2026-09-22T10:00:00Z"}])]
    db = MagicMock()
    db.table.return_value = query
    with patch("scripts.backfill_valeria_score.get_supabase", return_value=db), \
         patch("scripts.backfill_valeria_score.get_history", return_value=[{"role": "user", "content": "quero trocar"}]), \
         patch("scripts.backfill_valeria_score.extract_score_evidence", return_value={"updates": {"supplier_reason": "replace"}, "evidence": {}}), \
         patch("scripts.backfill_valeria_score.save_score_evidence") as save_score:
        result = run_backfill(days=60, dry_run=False)
    assert result["updated"] == 1
    assert save_score.call_args.kwargs["source"] == "backfill"


def test_run_backfill_returns_keyset_cursor_for_stable_resume():
    query = MagicMock()
    query.select.return_value = query
    query.gte.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value = MagicMock(data=[{"lead_id": "lead-1", "last_interaction_at": "2026-09-22T10:00:00Z"}])
    db = MagicMock()
    db.table.return_value = query
    with patch("scripts.backfill_valeria_score.get_supabase", return_value=db), \
         patch("scripts.backfill_valeria_score.get_history", return_value=[]):
        result = run_backfill(limit=1)
    assert result["next_cursor"] == "2026-09-22T10:00:00Z|lead-1"


def test_run_backfill_persists_checkpoint_before_interruption(tmp_path):
    checkpoint = tmp_path / "score.cursor"
    query = MagicMock()
    query.select.return_value = query
    query.gte.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value = MagicMock(data=[
        {"lead_id": "lead-1", "last_interaction_at": "2026-09-22T10:00:00Z"},
        {"lead_id": "lead-2", "last_interaction_at": "2026-09-21T10:00:00Z"},
    ])
    db = MagicMock()
    db.table.return_value = query
    with patch("scripts.backfill_valeria_score.get_supabase", return_value=db), \
         patch("scripts.backfill_valeria_score.get_history", side_effect=[[], KeyboardInterrupt]):
        with pytest.raises(KeyboardInterrupt):
            run_backfill(dry_run=False, checkpoint=checkpoint)
    assert checkpoint.read_text() == "2026-09-22T10:00:00Z|lead-1"


def test_dry_run_does_not_advance_write_checkpoint(tmp_path):
    checkpoint = tmp_path / "score.cursor"
    query = MagicMock()
    for method in ("select", "gte", "order", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value = MagicMock(data=[{"lead_id": "lead-1", "last_interaction_at": "2026-09-22T10:00:00Z"}])
    db = MagicMock()
    db.table.return_value = query
    with patch("scripts.backfill_valeria_score.get_supabase", return_value=db), \
         patch("scripts.backfill_valeria_score.get_history", return_value=[]):
        run_backfill(dry_run=True, checkpoint=checkpoint)
        assert not checkpoint.exists()
        run_backfill(dry_run=False, checkpoint=checkpoint)
    assert checkpoint.read_text() == "2026-09-22T10:00:00Z|lead-1"
    assert query.execute.call_count == 2


def test_backfill_advances_past_page_of_failures():
    query = MagicMock()
    for method in ("select", "gte", "order", "limit", "or_"):
        getattr(query, method).return_value = query
    query.execute.side_effect = [
        MagicMock(data=[{"lead_id": f"lead-{i}", "last_interaction_at": "2026-09-22T10:00:00Z"} for i in range(100)]),
        MagicMock(data=[]),
    ]
    db = MagicMock()
    db.table.return_value = query
    with patch("scripts.backfill_valeria_score.get_supabase", return_value=db), \
         patch("scripts.backfill_valeria_score.get_history", side_effect=RuntimeError("failed")):
        result = run_backfill()
    assert result["scanned"] == result["errors"] == 100
    assert query.execute.call_count == 2


def test_failed_lead_is_retried_on_next_write_run(tmp_path):
    checkpoint = tmp_path / "score.cursor"
    query = MagicMock()
    for method in ("select", "gte", "order", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value = MagicMock(data=[{"lead_id": "lead-1", "last_interaction_at": "2026-09-22T10:00:00Z"}])
    db = MagicMock()
    db.table.return_value = query
    with patch("scripts.backfill_valeria_score.get_supabase", return_value=db), \
         patch("scripts.backfill_valeria_score.get_history", side_effect=[RuntimeError("temporary"), []]):
        failed = run_backfill(dry_run=False, checkpoint=checkpoint)
        assert failed["errors"] == 1
        assert not checkpoint.exists()
        retried = run_backfill(dry_run=False, checkpoint=checkpoint)
    assert retried["scanned"] == 1
    assert checkpoint.exists()
    assert query.execute.call_count == 2
