"""Explosão do follow-up do João no fim de semana de 03–04/10/2026.

Medido em produção em 05/10/2026: 1.019.281 jobs `pending` para 467 leads, criados
entre sáb 00:00 e dom 23:59 (BRT) num ritmo constante de ~21 mil por hora. Na segunda às
09:00, 24 leads receberam o MESMO template duas vezes, no mesmo segundo.

Três defeitos se somaram, e cada seção deste arquivo prende um deles:

1. A TRAVA DE MATRÍCULA ERA CEGA ACIMA DE 1.000 LINHAS. `_jobs_joao_dos_leads` lia os
   jobs dos candidatos numa consulta só, e o PostgREST desta VPS corta TODA resposta em
   1.000 linhas (`PGRST_DB_MAX_ROWS=1000`) sem erro. O card cujo job aberto caía depois
   do corte parecia livre e era matriculado de novo — e cada rematrícula empurrava mais
   cards para além do corte. Às 00:05 de sábado (481 matrículas legítimas depois) a
   primeira rematrícula aconteceu; daí em diante só houve rematrículas.

2. O ORÇAMENTO DO DIA CONTAVA O DIA ERRADO. A matrícula descontava os jobs com
   `fire_at` HOJE; mas o toque 1 de uma matrícula feita no sábado é clampado para
   segunda 09:00. No sábado e no domingo o "comprometido para hoje" era sempre zero, e
   o saldo voltava cheio (50) a cada tick de 30 segundos. O mesmo valia para qualquer dia
   útil depois das 16h.

3. NADA NO ENVIO IMPEDIA O MESMO TEMPLATE DE SAIR DUAS VEZES PARA O MESMO LEAD NO MESMO
   DIA. O teto de envio segurou o volume (50), mas gastou metade dele em duplicatas.

E um defeito vizinho, achado na mesma auditoria: o botão "Parar mensagens" não era
reconhecido quando o lead mandava outra mensagem logo em seguida ("Parar mensagens" +
"Bom dia"). O buffer junta as mensagens com "\\n" antes de entregar, e a comparação era
da string inteira. 4 leads pediram para sair e continuaram matriculados.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.follow_up import cadence_joao as C
from app.follow_up import service as S

from tests.test_agendador_joao_2026_09_18 import (
    JOAO_CHANNEL,
    _ligada,
    _linha_rpc,
)


# O PostgREST da VPS: `PGRST_DB_MAX_ROWS=1000` em /srv/supabase/stack.yml.
TETO_POSTGREST = 1000

# Sábado 03/10/2026, 00:00 em São Paulo — o instante em que a explosão começou.
SABADO_MEIA_NOITE = datetime(2026, 10, 3, 3, 0, tzinfo=timezone.utc)
# A janela em que o toque 1 de uma matrícula de sábado realmente sai.
SEGUNDA_09H = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class _TabelaComTeto:
    """Uma tabela que filtra de verdade E corta a resposta como o PostgREST corta.

    Sem `.range()` a resposta vem truncada em 1.000 linhas, sem erro — exatamente o que
    a produção faz. Com `.range(a, b)` devolve a fatia pedida (ainda limitada a 1.000).
    """

    def __init__(self, banco, nome):
        self.banco, self.nome = banco, nome
        self.op, self.payload = "select", None
        self.filtros: list = []
        self.fatia: tuple[int, int] | None = None

    def select(self, *a, **k):
        self.op = "select"
        return self

    def eq(self, col, val):
        self.filtros.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.filtros.append(("in", col, list(vals)))
        return self

    def gte(self, col, val):
        self.filtros.append(("gte", col, val))
        return self

    def lt(self, col, val):
        self.filtros.append(("lt", col, val))
        return self

    def order(self, *a, **k):
        return self

    def range(self, inicio, fim):
        self.fatia = (inicio, fim)
        return self

    def insert(self, rows):
        self.op, self.payload = "insert", rows
        self.banco.inserts.append((self.nome, rows))
        return self

    def _casa(self, linha):
        for op, col, val in self.filtros:
            atual = linha.get(col)
            if op == "eq" and atual != val:
                return False
            if op == "in" and atual not in val:
                return False
            if op == "gte" and not (atual and _ts(atual) >= _ts(val)):
                return False
            if op == "lt" and not (atual and _ts(atual) < _ts(val)):
                return False
        return True

    def execute(self):
        if self.op == "insert":
            return SimpleNamespace(data=self.payload)
        self.banco.selects.append((self.nome, list(self.filtros), self.fatia))
        casam = [dict(l) for l in self.banco.tabelas.get(self.nome, []) if self._casa(l)]
        if self.fatia is not None:
            inicio, fim = self.fatia
            casam = casam[inicio:fim + 1]
        return SimpleNamespace(data=casam[:TETO_POSTGREST])


class _BancoComTeto:
    def __init__(self, tabelas=None, rpc_rows=None):
        self.tabelas = tabelas or {}
        self.rpc_rows = rpc_rows or []
        self.inserts: list = []
        self.selects: list = []

    def table(self, nome):
        return _TabelaComTeto(self, nome)

    def rpc(self, nome, args):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=list(self.rpc_rows)))


def _ts(valor):
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))


def _job_aberto(lead, deal, *, job_type="joao_em_conversa", toque=1, fire_at=SEGUNDA_09H,
                status="pending", n=0):
    return {
        "id": f"job-{lead}-{toque}-{n}",
        "lead_id": lead,
        "job_type": job_type,
        "status": status,
        "sequence": toque,
        "fire_at": fire_at.isoformat(),
        "sent_at": None,
        "created_at": SABADO_MEIA_NOITE.isoformat(),
        "cancel_reason": None,
        "metadata": {"deal_id": deal, "toque": toque, "matricula_id": f"m-{lead}-{n}",
                     "template_name": f"joao_em_conversa_t{toque}"},
    }


def _rodar(banco, overrides, *, now, teto=None):
    with (
        patch("app.follow_up.service.get_supabase", return_value=banco),
        patch("app.follow_up.service.carregar_overrides_joao", return_value=overrides),
        patch("app.follow_up.service.carregar_ajustes_joao",
              return_value={"teto_diario_disparos": 50, "adiamento_estoque_dias": 30}),
        patch("app.follow_up.service.get_channel_by_provider_config",
              return_value=JOAO_CHANNEL),
        patch("app.follow_up.service.get_or_create_conversation",
              side_effect=lambda lead_id, ch: {"id": f"conv-{lead_id}"}),
        patch("app.leads.service.is_lead_blacklisted", return_value=False),
        patch("app.follow_up.service.emit_event"),
    ):
        return S.agendar_cadencias_joao(now=now, teto=teto)


def _leads_matriculados(banco):
    return {row["lead_id"] for _t, rows in banco.inserts for row in rows}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. A trava de matrícula enxerga TODOS os jobs, e não só os primeiros 1.000
# ═══════════════════════════════════════════════════════════════════════════════
def test_jobs_dos_leads_volta_inteiro_mesmo_acima_do_teto_do_postgrest():
    jobs = [_job_aberto(f"lead-{i % 300}", f"deal-{i % 300}", n=i) for i in range(2500)]
    banco = _BancoComTeto({"follow_up_jobs": jobs})

    lidos = S._jobs_joao_dos_leads(banco, [f"lead-{i}" for i in range(300)])

    assert len(lidos) == 2500, (
        "a leitura parou no corte do PostgREST — o card cujo job aberto ficou depois "
        "do corte parece livre e é matriculado de novo")


def test_jobs_dos_leads_nao_manda_milhares_de_ids_numa_url_so():
    """A janela de candidatos é 2.000 cards: 2.000 UUIDs num `in.(...)` são ~75 KB de
    URL, acima do que o Kong/PostgREST aceitam com folga. Pedimos em lotes."""
    banco = _BancoComTeto({"follow_up_jobs": []})
    S._jobs_joao_dos_leads(banco, [f"lead-{i}" for i in range(2000)])

    maior_lote = max(
        len(val) for _n, filtros, _f in banco.selects
        for op, col, val in filtros if op == "in" and col == "lead_id")
    assert maior_lote <= 200


def test_card_com_cadencia_aberta_nao_e_rematriculado_quando_os_jobs_passam_de_1000():
    """A REPRODUÇÃO do incidente, pela varredura inteira.

    1.200 cards já matriculados (um job aberto cada) estão na frente; o card-alvo também
    tem job aberto, mas a linha dele é a 1.201ª da resposta. Antes da correção a trava
    não a via, e o card-alvo era matriculado de novo a cada tick de 30 segundos.
    """
    # Toques de TERÇA: fora do dia que o orçamento conta, para que o saldo não mascare
    # a trava (é ela que este teste prova).
    terca = SEGUNDA_09H + timedelta(days=1)
    ocupados = [_job_aberto(f"lead-{i}", f"deal-{i}", fire_at=terca) for i in range(1200)]
    alvo = _job_aberto("lead-alvo", "deal-alvo", fire_at=terca)
    candidatos = [_linha_rpc(lead=f"lead-{i}", deal=f"deal-{i}") for i in range(1200)]
    candidatos.append(_linha_rpc(lead="lead-alvo", deal="deal-alvo"))
    banco = _BancoComTeto({"follow_up_jobs": ocupados + [alvo]}, rpc_rows=candidatos)

    # Segunda 10h: dentro da janela, o orçamento do dia não interfere neste teste.
    _rodar(banco, _ligada("em_conversa"), now=SEGUNDA_09H + timedelta(hours=1), teto=5000)

    assert "lead-alvo" not in _leads_matriculados(banco)
    assert banco.inserts == []


def test_leitura_que_falha_no_meio_da_paginacao_e_fail_closed():
    """Metade dos jobs é tão perigoso quanto nenhum: devolve None e a passagem pula."""

    class _Quebra(_BancoComTeto):
        chamadas = 0

        def table(self, nome):
            self.chamadas += 1
            if self.chamadas > 1:
                raise RuntimeError("statement timeout")
            return super().table(nome)

    # 10 jobs para cada um dos 150 leads: um lote só, mas DUAS páginas — e a segunda falha.
    jobs = [_job_aberto(f"lead-{i % 150}", f"deal-{i % 150}", n=i) for i in range(1500)]
    banco = _Quebra({"follow_up_jobs": jobs})
    assert S._jobs_joao_dos_leads(banco, [f"lead-{i}" for i in range(150)]) is None


def test_resposta_do_lead_cancela_TODOS_os_pendentes_mesmo_acima_de_1000():
    """`processar_resposta_joao` lia os jobs do lead sem paginar. Um lead com 2.000
    pendentes (o estado de produção em 05/10) teria só 1.000 cancelados no opt-out."""
    jobs = [_job_aberto("lead-x", "deal-x", n=i) for i in range(2000)]
    banco = _BancoComTeto({"follow_up_jobs": jobs})
    canceladas: list = []

    class _Update:
        def __init__(self, payload):
            self.payload = payload
            self.ids: list = []

        def in_(self, col, ids):
            self.ids = list(ids)
            return self

        def eq(self, *a):
            return self

        def execute(self):
            canceladas.extend(self.ids)
            return SimpleNamespace(data=[])

    original = _TabelaComTeto.__init__

    def _com_update(self, b, nome):
        original(self, b, nome)
        self.update = lambda payload: _Update(payload)

    with (
        patch.object(_TabelaComTeto, "__init__", _com_update),
        patch("app.follow_up.service.get_supabase", return_value=banco),
        patch("app.campaigns.worker.handle_optout_reply"),
        patch("app.leads.service.get_lead", return_value={"id": "lead-x"}),
    ):
        S.processar_resposta_joao("lead-x", "Parar mensagens")

    assert len(canceladas) == 2000


# ═══════════════════════════════════════════════════════════════════════════════
# 2. O orçamento da matrícula é o do dia em que o toque 1 VAI SAIR
# ═══════════════════════════════════════════════════════════════════════════════
def _janela(banco):
    """(gte, lt) de `fire_at` que a contagem do orçamento pediu."""
    for _nome, filtros, _f in banco.selects:
        limites = {op: val for op, col, val in filtros if col == "fire_at"}
        if limites:
            return _ts(limites["gte"]), _ts(limites["lt"])
    raise AssertionError("a contagem não recortou por fire_at")


def test_no_sabado_o_orcamento_conta_os_toques_de_segunda():
    banco = _BancoComTeto({"follow_up_jobs": []})
    S.disparos_comprometidos(banco, now=SABADO_MEIA_NOITE)

    inicio, fim = _janela(banco)
    assert inicio == datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)   # seg 00:00 BRT
    assert fim == datetime(2026, 10, 6, 3, 0, tzinfo=timezone.utc)


def test_depois_das_16h_o_orcamento_conta_os_toques_de_amanha():
    quarta_17h = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)
    banco = _BancoComTeto({"follow_up_jobs": []})
    S.disparos_comprometidos(banco, now=quarta_17h)

    inicio, _fim = _janela(banco)
    assert inicio == datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc)   # qui 00:00 BRT


def test_de_madrugada_e_no_horario_comercial_o_dia_continua_sendo_hoje():
    for agora in (datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc),     # qua 03h BRT
                  datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)):   # qua 11h BRT
        banco = _BancoComTeto({"follow_up_jobs": []})
        S.disparos_comprometidos(banco, now=agora)
        inicio, _fim = _janela(banco)
        assert inicio == datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc), agora


def test_fim_de_semana_nao_renova_o_orcamento_a_cada_tick():
    """A REPRODUÇÃO do defeito 2, pelo agendador.

    Sábado 00:00, teto de 50, e 50 toques já marcados para segunda 09:00 (a primeira
    passagem do fim de semana). Antes da correção o saldo lido era 50 — o "hoje" era
    sábado, e nada tinha `fire_at` no sábado — e mais 50 cards entravam a cada tick.
    """
    ja_na_fila = [_job_aberto(f"ja-{i}", f"deal-ja-{i}") for i in range(50)]
    novos = [_linha_rpc(lead=f"novo-{i}", deal=f"deal-novo-{i}") for i in range(30)]
    banco = _BancoComTeto({"follow_up_jobs": ja_na_fila}, rpc_rows=novos)

    assert _rodar(banco, _ligada("em_conversa"), now=SABADO_MEIA_NOITE) == 0
    assert banco.inserts == []


def test_matricula_do_fim_de_semana_marca_o_toque_1_no_dia_que_o_orcamento_contou():
    """O contrato entre as duas metades: o dia que o orçamento conta é o dia em que
    `_montar_jobs_da_matricula` põe o toque 1. Se divergirem, o defeito volta."""
    banco = _BancoComTeto({"follow_up_jobs": []},
                          rpc_rows=[_linha_rpc(lead="novo-1", deal="deal-novo-1")])
    _rodar(banco, _ligada("em_conversa"), now=SABADO_MEIA_NOITE)

    toque_1 = next(row for _t, rows in banco.inserts for row in rows
                   if row["metadata"].get("toque") == 1)
    inicio, fim = _janela(banco)
    assert inicio <= _ts(toque_1["fire_at"]) < fim


# ═══════════════════════════════════════════════════════════════════════════════
# 3. "Parar mensagens" junto com outra mensagem continua sendo "Parar mensagens"
# ═══════════════════════════════════════════════════════════════════════════════
def test_botao_de_saida_seguido_de_outra_mensagem_e_opt_out():
    from app.campaigns.worker import is_optout_reply

    # Os quatro casos reais de produção (30/09 e 02/10/2026).
    for texto in ("Parar mensagens\nBom dia.", "Parar mensagens\nOi",
                  "Parar mensagens\nOlá", "Parar mensagens\nBom dia"):
        assert is_optout_reply(texto), texto
    assert is_optout_reply("Bom dia\nNão tenho interesse")


def test_botao_de_saida_continua_sendo_igualdade_dentro_da_mensagem():
    """A doutrina da igualdade não muda: cada MENSAGEM tem de ser o rótulo inteiro."""
    from app.campaigns.worker import is_optout_reply

    assert not is_optout_reply("não tenho interesse em cápsulas, só em grãos")
    assert not is_optout_reply("Bom dia\nnão tenho interesse em cápsulas, só em grãos")
    assert not is_optout_reply("quero parar mensagens de cobrança")
    assert not is_optout_reply("")
    assert not is_optout_reply(None)


def test_cadencia_do_joao_classifica_o_combinado_como_opt_out():
    assert C.classificar_resposta("Parar mensagens\nBom dia") == C.RESPOSTA_OPTOUT


# ═══════════════════════════════════════════════════════════════════════════════
# 4. O mesmo template não sai duas vezes no mesmo dia para o mesmo lead
# ═══════════════════════════════════════════════════════════════════════════════
from tests import test_scheduler_joao_2026_09_18 as H   # noqa: E402

TEMPLATE = "joao_novo_atacado_t1"   # o template do `_joao_job` padrão


class _Envios:
    """`follow_up_jobs` só com `.select().eq().eq()` — o que a guarda pede."""

    def __init__(self, linhas, quebrada=False):
        self.linhas, self.quebrada, self.filtros = linhas, quebrada, {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filtros[col] = val
        return self

    def execute(self):
        if self.quebrada:
            raise RuntimeError("statement timeout")
        return SimpleNamespace(data=[
            dict(l) for l in self.linhas
            if all(l.get(c) == v for c, v in self.filtros.items())])


def _db_com_envios(linhas, quebrada=False):
    db = H._db()
    original = db.table
    db.table = lambda nome: (_Envios(linhas, quebrada) if nome == "follow_up_jobs"
                             else original(nome))
    return db


def _enviado(template=TEMPLATE, *, sent_at=H.NOW, lead="lead-1", job_type="joao_novo"):
    return {"id": f"ja-{template}-{sent_at.isoformat()}", "lead_id": lead,
            "status": "sent", "job_type": job_type, "sent_at": sent_at.isoformat(),
            "metadata": {"template_name": template}}


def test_o_mesmo_template_no_mesmo_dia_e_cancelado_como_duplicata():
    """A REPRODUÇÃO do defeito 3: a segunda cópia do par de 05/10 não sai mais."""
    calls = H._run_handler(H._joao_job(), sb=_db_com_envios([_enviado()]))

    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_called_once_with("job-joao-1", "template_repetido_no_dia")
    calls["sent"].assert_not_called()


def test_o_mesmo_template_em_outro_dia_sai_porque_em_atencao_repete_por_desenho():
    ontem = H.NOW - timedelta(days=1)
    calls = H._run_handler(H._joao_job(), sb=_db_com_envios([_enviado(sent_at=ontem)]))

    calls["meta"].send_template.assert_awaited_once()


def test_outro_template_no_mesmo_dia_e_ADIADO_para_amanha_e_nunca_cancelado():
    """Os 105 leads com toque 2 e toque 3 vencendo juntos: o segundo espera um dia.
    Cancelar faria a matrícula contar como interrompida e o card ser rematriculado."""
    with patch("app.follow_up.scheduler.adiar_job_para_amanha") as adiar, \
         patch("app.follow_up.scheduler._devolver_job_a_pending") as devolve:
        calls = H._run_handler(
            H._joao_job(), sb=_db_com_envios([_enviado("joao_novo_atacado_t2")]))

    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_not_called()
    calls["sent"].assert_not_called()
    assert adiar.call_args.args[0] == "job-joao-1"
    devolve.assert_called_once_with("job-joao-1")


def test_o_job_de_mover_de_hoje_nao_conta_como_template_recebido():
    mover = _enviado(None)
    mover["metadata"] = {"acao": "mover_etapa", "template_name": None}
    calls = H._run_handler(H._joao_job(), sb=_db_com_envios([mover]))

    calls["meta"].send_template.assert_awaited_once()


def test_o_mesmo_template_para_OUTRO_lead_nao_e_duplicata():
    calls = H._run_handler(H._joao_job(), sb=_db_com_envios([_enviado(lead="lead-2")]))

    calls["meta"].send_template.assert_awaited_once()


def test_job_da_valeria_com_o_mesmo_nome_nao_conta():
    calls = H._run_handler(
        H._joao_job(), sb=_db_com_envios([_enviado(job_type="standard")]))

    calls["meta"].send_template.assert_awaited_once()


def test_sem_conseguir_conferir_nao_envia_nem_encerra():
    calls = H._run_handler(H._joao_job(), sb=_db_com_envios([], quebrada=True))

    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_not_called()
    calls["sent"].assert_not_called()
