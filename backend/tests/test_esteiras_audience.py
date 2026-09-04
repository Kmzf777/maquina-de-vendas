"""campaigns.audience libera (ou nao) o motor sobre lead com ai_enabled=False.

O teste de REGRESSAO deste arquivo (audience ausente => comportamento de hoje) e a
rede de seguranca da mudanca inteira: campanha antiga nao pode passar a disparar
por cima de conversa conduzida por vendedor.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.automation.engine import _audience_allows, _process_one


class TestAudienceAllows:
    def test_ia_aceita_lead_com_ia_ligada(self):
        assert _audience_allows("ia", {"ai_enabled": True}) is True

    def test_ia_recusa_lead_sob_controle_humano(self):
        assert _audience_allows("ia", {"ai_enabled": False}) is False

    def test_humano_aceita_so_controle_humano(self):
        assert _audience_allows("humano", {"ai_enabled": False}) is True
        assert _audience_allows("humano", {"ai_enabled": True}) is False

    def test_ambos_aceita_os_dois(self):
        assert _audience_allows("ambos", {"ai_enabled": True}) is True
        assert _audience_allows("ambos", {"ai_enabled": False}) is True

    def test_audience_ausente_ou_lixo_cai_em_ia(self):
        assert _audience_allows(None, {"ai_enabled": True}) is True
        assert _audience_allows(None, {"ai_enabled": False}) is False
        assert _audience_allows("banana", {"ai_enabled": False}) is False

    def test_lead_sem_a_chave_conta_como_ia_ligada(self):
        # Default historico: ausencia de ai_enabled sempre significou True.
        assert _audience_allows("ia", {}) is True


@pytest.mark.asyncio
class TestProcessOneGate:
    async def _roda(self, audience, ai_enabled):
        enrollment = {
            "id": "e1",
            "lead_id": "lead1",
            "step_count": 0,
            "leads": {"id": "lead1", "phone": "5511999", "ai_enabled": ai_enabled},
            "campaigns": {"id": "c1", "status": "active", "audience": audience, "channel_id": "ch1"},
            "campaign_nodes": {"id": "n1", "type": "end", "config": {}},
        }
        with (
            patch("app.automation.engine._conversation_followup_disabled", return_value=False),
            patch("app.automation.engine._complete") as mock_complete,
            patch("app.automation.engine._log_exec"),
        ):
            from datetime import datetime, timezone
            await _process_one(enrollment, datetime.now(timezone.utc))
        return mock_complete

    async def test_regressao_campanha_sem_audience_nao_toca_lead_humano(self):
        mock_complete = await self._roda(None, False)
        mock_complete.assert_not_called()

    async def test_campanha_ia_nao_toca_lead_humano(self):
        mock_complete = await self._roda("ia", False)
        mock_complete.assert_not_called()

    async def test_campanha_humano_processa_lead_humano(self):
        mock_complete = await self._roda("humano", False)
        mock_complete.assert_called_once()

    async def test_campanha_humano_nao_toca_lead_da_ia(self):
        mock_complete = await self._roda("humano", True)
        mock_complete.assert_not_called()

    async def test_campanha_ambos_processa_os_dois(self):
        assert (await self._roda("ambos", False)).call_count == 1
        assert (await self._roda("ambos", True)).call_count == 1


class TestApplyAudience:
    def test_ia_filtra_true(self):
        from app.automation.triggers import _apply_audience
        q = MagicMock()
        _apply_audience(q, "ia")
        q.eq.assert_called_once_with("ai_enabled", True)

    def test_humano_filtra_false(self):
        from app.automation.triggers import _apply_audience
        q = MagicMock()
        _apply_audience(q, "humano")
        q.eq.assert_called_once_with("ai_enabled", False)

    def test_ambos_nao_filtra(self):
        from app.automation.triggers import _apply_audience
        q = MagicMock()
        assert _apply_audience(q, "ambos") is q
        q.eq.assert_not_called()

    def test_ausente_cai_em_ia(self):
        from app.automation.triggers import _apply_audience
        q = MagicMock()
        _apply_audience(q, None)
        q.eq.assert_called_once_with("ai_enabled", True)
