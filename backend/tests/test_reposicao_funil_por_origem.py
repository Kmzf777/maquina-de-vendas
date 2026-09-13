# backend/tests/test_reposicao_funil_por_origem.py
"""Card de reposição nasce no funil ERRADO (ou não nasce) — dois defeitos, um sintoma comum.

Contexto (10/09/2026): dois defeitos ao mesmo tempo.

DEFEITO 1 — o funil não existe mais. `reposicao.py` fixava uma constante de NOME
("João - Reposição") e `create_deal(pipeline_name=...)` resolvia o pipeline por
`.eq("name", ...)`. O funil foi renomeado para "João - Reposição Atacado" em
10/09/2026 e `create_deal`, não achando o nome, caiu CALADO no fallback "primeiro
pipeline por order_index" — o card de reposição passou a nascer em funil aleatório,
sem erro visível (o log existente só registra sucesso, e "sucesso" aqui mente sobre o
destino). É a MESMA classe de incidente que já bateu uma vez em 09/09/2026
(ver `test_recuperacao_migration_2026_09_09.py::TestPipelineDeReposicao` — outro nome
errado, mesmo mecanismo). O nome mudou de novo e quebrou de novo: a prova de que nome
não pode ser o contrato.

DEFEITO 2 — mesmo com o nome certo, nome não bastaria: agora existem DOIS funis de
reposição (Atacado e Private Label), e o destino depende do FUNIL DE ORIGEM do card
que fechou, não de uma constante única. Uma venda fechada no funil Private Label que
caísse em "Reposição Atacado" seria tão errada quanto cair no funil frio — os dois
públicos não podem se misturar no board do vendedor.

O que estes testes travam:
  - o mapa origem→destino é por UUID (não editável pela tela), nunca por nome — o
    nome já provou duas vezes que muda em silêncio;
  - origem desconhecida NÃO cria o card (fail-closed: card no funil errado é pior que
    nenhum card — foi o que gerou os 19 deals extraviados do incidente de 09/09/2026);
  - a etapa de destino é resolvida por KEY ('novo'), nunca por rótulo — rótulo é
    editável na tela, e 'novo' é o marco zero do relógio de 45 dias
    (`deals.entered_stage_at`, mantido por trigger, vira a data da venda);
  - `dedupe_open` é escopado ao funil de reposição de DESTINO — sem esse escopo,
    `create_deal` reaproveitaria qualquer deal aberto do lead (ex.: o card de handoff
    da ValerIA, em outro funil) e o card de reposição nunca chegaria a existir.
"""
import re
from pathlib import Path

import app.leads.reposicao as rep

# Confirmados por SELECT em 10/09/2026 (ver descrição da Task 6).
ATACADO_ORIGEM = "9706a14a-3d9a-413b-bceb-26838fc2cc45"          # João - Atacado
ATACADO_REPOSICAO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"       # João - Reposição Atacado
PRIVATE_LABEL_ORIGEM = "24fb6ce8-6b7b-4612-970d-8debb8c041b7"    # João - Private Label
PRIVATE_LABEL_REPOSICAO = "9c027143-72f6-42d6-861f-a494ba5bbb4f"  # João - Reposição Private Label
DESCONHECIDO_ORIGEM = "00000000-0000-0000-0000-000000000000"


class _CreateDealSpy:
    """Substitui create_deal para capturar exatamente os kwargs recebidos."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, lead_id, title, category=None, *, pipeline_name=None,
                 pipeline_id=None, stage_label=None, stage_key=None,
                 dedupe_open=False, dedupe_pipeline_id=None):
        self.calls.append(dict(
            lead_id=lead_id, title=title, category=category,
            pipeline_name=pipeline_name, pipeline_id=pipeline_id,
            stage_label=stage_label, stage_key=stage_key,
            dedupe_open=dedupe_open, dedupe_pipeline_id=dedupe_pipeline_id,
        ))
        return {"id": "deal-novo"}


# ── Mapa origem→destino: função pura ────────────────────────────────────────
class TestReposicaoPipelineParaOrigem:
    """reposicao_pipeline_para: mapa por UUID, fail-closed para origem desconhecida."""

    def test_atacado_mapeia_para_reposicao_atacado(self):
        assert rep.reposicao_pipeline_para(ATACADO_ORIGEM) == ATACADO_REPOSICAO

    def test_private_label_mapeia_para_reposicao_private_label(self):
        assert rep.reposicao_pipeline_para(PRIVATE_LABEL_ORIGEM) == PRIVATE_LABEL_REPOSICAO

    def test_origem_desconhecida_devolve_none(self):
        # Fail-closed: um funil novo/desconhecido não pode virar reposição em
        # qualquer lugar por acidente.
        assert rep.reposicao_pipeline_para(DESCONHECIDO_ORIGEM) is None

    def test_origem_none_devolve_none(self):
        assert rep.reposicao_pipeline_para(None) is None


# ── ensure_reposicao_deal → create_deal com o destino certo ────────────────
class TestEnsureReposicaoDealChamaCreateDealComDestinoCorreto:
    """ensure_reposicao_deal resolve o destino pela ORIGEM do deal_id que fechou."""

    def test_atacado_para_reposicao_atacado(self, monkeypatch):
        spy = _CreateDealSpy()
        monkeypatch.setattr(rep, "create_deal", spy)
        monkeypatch.setattr(rep, "_pipeline_de_origem", lambda deal_id: ATACADO_ORIGEM)

        rep.ensure_reposicao_deal("lead-1", deal_id="deal-atacado")

        assert len(spy.calls) == 1
        call = spy.calls[0]
        assert call["lead_id"] == "lead-1"
        assert call["pipeline_id"] == ATACADO_REPOSICAO
        assert call["stage_key"] == "novo"
        assert call["dedupe_open"] is True
        assert call["dedupe_pipeline_id"] == ATACADO_REPOSICAO
        # o nome NUNCA é usado para resolver o pipeline de reposição
        assert call["pipeline_name"] is None

    def test_private_label_para_reposicao_private_label(self, monkeypatch):
        spy = _CreateDealSpy()
        monkeypatch.setattr(rep, "create_deal", spy)
        monkeypatch.setattr(rep, "_pipeline_de_origem", lambda deal_id: PRIVATE_LABEL_ORIGEM)

        rep.ensure_reposicao_deal("lead-2", deal_id="deal-pl")

        assert len(spy.calls) == 1
        call = spy.calls[0]
        assert call["pipeline_id"] == PRIVATE_LABEL_REPOSICAO
        assert call["stage_key"] == "novo"
        assert call["dedupe_pipeline_id"] == PRIVATE_LABEL_REPOSICAO


# ── Fail-closed: origem desconhecida não cria nada ──────────────────────────
class TestFailClosedParaOrigemDesconhecida:
    """Criar no funil errado é pior que não criar — nunca inventar um fallback.

    É exatamente o oposto do comportamento antigo: create_deal, sem achar o nome,
    caía no fallback silencioso "primeiro pipeline por order_index". Aqui não há
    fallback nenhum — origem desconhecida é motivo de NÃO criar.
    """

    def test_origem_desconhecida_nao_cria_card(self, monkeypatch):
        spy = _CreateDealSpy()
        monkeypatch.setattr(rep, "create_deal", spy)
        monkeypatch.setattr(rep, "_pipeline_de_origem", lambda deal_id: DESCONHECIDO_ORIGEM)

        rep.ensure_reposicao_deal("lead-3", deal_id="deal-x")

        assert spy.calls == []

    def test_sem_deal_id_nao_cria_card(self, monkeypatch):
        # Sem deal_id não há como saber a origem — fail-closed, não "primeiro pipeline".
        spy = _CreateDealSpy()
        monkeypatch.setattr(rep, "create_deal", spy)

        rep.ensure_reposicao_deal("lead-4")

        assert spy.calls == []

    def test_falha_ao_resolver_origem_e_fail_soft(self, monkeypatch):
        def boom(deal_id):
            raise RuntimeError("db down")
        monkeypatch.setattr(rep, "_pipeline_de_origem", boom)

        # Não deve levantar — não pode derrubar o fluxo de venda/Kanban.
        rep.ensure_reposicao_deal("lead-5", deal_id="deal-y")


# ── _pipeline_de_origem: leitura fail-soft de deals.pipeline_id ────────────
class _FakeQ:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self._rows
        return r


class _FakeSB:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _FakeQ(self._rows)


class TestPipelineDeOrigemLeituraDoDeal:
    def test_le_pipeline_id_do_deal(self, monkeypatch):
        sb = _FakeSB([{"pipeline_id": ATACADO_ORIGEM}])
        monkeypatch.setattr(rep, "get_supabase", lambda: sb)
        assert rep._pipeline_de_origem("deal-1") == ATACADO_ORIGEM

    def test_deal_id_none_devolve_none_sem_consultar(self, monkeypatch):
        def boom():
            raise AssertionError("não deveria consultar o banco sem deal_id")
        monkeypatch.setattr(rep, "get_supabase", boom)
        assert rep._pipeline_de_origem(None) is None

    def test_deal_inexistente_devolve_none(self, monkeypatch):
        sb = _FakeSB([])
        monkeypatch.setattr(rep, "get_supabase", lambda: sb)
        assert rep._pipeline_de_origem("deal-fantasma") is None

    def test_erro_de_consulta_e_fail_soft(self, monkeypatch):
        class _Boom:
            def table(self, name):
                raise RuntimeError("supabase down")
        monkeypatch.setattr(rep, "get_supabase", lambda: _Boom())
        assert rep._pipeline_de_origem("deal-1") is None  # não levanta


# ── O nome literal não pode voltar ───────────────────────────────────────────
class TestNomeLiteralNaoVoltaMais:
    """O nome já mudou duas vezes (09/09 e 10/09/2026) e quebrou tudo em silêncio
    nas duas. Não pode ser o contrato: nem como constante, nem como argumento de
    create_deal, nem como valor cru no módulo.
    """

    def _fonte(self) -> str:
        return Path(rep.__file__).read_text(encoding="utf-8")

    def test_constante_antiga_nao_existe_mais(self):
        assert not hasattr(rep, "REPOSICAO_PIPELINE_NAME")

    def test_nome_da_constante_antiga_sumiu_do_modulo(self):
        assert "REPOSICAO_PIPELINE_NAME" not in self._fonte()

    def test_modulo_nao_resolve_pipeline_por_nome(self):
        # create_deal(pipeline_name=...) é exatamente o caminho que caiu calado no
        # fallback por order_index quando o nome mudou. reposicao.py não pode mais
        # depender dele — o destino tem que chegar em create_deal como pipeline_id.
        assert "pipeline_name=" not in self._fonte()

    def test_nome_literal_antigo_sem_sufixo_nao_aparece(self):
        # Regex e não substring: "João - Reposição Atacado" / "...Private Label" são
        # os nomes ATUAIS e podem aparecer em comentário explicando o mapa. O que não
        # pode voltar é o nome ANTIGO exato (sem sufixo) como valor/string.
        fonte = self._fonte()
        assert not re.search(r'"João - Reposição"', fonte)
        assert not re.search(r"'João - Reposição'", fonte)

    def test_mapa_e_por_uuid_hardcoded(self):
        # Os quatro UUIDs do mapa (confirmados por SELECT em 10/09/2026) têm que
        # estar no módulo — é o contrato que substitui o nome.
        fonte = self._fonte()
        for uuid in (ATACADO_ORIGEM, ATACADO_REPOSICAO, PRIVATE_LABEL_ORIGEM, PRIVATE_LABEL_REPOSICAO):
            assert uuid in fonte, f"UUID {uuid} ausente do módulo"
