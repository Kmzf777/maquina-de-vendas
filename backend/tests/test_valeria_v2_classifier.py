"""ValerIA de botões v2: o classificador de texto livre (spec §7).

Ele lê o texto do lead e devolve UMA etiqueta. Nenhuma palavra do modelo chega ao
cliente: a etiqueta só escolhe uma mensagem fixa. O que estes testes travam:
  1. nunca levanta — timeout, exceção, teto estourado, JSON quebrado, classe ou id
     inventado viram RUIDO;
  2. a saída é validada contra os ids da tela atual e as FAQs do ramo;
  3. o gasto entra em `token_usage` com `call_type` próprio;
  4. o prompt carrega a tela, as FAQs, a última mensagem e o texto do lead.

A API do Gemini NUNCA é chamada: `app.button_flow.valeria_classifier.generate` é
sempre mockado.
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.button_flow import valeria_classifier as vc
from tests.gemini_fakes import fake_text

BOTOES = [("cafeteria", "Cafeteria"), ("loja", "Loja ou empório"), ("outro", "Outro tipo")]
FAQS = {"preco": "pede preço/valor/tabela", "frete": "pergunta sobre frete", "minimo": "pedido mínimo"}


@pytest.fixture(autouse=True)
def _sem_supabase(monkeypatch):
    """Corta budget guard e token_usage (os dois entram por import tardio)."""
    monkeypatch.setattr("app.agent.budget_guard.is_exceeded", lambda: False)
    registradas: list[dict] = []
    monkeypatch.setattr(
        "app.agent.token_tracker.track_token_usage",
        lambda **kwargs: registradas.append(kwargs),
    )
    return registradas


def _patch_generate(*resultados):
    return patch(
        "app.button_flow.valeria_classifier.generate",
        new=AsyncMock(side_effect=list(resultados)),
    )


async def _cls(resposta, texto="x", **kw):
    """Classifica `texto` com o modelo devolvendo `resposta` (str/None ou exceção)."""
    if not isinstance(resposta, BaseException):
        resposta = fake_text(resposta)
    args = dict(no_id="QA1", ramo="atacado", botoes=BOTOES, faqs=FAQS,
                ultima_mensagem="que tipo de negócio você tem?")
    args.update(kw)
    with _patch_generate(resposta) as m_gen:
        resultado = await vc.classificar(texto, **args)
    return resultado, m_gen


@pytest.mark.parametrize("bruto,esperado", [
    ('{"classe":"BOTAO","botao_id":"cafeteria"}', vc.Classificacao("BOTAO", "cafeteria", None)),
    ('{"classe":"FAQ","faq_id":"frete"}', vc.Classificacao("FAQ", None, "frete")),
    ('{"classe":"PERGUNTA"}', vc.Classificacao("PERGUNTA")),
    ('{"classe":"VENDEDOR"}', vc.Classificacao("VENDEDOR")),
    ('{"classe":"SAIR"}', vc.Classificacao("SAIR")),
    ('{"classe":"RUIDO"}', vc.Classificacao("RUIDO")),
])
async def test_classes_validas(bruto, esperado):
    resultado, m_gen = await _cls(bruto, texto="tenho uma cafeteria")
    assert resultado == esperado
    assert m_gen.await_count == 1


async def test_ids_que_nao_sao_da_classe_sao_descartados():
    """`faq_id` numa resposta BOTAO (ou `botao_id` numa PERGUNTA) não vaza pro motor."""
    r, _ = await _cls('{"classe":"BOTAO","botao_id":"loja","faq_id":"frete"}')
    assert r == vc.Classificacao("BOTAO", "loja", None)
    r, _ = await _cls('{"classe":"PERGUNTA","botao_id":"loja","faq_id":"frete"}')
    assert r == vc.Classificacao("PERGUNTA")


async def test_json_com_cerca_markdown_ainda_e_aproveitado():
    r, _ = await _cls('```json\n{"classe": "faq", "faq_id": "minimo"}\n```')
    assert r == vc.Classificacao("FAQ", None, "minimo")


@pytest.mark.parametrize("bruto", [
    '{"classe":"BOTAO","botao_id":"inventado"}',   # id fora da tela
    '{"classe":"BOTAO"}',                           # BOTAO sem id
    '{"classe":"FAQ","faq_id":"pagamento"}',        # faq fora do ramo
    '{"classe":"FAQ"}',                             # FAQ sem id
    '{"classe":"XPTO"}',
    '{"classe":["BOTAO"]}',
    '["BOTAO"]',
    'não é json',
    'BOTAO',                                        # palavra solta não basta
    '',
    None,
])
async def test_saida_invalida_vira_ruido(bruto):
    r, _ = await _cls(bruto)
    assert r == vc.Classificacao("RUIDO")


async def test_timeout_vira_ruido():
    r, _ = await _cls(asyncio.TimeoutError())
    assert r == vc.Classificacao("RUIDO")


async def test_timeout_real_do_wait_for(monkeypatch):
    monkeypatch.setenv("VALERIA_CLASSIFIER_TIMEOUT_S", "0.01")

    async def _pendurado(*_a, **_k):
        await asyncio.sleep(5)

    with patch("app.button_flow.valeria_classifier.generate", new=_pendurado):
        r = await vc.classificar("oi, tudo bem?", no_id="QA1", ramo="atacado", botoes=BOTOES,
                                 faqs=FAQS, ultima_mensagem="")
    assert r == vc.Classificacao("RUIDO")


async def test_excecao_vira_ruido():
    r, _ = await _cls(RuntimeError("503 UNAVAILABLE"))
    assert r == vc.Classificacao("RUIDO")


async def test_argumentos_estranhos_nao_levantam():
    """Nem entrada malformada do chamador derruba o turno."""
    with _patch_generate(fake_text('{"classe":"RUIDO"}')):
        r = await vc.classificar("oi", no_id=None, ramo=None, botoes=None, faqs=None,
                                 ultima_mensagem=None)
    assert r == vc.Classificacao("RUIDO")


async def test_texto_vazio_e_ruido_sem_chamar_modelo():
    for texto in ("", "   ", "👍", None):
        r, m_gen = await _cls('{"classe":"VENDEDOR"}', texto=texto)
        assert r == vc.Classificacao("RUIDO")
        assert m_gen.await_count == 0


async def test_budget_estourado_vira_ruido_sem_chamar_modelo(monkeypatch):
    monkeypatch.setattr("app.agent.budget_guard.is_exceeded", lambda: True)
    r, m_gen = await _cls('{"classe":"VENDEDOR"}', texto="quero falar com alguém")
    assert r == vc.Classificacao("RUIDO")
    assert m_gen.await_count == 0


async def test_budget_guard_quebrado_nao_bloqueia(monkeypatch):
    def _explode():
        raise RuntimeError("supabase fora")

    monkeypatch.setattr("app.agent.budget_guard.is_exceeded", _explode)
    r, _ = await _cls('{"classe":"VENDEDOR"}', texto="quero falar com alguém")
    assert r == vc.Classificacao("VENDEDOR")


async def test_contabiliza_token_usage_com_call_type_proprio(_sem_supabase):
    await _cls('{"classe":"FAQ","faq_id":"frete"}', texto="tem frete grátis?", lead_id="lead-9")
    assert len(_sem_supabase) == 1
    linha = _sem_supabase[0]
    assert linha["call_type"] == "valeria_botoes_classify"
    assert linha["model"] == vc.modelo()
    assert linha["lead_id"] == "lead-9"
    assert linha["prompt_tokens"] > 0


async def test_contabilidade_quebrada_nao_derruba(monkeypatch):
    def _explode(**_k):
        raise RuntimeError("PGRST204")

    monkeypatch.setattr("app.agent.token_tracker.track_token_usage", _explode)
    r, _ = await _cls('{"classe":"SAIR"}', texto="não quero mais")
    assert r == vc.Classificacao("SAIR")


async def test_chamada_e_estreita_e_deterministica():
    _, m_gen = await _cls('{"classe":"RUIDO"}', texto="bom dia")
    args, kwargs = m_gen.await_args
    assert args[0] == vc.modelo()
    assert kwargs["json_mode"] is True
    assert kwargs["thinking_off"] is True
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_output_tokens"] <= 64
    assert "tools" not in kwargs
    enviado = kwargs["contents"][0].parts[0].text
    assert "bom dia" in enviado
    assert "cafeteria: Cafeteria" in enviado


def test_prompt_cita_botoes_faqs_e_ultima_mensagem():
    p = vc.montar_prompt("tem frete grátis?", no_id="QA1", ramo="atacado", botoes=BOTOES, faqs=FAQS,
                         ultima_mensagem="que tipo de negócio você tem?")
    for trecho in ("cafeteria: Cafeteria", "frete: pergunta sobre frete", "que tipo de negócio",
                   "tem frete grátis?"):
        assert trecho in p
    # Papel, as 6 classes e o formato de saída.
    assert "NAO responda ao lead" in p
    for classe in vc.CLASSES:
        assert classe in p
    assert '"classe"' in p and '"botao_id"' in p and '"faq_id"' in p
    # Tela e ramo atuais.
    assert "QA1" in p and "atacado" in p


def test_prompt_exemplos_so_com_ids_que_existem():
    """Exemplo de BOTAO/FAQ só entra quando o id está na tela/ramo — senão ensinaria id inventado."""
    p = vc.montar_prompt("x", no_id="QA1", ramo="atacado", botoes=BOTOES, faqs=FAQS,
                         ultima_mensagem="")
    assert '"tenho uma cafeteria"' in p
    assert '"tem frete gratis?"' in p
    assert '"qual o valor do quilo?"' in p
    assert "mais100" not in p
    for ex in ('"bom dia"', '"quero falar com alguem"', '"nao quero mais"',
               '"voces fazem cafe com acai?"'):
        assert ex in p

    volume = [("ate30", "Até 30 kg"), ("ate100", "30 a 100 kg"), ("mais100", "Mais de 100 kg")]
    p2 = vc.montar_prompt("x", no_id="QA2", ramo="atacado", botoes=volume, faqs={}, ultima_mensagem="")
    assert '"uns 200 kgs"' in p2 and "mais100" in p2
    assert '"tenho uma cafeteria"' not in p2
    assert '"tem frete gratis?"' not in p2


def test_prompt_trunca_entrada_longa():
    p = vc.montar_prompt("x" * 5000, no_id="QA1", ramo="atacado", botoes=BOTOES, faqs=FAQS,
                         ultima_mensagem="h" * 5000)
    assert p.count("x") < 700
    assert p.count("h") < 400


def test_prompt_sem_persona_nem_catalogo():
    p = vc.montar_prompt("oi", no_id="QA1", ramo="atacado", botoes=BOTOES, faqs=FAQS,
                         ultima_mensagem="")
    assert "ValerIA" not in p
    assert "R$" not in p
    assert len(p) < 2500


def test_modelo_e_timeout_vem_do_env(monkeypatch):
    monkeypatch.delenv("VALERIA_CLASSIFIER_MODEL", raising=False)
    monkeypatch.delenv("VALERIA_CLASSIFIER_TIMEOUT_S", raising=False)
    assert vc.modelo() == "gemini-2.5-flash-lite"
    assert vc.timeout_segundos() == 12.0
    monkeypatch.setenv("VALERIA_CLASSIFIER_MODEL", "m-x")
    monkeypatch.setenv("VALERIA_CLASSIFIER_TIMEOUT_S", "3")
    assert vc.modelo() == "m-x" and vc.timeout_segundos() == 3.0
    monkeypatch.setenv("VALERIA_CLASSIFIER_TIMEOUT_S", "nao-e-numero")
    assert vc.timeout_segundos() == 12.0
    monkeypatch.setenv("VALERIA_CLASSIFIER_TIMEOUT_S", "0")
    assert vc.timeout_segundos() == 12.0


def test_classes_do_contrato():
    assert vc.CLASSES == ("BOTAO", "FAQ", "PERGUNTA", "VENDEDOR", "SAIR", "RUIDO")
    c = vc.Classificacao("RUIDO")
    assert c.botao_id is None and c.faq_id is None


def test_recuperacao_ainda_expoe_os_helpers_antigos():
    """O refactor para `_llm_comum` não pode quebrar quem importa/patcha pelo nome antigo."""
    from app.button_flow import classifier
    assert callable(classifier._budget_estourado)
    assert callable(classifier._contabilizar)
    assert callable(classifier.generate)


# ── SAIR: a única etiqueta irreversível (T_OPTOUT) ──────────────────────────
# Reaproveita a rede da Recuperação (`classifier.pediu_para_parar` e
# `classifier._proteger_saida`): pedido explícito de parada não depende do modelo, e
# cortesia ("obrigado", "já compro com o João") nunca vira opt-out por palpite do LLM.
@pytest.mark.parametrize("texto", [
    "obrigado, já compro com o João",
    "Obrigado! acabamos de receber reposição",
])
async def test_sair_do_modelo_com_cortesia_vira_ruido(texto):
    r, m_gen = await _cls('{"classe":"SAIR"}', texto=texto)
    assert r == vc.Classificacao("RUIDO")
    assert m_gen.await_count == 1


@pytest.mark.parametrize("texto", ["me tira da lista", "para de me mandar isso"])
async def test_pedido_explicito_de_parada_e_sair_sem_modelo_mesmo_com_provedor_fora(texto):
    r, m_gen = await _cls(RuntimeError("503 UNAVAILABLE"), texto=texto)
    assert r == vc.Classificacao("SAIR")
    assert m_gen.await_count == 0


async def test_pedido_explicito_de_parada_e_sair_com_budget_estourado(monkeypatch):
    monkeypatch.setattr("app.agent.budget_guard.is_exceeded", lambda: True)
    r, m_gen = await _cls('{"classe":"RUIDO"}', texto="me tira da lista")
    assert r == vc.Classificacao("SAIR")
    assert m_gen.await_count == 0


async def test_sair_normal_continua_sair():
    r, _ = await _cls('{"classe":"SAIR"}', texto="não quero mais receber")
    assert r == vc.Classificacao("SAIR")
    # Sem pedido determinístico: a decisão é do modelo e a rede não a inverte.
    r, m_gen = await _cls('{"classe":"SAIR"}', texto="não quero mais")
    assert r == vc.Classificacao("SAIR")
    assert m_gen.await_count == 1


async def test_cortesia_nao_inverte_pedido_explicito():
    r, m_gen = await _cls('{"classe":"RUIDO"}', texto="Obrigado, mas pode parar de enviar essas mensagens")
    assert r == vc.Classificacao("SAIR")
    assert m_gen.await_count == 0
