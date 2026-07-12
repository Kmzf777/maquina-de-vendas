"""Fixes N1/N2 da auditoria inbound 12/07 (docs/superpowers/reports/auditoria_inbound_2026_07_12.md).

N1 — Alucinação de envio de fotos (caso Ana Weiss, 11/07 19:59 UTC):
  "enviei aqui algumas fotos pra você ver como ficam as embalagens" SEM chamar
  enviar_fotos — zero imagens em toda a história do lead. Guarda determinística
  nova (espelho da guarda de handoff verbalizado): detecta a alegação no texto
  final e FORÇA enviar_fotos(categoria=stage). A idempotência da tool (marcador
  [enviar_fotos] no histórico + fila do turno) absorve referências legítimas a
  fotos já enviadas; o texto do turno é preservado (fotos saem depois, via fila
  diferida — a frase vira verdade).

N2 — Vocabulário da ponte (casos Bianca/Rosângela bom/Ana Weiss):
  "ta" faltava em _SOCIAL_CLOSING_TOKENS → "Tá joia" levava carimbo em vez de ❤️;
  "orcamentos" (plural) faltava em _BUSINESS_QUESTION_TOKENS → "vou esperar os
  outros orçamentos" levava carimbo em cima de sinal comercial.
"""
import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text


def _conversation(stage: str = "private_label") -> dict:
    return {
        "id": "conv-fotoguard-001",
        "stage": stage,
        "leads": {
            "id": "lead-fotoguard-001",
            "name": "Ana",
            "phone": "5511900000098",
            "ai_enabled": True,
        },
    }


def _history_one_user_msg() -> list:
    return [
        {
            "role": "user",
            "content": "Sim",
            "stage": "private_label",
            "created_at": "2026-07-12T10:00:00Z",
            "wamid": "wamid-fotoguard-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


# ---------------------------------------------------------------------------
# N1 / Secao 1: testes puros de _looks_like_photo_send_claim
# ---------------------------------------------------------------------------

class TestLooksLikePhotoSendClaim:
    """Testes puros — sem mocks, sem I/O, só a função."""

    def _fn(self, text) -> bool:
        from app.agent.orchestrator import _looks_like_photo_send_claim
        return _looks_like_photo_send_claim(text)

    # --- Vítima real e variantes de alegação (True) ---

    def test_vitima_ana_weiss(self):
        """Frase real da vítima (11/07 19:59 UTC) — zero fotos na conversa."""
        text = "enviei aqui algumas fotos pra você ver como ficam as embalagens com a marca do cliente"
        assert self._fn(text) is True

    def test_enviei_fotos_do_portfolio(self):
        assert self._fn("enviei aqui as fotos do nosso portfólio pra você dar uma olhada") is True

    def test_mandei_as_imagens(self):
        assert self._fn("mandei as imagens dos produtos pra você") is True

    def test_te_mandei_as_fotos(self):
        assert self._fn("te mandei as fotos aqui no chat") is True

    def test_acabei_de_enviar_o_catalogo(self):
        assert self._fn("acabei de enviar o catálogo com as embalagens") is True

    def test_acento_e_caixa_insensitivo(self):
        assert self._fn("Enviei aqui as FOTOS do portfólio") is True

    # --- Frases legítimas que NÃO são alegação de envio (False) ---

    def test_recebi_foto_do_lead_nao_dispara(self):
        assert self._fn("recebi sua foto aqui, vou deixar salvo pro Joao dar uma olhada") is False

    def test_fallback_de_midia_nao_dispara(self):
        assert self._fn("me manda por texto aqui que eu te ajudo na hora?") is False

    def test_oferta_futura_nao_dispara(self):
        assert self._fn("quer que eu te mostre como fica?") is False

    def test_enviei_sem_substantivo_de_midia_nao_dispara(self):
        assert self._fn("enviei sua solicitação pro time interno") is False

    def test_referencia_sem_verbo_de_envio_nao_dispara(self):
        assert self._fn("as fotos mostram bem como a embalagem fica") is False

    def test_texto_vazio(self):
        assert self._fn("") is False

    def test_none(self):
        assert self._fn(None) is False


# ---------------------------------------------------------------------------
# N1 / Secao 2: run_agent força enviar_fotos quando a alegação vem sem tool-call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_alegacao_de_fotos_sem_tool_forca_enviar_fotos():
    """Texto final alega envio de fotos sem tool-call → guard chama enviar_fotos(stage)."""
    from app.agent.orchestrator import run_agent

    claim_text = "enviei aqui algumas fotos pra você ver como ficam as embalagens com a marca do cliente"

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-fotoguard-001", "phone": "5511900000098", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="4 fotos enfileiradas") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=fake_text(claim_text))):
        result = await run_agent(_conversation("private_label"), "Sim")

    # O texto do turno é PRESERVADO (fotos saem depois via fila diferida).
    assert result == claim_text, f"esperado texto original preservado, got {result!r}"
    assert mock_exec.called, "execute_tool deve ser chamado pela guarda de fotos"
    called_names = [c.args[0] for c in mock_exec.call_args_list]
    assert "enviar_fotos" in called_names, f"esperado enviar_fotos, got {called_names!r}"
    foto_call = [c for c in mock_exec.call_args_list if c.args[0] == "enviar_fotos"][0]
    assert foto_call.args[1] == {"categoria": "private_label"}


@pytest.mark.asyncio
async def test_run_agent_texto_normal_nao_dispara_guarda_de_fotos():
    """Resposta comum de venda não aciona enviar_fotos."""
    from app.agent.orchestrator import run_agent

    normal_text = "o café Clássico tem notas achocolatadas e é um dos nossos mais pedidos"

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-fotoguard-002", "phone": "5511900000098", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="ok") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=fake_text(normal_text))):
        result = await run_agent(_conversation("private_label"), "me fala dos cafés")

    assert result == normal_text
    if mock_exec.called:
        for call in mock_exec.call_args_list:
            assert call.args[0] != "enviar_fotos"


@pytest.mark.asyncio
async def test_run_agent_guarda_de_fotos_fora_de_stage_com_catalogo_nao_dispara():
    """Em stage sem catálogo de fotos (secretaria), a guarda não força a tool."""
    from app.agent.orchestrator import run_agent

    claim_text = "enviei aqui as fotos do nosso portfólio"

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-fotoguard-003", "phone": "5511900000098", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="ok") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=fake_text(claim_text))):
        result = await run_agent(_conversation("secretaria"), "oi")

    assert result == claim_text
    if mock_exec.called:
        for call in mock_exec.call_args_list:
            assert call.args[0] != "enviar_fotos"


@pytest.mark.asyncio
async def test_run_agent_guarda_de_fotos_fail_soft():
    """Se execute_tool falhar dentro da guarda, o turno entrega o texto sem crash."""
    from app.agent.orchestrator import run_agent

    claim_text = "enviei aqui as fotos do nosso portfólio pra você dar uma olhada"

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-fotoguard-004", "phone": "5511900000098", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               side_effect=RuntimeError("simulando falha")) as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=fake_text(claim_text))):
        result = await run_agent(_conversation("atacado"), "Sim")

    assert result == claim_text, "fail-soft: texto original deve ser entregue"
    assert mock_exec.called


# ---------------------------------------------------------------------------
# N2 / Secao 3: vocabulário da ponte
# ---------------------------------------------------------------------------

class TestBridgeVocabularyN2:
    def _social(self, text) -> bool:
        from app.buffer.processor import _is_social_closing
        return _is_social_closing(text)

    def _business(self, text) -> bool:
        from app.buffer.processor import _looks_like_business_question
        return _looks_like_business_question(text)

    # --- Vítimas reais (auditoria 12/07) ---

    def test_ta_joia_e_social_closing(self):
        """Caso Bianca 11/07: 'Tá joia' levou carimbo em vez de ❤️."""
        assert self._social("Tá joia") is True

    def test_ta_joia_obrigada_multilinha_e_social_closing(self):
        """Caso Rosângela bom 12/07: 'Ta joia\\nObrigada' levou carimbo."""
        assert self._social("Ta joia\nObrigada") is True

    def test_orcamentos_plural_e_business(self):
        """Caso Ana Weiss 11/07: sinal comercial levou carimbo — deve ficar em silêncio."""
        assert self._business("Vou esperar os outros orçamentos para comparar") is True

    # --- Regressões (comportamento existente preservado) ---

    def test_obrigado_continua_social(self):
        assert self._social("Obrigado") is True

    def test_pergunta_de_valor_continua_business(self):
        assert self._business("Qual o valor da unidade") is True

    def test_ta_com_pergunta_nao_e_social(self):
        assert self._social("tá joia? me confirma o preço") is False

    def test_frase_substantiva_com_ta_nao_e_social(self):
        """'ta' entra no vocabulário, mas palavra fora do vocabulário mantém a ponte."""
        assert self._social("ta demorando muito a resposta") is False

    def test_orcamento_singular_continua_business(self):
        assert self._business("me manda um orçamento") is True
