"""Guardrail determinístico anti-handoff-verbal — auditoria 2026-06-30.

Contexto forense:
  Valéria às vezes ANUNCIA a transferência para o João em plain text SEM chamar
  encaminhar_humano, deixando o lead parado:
    - "deixa eu te conectar com o João Bras, nosso supervisor, pra ele te detalhar tudo"
    - "vou deixar o contato dele aqui embaixo, é só tocar e chamar"
  Em ambos os casos, tool_calls estava VAZIO — a ferramenta nunca disparou.

Mudanças validadas aqui:
  1. _looks_like_handoff_announcement() retorna True para as frases de CTA reais de vítima.
  2. _looks_like_handoff_announcement() retorna False para menções informacionais de João Bras.
  3. run_agent() detecta o CTA no texto final e força execute_tool("encaminhar_humano"),
     retornando None (handoff sentinel) em vez do texto cru.
  4. Regressão: texto informacional não dispara o guard.
  5. Se execute_tool levantar exceção dentro do guard, run_agent retorna o texto original
     (fail-soft, sem crash do turno).
  6. Prompt base contém proibição explícita de handoff verbal sem tool.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(content: str | None, tool_calls=None) -> MagicMock:
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls  # None → falsy → tool loop exits
    msg.model_dump.return_value = {
        "role": "assistant", "content": content, "tool_calls": None
    }
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


def _conversation(stage: str = "secretaria") -> dict:
    return {
        "id": "conv-guard-001",
        "stage": stage,
        "leads": {
            "id": "lead-guard-001",
            "name": "Teste",
            "phone": "5511900000099",
            "ai_enabled": True,
        },
    }


def _history_one_user_msg() -> list:
    return [
        {
            "role": "user",
            "content": "quero saber mais",
            "stage": "secretaria",
            "created_at": "2026-06-30T10:00:00Z",
            "wamid": "wamid-guard-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


# ---------------------------------------------------------------------------
# Secao 1: testes puros de _looks_like_handoff_announcement
# ---------------------------------------------------------------------------

class TestLooksLikeHandoffAnnouncement:
    """Testes puros — sem mocks, sem I/O, só a funcao."""

    def _fn(self, text: str) -> bool:
        from app.agent.orchestrator import _looks_like_handoff_announcement
        return _looks_like_handoff_announcement(text)

    # --- Vítimas reais (devem retornar True) ---

    def test_vitima_1_conectar_joao_bras(self):
        """Frase real: lead 5547984004911 (vítima 1)."""
        text = "deixa eu te conectar com o João Bras, nosso supervisor, pra ele te detalhar tudo e a gente dar o proximo passo"
        assert self._fn(text) is True

    def test_vitima_2_contato_dele_aqui(self):
        """Frase real: lead com 'vou deixar o contato dele aqui embaixo' (vítima 2)."""
        text = "vou deixar o contato dele aqui embaixo, é só tocar e chamar"
        assert self._fn(text) is True

    # --- Variantes de CTA (devem retornar True) ---

    def test_vou_te_conectar(self):
        assert self._fn("vou te conectar com o supervisor") is True

    def test_deixa_eu_te_conectar(self):
        assert self._fn("deixa eu te conectar com o Joao") is True

    def test_te_conectar_com_o_joao(self):
        assert self._fn("ce pode te conectar com o joao agora") is True

    def test_vou_deixar_o_contato(self):
        assert self._fn("vou deixar o contato do João aqui") is True

    def test_deixando_o_contato(self):
        assert self._fn("estou deixando o contato dele aqui pra você") is True

    def test_te_passar_o_contato(self):
        assert self._fn("posso te passar o contato do João?") is True

    def test_contato_dele_aqui(self):
        assert self._fn("tô deixando o contato dele aqui embaixo") is True

    def test_contato_do_joao_aqui(self):
        assert self._fn("o contato do João aqui embaixo, é só clicar") is True

    def test_vou_transferir(self):
        assert self._fn("vou transferir você para o supervisor") is True

    def test_vou_te_transferir(self):
        assert self._fn("vou te transferir pro atendimento do João") is True

    def test_vou_te_passar_pro_joao(self):
        assert self._fn("vou te passar pro João agora") is True

    def test_vou_te_passar_para_o_joao(self):
        assert self._fn("vou te passar para o João Bras") is True

    # --- Acento-insensitivo ---

    def test_case_insensitive_maiuscula(self):
        assert self._fn("VOu Te ConEctar com o supervisor") is True

    def test_accent_insensitive_joao_sem_acento(self):
        assert self._fn("vou te passar pro Joao diretamente") is True

    def test_accent_insensitive_conectar_com_acento(self):
        """Conectar grafado normalmente já é insensível."""
        assert self._fn("vou te conectar com o supervisor") is True

    # --- Menções informacionais (devem retornar False) ---

    def test_informacional_quem_prepara(self):
        """'quem prepara isso é o Joao Bras' — menção, não CTA de transferência."""
        assert self._fn("quem prepara isso é o Joao Bras") is False

    def test_informacional_vou_deixar_salvo(self):
        """'vou deixar salvo pro Joao dar uma olhada' — NÃO é 'vou deixar o contato'."""
        assert self._fn("vou deixar salvo pro Joao dar uma olhada") is False

    def test_informacional_boas_maos(self):
        assert self._fn("você já tá em boas mãos com o time") is False

    def test_informacional_qualquer_coisa(self):
        assert self._fn("qualquer coisa é só chamar") is False

    def test_informacional_nome_no_contexto(self):
        assert self._fn("quem cuida da amostra é o Joao Bras, nosso supervisor de vendas") is False

    def test_texto_vazio(self):
        assert self._fn("") is False

    def test_none_equivalente(self):
        assert self._fn(None) is False

    def test_resposta_normal_venda(self):
        assert self._fn("o café Clássico tem notas achocolatadas e é um dos nossos mais pedidos") is False


# ---------------------------------------------------------------------------
# Secao 2: run_agent dispara guard quando texto é CTA e nenhum tool rodou
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_cta_texto_sem_tool_dispara_guard():
    """Guard força encaminhar_humano quando text é CTA de transferência e tool_calls=None."""
    from app.agent.orchestrator import run_agent

    cta_text = "vou te conectar com o João Bras, nosso supervisor, pra ele te detalhar tudo"

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-guard-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="handoff executado") as mock_exec, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(
            return_value=_make_response(content=cta_text, tool_calls=None)
        )
        result = await run_agent(_conversation(), "quero saber mais")

    # run_agent deve retornar None (sentinel de handoff)
    assert result is None, f"esperado None (handoff sentinel), got {result!r}"

    # execute_tool deve ter sido chamado com "encaminhar_humano"
    assert mock_exec.called, "execute_tool deve ser chamado pelo guard"
    called_with = mock_exec.call_args.args[0]
    assert called_with == "encaminhar_humano", (
        f"execute_tool deve ser chamado com 'encaminhar_humano', got {called_with!r}"
    )


@pytest.mark.asyncio
async def test_run_agent_cta_vitima2_contato_dele_aqui():
    """Guard funciona com a segunda frase real de vítima."""
    from app.agent.orchestrator import run_agent

    cta_text = "vou deixar o contato dele aqui embaixo, é só tocar e chamar"

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-guard-002", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="ok") as mock_exec, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(
            return_value=_make_response(content=cta_text, tool_calls=None)
        )
        result = await run_agent(_conversation(), "quero o contato do vendedor")

    assert result is None
    assert mock_exec.called
    assert mock_exec.call_args.args[0] == "encaminhar_humano"


# ---------------------------------------------------------------------------
# Secao 3: regressão — menção informacional NÃO dispara o guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_informacional_nao_dispara_guard():
    """Menção informacional de 'Joao Bras' não deve acionar o guard."""
    from app.agent.orchestrator import run_agent

    info_text = "quem cuida da amostra é o Joao Bras, nosso supervisor de vendas"

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-guard-003", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="ok") as mock_exec, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(
            return_value=_make_response(content=info_text, tool_calls=None)
        )
        result = await run_agent(_conversation(), "quem é o João?")

    # run_agent deve retornar o texto normal
    assert result == info_text, f"esperado texto original, got {result!r}"
    # execute_tool NÃO deve ser chamado com encaminhar_humano
    if mock_exec.called:
        for call in mock_exec.call_args_list:
            assert call.args[0] != "encaminhar_humano", (
                "execute_tool não deve ser chamado com encaminhar_humano para texto informacional"
            )


@pytest.mark.asyncio
async def test_run_agent_vou_deixar_salvo_nao_dispara_guard():
    """'vou deixar salvo pro Joao dar uma olhada' NÃO é CTA de transferência."""
    from app.agent.orchestrator import run_agent

    safe_text = "recebi aqui sua arte\n\nvou deixar salvo pro Joao dar uma olhada quando vocês avançarem no pedido"

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-guard-004", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock, return_value="ok") as mock_exec, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(
            return_value=_make_response(content=safe_text, tool_calls=None)
        )
        result = await run_agent(_conversation(), "[imagem]")

    assert result == safe_text, f"esperado texto original, got {result!r}"
    if mock_exec.called:
        for call in mock_exec.call_args_list:
            assert call.args[0] != "encaminhar_humano"


# ---------------------------------------------------------------------------
# Secao 4: fail-soft — se execute_tool levantar, retorna texto original (sem crash)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_agent_guard_execute_tool_raises_retorna_texto_original():
    """Se execute_tool falhar dentro do guard, run_agent retorna o texto sem crashar."""
    from app.agent.orchestrator import run_agent

    cta_text = "vou te conectar com o supervisor agora"

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-guard-005", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               side_effect=RuntimeError("simulando falha de rede")) as mock_exec, \
         patch("app.agent.orchestrator._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(
            return_value=_make_response(content=cta_text, tool_calls=None)
        )
        result = await run_agent(_conversation(), "quero falar com alguém")

    # Com execute_tool falhando, run_agent deve retornar o texto original (fail-soft)
    assert result == cta_text, (
        f"com execute_tool falhando, run_agent deve retornar texto original, got {result!r}"
    )
    # execute_tool foi chamado (guard tentou)
    assert mock_exec.called


# ---------------------------------------------------------------------------
# Secao 5: prompt base contém proibição de handoff verbal sem tool
# ---------------------------------------------------------------------------

def test_prompt_base_contem_proibicao_handoff_verbal():
    """Prompt base deve conter proibição explícita de anunciar handoff sem chamar a tool."""
    from datetime import datetime
    from app.agent.prompts.base import build_base_prompt
    prompt = build_base_prompt(None, None, datetime(2026, 6, 30, 10, 0))
    low = prompt.lower()
    # Deve mencionar a proibição de anunciar o handoff como texto
    assert "handoff verbal" in low or ("anunciar" in low and "handoff" in low) or \
           ("vou te conectar" in low and "proibido" in low) or \
           "16b" in prompt, (
        "Prompt base não contém proibição de handoff verbal sem tool-call"
    )
