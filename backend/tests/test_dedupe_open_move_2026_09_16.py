# backend/tests/test_dedupe_open_move_2026_09_16.py
"""`dedupe_open` reaproveitava o card IGNORANDO a etapa pedida — e esvaziava a etapa.

Defeito medido em produção (16/09/2026). `create_deal(dedupe_open=True)` fazia:

    existing = get_open_deal(lead_id, pipeline_id=dedupe_pipeline_id)
    if existing:
        return existing          # ← devolve o card ONDE ELE ESTÁ

O `stage_key` que o chamador pediu era descartado em silêncio. Quem paga a conta é
`reposicao.ensure_reposicao_deal`, que chama:

    create_deal(lead_id, title="Reposição", pipeline_id=pipeline_destino,
                stage_key="novo", dedupe_open=True, dedupe_pipeline_id=pipeline_destino)

com a intenção de pôr o cliente em "Cliente Ativo" (key `novo`) do funil de reposição.
Só que 684 leads já tinham card ABERTO nesse MESMO funil, parados em "Já chamado"
(key `chamado_reposicao`), vindos de uma importação antiga. O dedupe encontrava esse
card e o devolvia intacto. Consequência permanente: a etapa "Cliente Ativo" ficou com
ZERO cards — e a esteira de Reposição, cujo gatilho é "parado 45 dias em Cliente
Ativo", nunca encontrou ninguém para disparar. Uma venda fechada não movia nada.

Contrato que estes testes travam:

  1. dedupe reaproveita a LINHA (não duplica card), mas a ETAPA pedida ainda manda:
     card aberto em outra etapa do mesmo funil é MOVIDO para a etapa do `stage_key`;
  2. o move renova `entered_stage_at`. É o relógio que a RPC
     `get_deals_stage_stagnant` lê (`entered_stage_at <= now() - stage_days`). Mover
     sem renovar entregaria o card na etapa nova já "parado há meses" e a esteira
     dispararia na primeira varredura, em cima de uma venda de ontem;
  3. card JÁ na etapa pedida → nenhum UPDATE. Renovar `entered_stage_at` à toa
     reiniciaria o relógio do gatilho sem que nada tenha acontecido — o card nunca
     completaria os 45 dias se a venda fosse reprocessada;
  4. sem `stage_key` → comportamento histórico intacto (o fluxo
     LP→inbound→encaminhar_humano usa dedupe_open sem stage_key e não quer move);
  5. `stage_key` inexistente no funil → devolve o card como está e LOGA AVISO; nunca
     levanta. `create_deal` está no caminho de venda e de Kanban.

Mock de Supabase no padrão do repositório (ver `test_create_deal_routing.py`).
"""
import logging
from unittest.mock import patch


# ── Fake Supabase (mesmo padrão de tests/test_create_deal_routing.py) ────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, fake):
        self.table = table
        self.fake = fake
        self.filters = {}
        self.op = "select"
        self.payload = None

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def is_(self, key, value):
        self.filters[("is", key)] = value
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return _Resp(self.fake.resolve(self))


class FakeSupabase:
    def __init__(self, resolver, inserted, updated=None):
        self._resolver = resolver
        self.inserted = inserted
        self.updated = updated if updated is not None else []

    def table(self, name):
        return _Query(name, self)

    def resolve(self, q):
        if q.op == "insert":
            self.inserted.append((q.table, q.payload))
            row = dict(q.payload)
            row["id"] = f"{q.table}-new"
            return [row]
        if q.op == "update":
            self.updated.append((q.table, q.payload, q.filters))
            row = {**q.payload, "id": q.filters.get("id")}
            return [row]
        return self._resolver(q.table, q.filters)


# Cenário real: funil de reposição com duas etapas. O card existente está na etapa
# herdada da importação ("Já chamado"); o chamador pede a etapa `novo`.
PIPE_REPOSICAO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"   # João - Reposição Atacado
STAGE_CLIENTE_ATIVO = "st-cliente-ativo"                  # key 'novo'
STAGE_JA_CHAMADO = "st-ja-chamado"                        # key 'chamado_reposicao'


def _resolver_com_card_em(stage_id, *, stage_keys=None):
    """Resolver de leitura: um deal aberto no funil de reposição, na etapa dada."""
    keys = {"novo": STAGE_CLIENTE_ATIVO, "chamado_reposicao": STAGE_JA_CHAMADO}
    if stage_keys is not None:
        keys = stage_keys

    def resolver(table, filters):
        if table == "deals" and ("is", "closed_at") in filters:
            return [{
                "id": "deal-existente",
                "title": "Reposição",
                "pipeline_id": PIPE_REPOSICAO,
                "stage_id": stage_id,
                "category": None,
            }]
        if table == "pipeline_stages":
            if filters.get("pipeline_id") == PIPE_REPOSICAO and "key" in filters:
                sid = keys.get(filters["key"])
                return [{"id": sid}] if sid else []
            return []
        return []

    return resolver


# ── 1. Card aberto em OUTRA etapa do mesmo funil → é MOVIDO ─────────────────
class TestCardEmOutraEtapaEMovidoParaAEtapaPedida:
    """Era o defeito: reaproveitar o card não pode significar ignorar o stage_key.

    Sem isto, "Cliente Ativo" fica permanentemente vazia (684 leads presos em "Já
    chamado") e a esteira de 45 dias que vigia essa etapa nunca dispara.
    """

    def _run(self):
        from app.leads.service import create_deal

        inserted, updated = [], []
        fake = FakeSupabase(_resolver_com_card_em(STAGE_JA_CHAMADO), inserted, updated)
        with patch("app.leads.service.get_supabase", return_value=fake):
            result = create_deal(
                "lead-1", "Reposição",
                pipeline_id=PIPE_REPOSICAO, stage_key="novo",
                dedupe_open=True, dedupe_pipeline_id=PIPE_REPOSICAO,
            )
        return result, inserted, updated

    def test_emite_update_com_o_stage_id_da_etapa_pedida(self):
        _, _, updated = self._run()
        assert len(updated) == 1, "o card tem que ser MOVIDO, não devolvido onde está"
        table, payload, filters = updated[0]
        assert table == "deals"
        assert filters["id"] == "deal-existente"
        assert payload["stage_id"] == STAGE_CLIENTE_ATIVO

    def test_renova_entered_stage_at_no_mesmo_update(self):
        # Relógio da RPC get_deals_stage_stagnant. Mover sem renovar entregaria o
        # card na etapa nova já "parado há meses" — a esteira dispararia na primeira
        # varredura, em cima de uma venda recém-fechada.
        _, _, updated = self._run()
        _, payload, _ = updated[0]
        assert "entered_stage_at" in payload, (
            "sem renovar entered_stage_at o card chega na etapa nova já vencido"
        )
        assert payload["entered_stage_at"], "entered_stage_at não pode ser vazio/None"

    def test_retorno_reflete_a_etapa_nova(self):
        # O chamador (ensure_reposicao_deal e quem mais reaproveitar) precisa ver o
        # card no estado pós-move, não no estado velho.
        result, _, _ = self._run()
        assert result["id"] == "deal-existente"
        assert result["stage_id"] == STAGE_CLIENTE_ATIVO

    def test_continua_sem_duplicar_card(self):
        # A razão de existir do dedupe segue valendo: move é UPDATE, nunca INSERT.
        _, inserted, _ = self._run()
        assert inserted == []


# ── 2. Card JÁ na etapa pedida → nenhum UPDATE ──────────────────────────────
class TestCardJaNaEtapaPedidaNaoEmiteUpdate:
    """Não renovar `entered_stage_at` à toa: isso reiniciaria o relógio do gatilho.

    Se toda venda reprocessada carimbasse `entered_stage_at = now()` num card que já
    está em "Cliente Ativo", o card nunca completaria os 45 dias — a esteira ficaria
    tão silenciosa quanto ficava com a etapa vazia, só que por outro motivo.
    """

    def test_sem_update_quando_ja_esta_na_etapa(self):
        from app.leads.service import create_deal

        inserted, updated = [], []
        fake = FakeSupabase(_resolver_com_card_em(STAGE_CLIENTE_ATIVO), inserted, updated)
        with patch("app.leads.service.get_supabase", return_value=fake):
            result = create_deal(
                "lead-2", "Reposição",
                pipeline_id=PIPE_REPOSICAO, stage_key="novo",
                dedupe_open=True, dedupe_pipeline_id=PIPE_REPOSICAO,
            )

        assert updated == [], "card já na etapa pedida não pode reiniciar o relógio"
        assert inserted == []
        assert result["id"] == "deal-existente"
        assert result["stage_id"] == STAGE_CLIENTE_ATIVO


# ── 3. Sem stage_key → comportamento histórico intacto ─────────────────────
class TestSemStageKeyNaoMexeNoCard:
    """O fluxo LP→inbound→encaminhar_humano usa dedupe_open SEM stage_key.

    Ele reaproveita o card de boas-vindas da LP exatamente onde o vendedor o deixou.
    Mover por conta própria ali seria um bug novo, não a correção deste.
    """

    def test_dedupe_open_sem_stage_key_devolve_o_existente_sem_update(self):
        from app.leads.service import create_deal

        inserted, updated = [], []
        fake = FakeSupabase(_resolver_com_card_em(STAGE_JA_CHAMADO), inserted, updated)
        with patch("app.leads.service.get_supabase", return_value=fake):
            result = create_deal("lead-3", "x", dedupe_open=True)

        assert updated == []
        assert inserted == []
        assert result["id"] == "deal-existente"
        assert result["stage_id"] == STAGE_JA_CHAMADO

    def test_stage_label_sozinho_nao_move(self):
        # A LP passa stage_label='Entrada' (sem key). Rótulo é editável na tela e
        # nunca foi contrato de destino no dedupe — não pode passar a ser agora.
        from app.leads.service import create_deal

        inserted, updated = [], []
        fake = FakeSupabase(_resolver_com_card_em(STAGE_JA_CHAMADO), inserted, updated)
        with patch("app.leads.service.get_supabase", return_value=fake):
            result = create_deal("lead-3b", "x", stage_label="Entrada", dedupe_open=True)

        assert updated == []
        assert result["stage_id"] == STAGE_JA_CHAMADO


# ── 4. stage_key inexistente → devolve como está + loga aviso, não levanta ──
class TestStageKeyInexistenteEFailSoft:
    """Etapa apagada/renomeada na tela não pode derrubar venda nem Kanban.

    Mas também não pode passar em silêncio: foi exatamente o silêncio do fallback
    ("resolve errado e segue") que produziu os incidentes de funil de reposição.
    """

    def test_devolve_o_existente_sem_mover(self):
        from app.leads.service import create_deal

        inserted, updated = [], []
        # O funil só conhece 'chamado_reposicao' — a key pedida não existe.
        fake = FakeSupabase(
            _resolver_com_card_em(
                STAGE_JA_CHAMADO, stage_keys={"chamado_reposicao": STAGE_JA_CHAMADO}
            ),
            inserted, updated,
        )
        with patch("app.leads.service.get_supabase", return_value=fake):
            result = create_deal(
                "lead-4", "Reposição",
                pipeline_id=PIPE_REPOSICAO, stage_key="novo",
                dedupe_open=True, dedupe_pipeline_id=PIPE_REPOSICAO,
            )

        assert updated == []
        assert inserted == []
        assert result["id"] == "deal-existente"
        assert result["stage_id"] == STAGE_JA_CHAMADO

    def test_loga_aviso(self, caplog):
        from app.leads.service import create_deal

        inserted, updated = [], []
        fake = FakeSupabase(
            _resolver_com_card_em(
                STAGE_JA_CHAMADO, stage_keys={"chamado_reposicao": STAGE_JA_CHAMADO}
            ),
            inserted, updated,
        )
        with caplog.at_level(logging.WARNING, logger="app.leads.service"):
            with patch("app.leads.service.get_supabase", return_value=fake):
                create_deal(
                    "lead-4b", "Reposição",
                    pipeline_id=PIPE_REPOSICAO, stage_key="novo",
                    dedupe_open=True, dedupe_pipeline_id=PIPE_REPOSICAO,
                )

        avisos = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert avisos, "etapa de destino inexistente tem que deixar rastro no log"
        assert any("novo" in r.getMessage() for r in avisos)

    def test_erro_na_movimentacao_nao_levanta(self):
        """Falha do UPDATE → card devolvido como está. create_deal nunca levanta aqui."""
        from app.leads.service import create_deal

        class _BoomOnUpdate(FakeSupabase):
            def resolve(self, q):
                if q.op == "update":
                    raise RuntimeError("supabase down")
                return super().resolve(q)

        inserted, updated = [], []
        fake = _BoomOnUpdate(_resolver_com_card_em(STAGE_JA_CHAMADO), inserted, updated)
        with patch("app.leads.service.get_supabase", return_value=fake):
            result = create_deal(
                "lead-5", "Reposição",
                pipeline_id=PIPE_REPOSICAO, stage_key="novo",
                dedupe_open=True, dedupe_pipeline_id=PIPE_REPOSICAO,
            )

        assert result["id"] == "deal-existente"  # devolveu o card, não explodiu
        assert inserted == []


# ── 5. Sem card existente → caminho de criação inalterado ───────────────────
class TestSemCardExistenteCriaNormalmente:
    """O caminho que não passa pelo dedupe não pode ter sido tocado."""

    def test_cria_o_card_na_etapa_pedida(self):
        from app.leads.service import create_deal

        def resolver(table, filters):
            if table == "deals":
                return []  # nenhum deal aberto
            if table == "pipeline_stages":
                if filters.get("pipeline_id") == PIPE_REPOSICAO and filters.get("key") == "novo":
                    return [{"id": STAGE_CLIENTE_ATIVO}]
                return []
            return []

        inserted, updated = [], []
        fake = FakeSupabase(resolver, inserted, updated)
        with patch("app.leads.service.get_supabase", return_value=fake):
            create_deal(
                "lead-6", "Reposição",
                pipeline_id=PIPE_REPOSICAO, stage_key="novo",
                dedupe_open=True, dedupe_pipeline_id=PIPE_REPOSICAO,
            )

        assert len(inserted) == 1
        _, payload = inserted[0]
        assert payload["pipeline_id"] == PIPE_REPOSICAO
        assert payload["stage_id"] == STAGE_CLIENTE_ATIVO
        assert updated == [], "criação não emite UPDATE"
