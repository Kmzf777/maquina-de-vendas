# backend/tests/test_sql_cards_extraviados_2026_09_16.py
"""Guarda-rails do corretivo dos 19 cards de Reposição extraviados (16/09/2026).

Contexto: `ensure_reposicao_deal` (backend/app/leads/reposicao.py) cria um card
title='Reposição' no funil de Reposição correspondente ao funil de ORIGEM da
venda do lead. Antes do fix de 10/09/2026 a resolução de pipeline caía calada
no fallback "primeiro pipeline por order_index" de `create_deal`
(leads/service.py) — os 19 cards criados entre 07/08 e 04/09/2026 pararam no
funil "Valéria - Importação Leads Frios" (18 em 'frio', 1 em 'respondeu').
Reconferido em produção em 16/09/2026: o total continua 19.

Já existe um corretivo anterior (scripts/recuperacao/corrigir_deals_reposicao.sql,
09/09/2026, travado por test_recuperacao_migration_2026_09_09.py). Ele nunca foi
aplicado e, de qualquer forma, só sabia mover para UM destino (João - Reposição
Atacado) — foi escrito antes de existir o segundo funil de reposição (Private
Label, 10/09/2026). scripts/corrige_cards_reposicao_extraviados.sql o substitui:
resolve o destino de CADA card pelo funil de origem da venda do PRÓPRIO lead,
espelhando o mapa de `reposicao_pipeline_para`, e deixa de fora (sem chutar)
qualquer card cuja origem não seja inequívoca.

A suíte não tem banco — as migrações e scripts corretivos deste repo são
aplicados à mão no Supabase (o GitHub Actions só sobe imagem, nunca roda SQL).
Aqui o único guarda-rail possível é sobre o TEXTO do arquivo, mesmo padrão de
test_esteiras_migration_sql.py e de
test_recuperacao_migration_2026_09_09.py::TestCorretivoDosDealsExtraviados
(que trava o corretivo anterior da mesmíssima forma).
"""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SQL_PATH = RAIZ / "scripts" / "corrige_cards_reposicao_extraviados.sql"

# UUIDs confirmados em backend/app/leads/reposicao.py (_ORIGEM_PARA_REPOSICAO) e
# em test_reposicao_funil_por_origem.py — não são inventados para este teste.
FUNIL_FRIO = "a9487d77-ae93-42fe-89b8-9747d5e9cdf4"              # Valéria - Importação Leads Frios (origem ERRADA)
ORIGEM_ATACADO = "9706a14a-3d9a-413b-bceb-26838fc2cc45"          # João - Atacado
DESTINO_ATACADO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"         # João - Reposição Atacado
ORIGEM_PL = "24fb6ce8-6b7b-4612-970d-8debb8c041b7"               # João - Private Label
DESTINO_PL = "9c027143-72f6-42d6-861f-a494ba5bbb4f"              # João - Reposição Private Label


def _sem_comentarios(texto: str) -> str:
    """Remove comentários `--` linha a linha.

    Importa para os testes que buscam comandos SQL executáveis (UPDATE/DELETE/
    DROP/...): o cabeçalho deste arquivo EXPLICA o desenho em português, citando
    esses mesmos termos, e um `in sql` cru leria a explicação como se fosse o
    comando.
    """
    return "\n".join(linha.split("--", 1)[0] for linha in texto.splitlines())


@pytest.fixture(scope="module")
def sql() -> str:
    assert SQL_PATH.exists(), (
        f"corretivo dos cards extraviados não encontrado em {SQL_PATH}"
    )
    return SQL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def codigo(sql) -> str:
    """O SQL sem comentários — para testes que procuram comandos, não prosa."""
    return _sem_comentarios(sql)


@pytest.fixture(scope="module")
def codigo_lower(codigo) -> str:
    return codigo.lower()


class TestArquivoExiste:
    def test_o_arquivo_existe(self):
        assert SQL_PATH.exists()


class TestAvisoDeSeguranca:
    """Mesmo contrato dos outros corretivos de produção deste repo
    (scripts/recuperacao/corrigir_deals_reposicao.sql,
    supabase/migrations/20260910_contrato_etapas_joao.sql): escreve no funil de
    trabalho do vendedor, então precisa avisar antes de qualquer SQL executável.
    """

    def test_avisa_que_nao_pode_ser_executado_sem_autorizacao(self, sql):
        cabecalho = sql[:2500]
        assert "NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO" in cabecalho
        assert "Nenhum agente de IA deve rodar" in cabecalho
        assert "PRODUÇÃO" in cabecalho

    def test_declara_quantos_cards_afeta(self, sql):
        # Medido por leitura em produção — 16/09/2026 reconfere o número de
        # 09/09/2026, não é um valor inventado de cabeça.
        assert "19 cards" in sql
        assert "19 leads distintos" in sql


class TestTransacional:
    def test_tem_begin_e_commit(self, codigo):
        assert re.search(r"\bBEGIN\s*;", codigo)
        assert re.search(r"\bCOMMIT\s*;", codigo)

    def test_begin_vem_antes_do_commit(self, codigo):
        assert codigo.index("BEGIN;") < codigo.rindex("COMMIT;")


class TestSeletorDosCardsExtraviados:
    """O WHERE que acha os 19 — tem que casar com o literal exato que o hook grava."""

    def test_filtra_pelo_titulo_exato_gravado_pelo_hook(self, sql):
        from app.leads import reposicao
        fonte = Path(reposicao.__file__).read_text(encoding="utf-8")
        assert 'title="Reposição"' in fonte, (
            "reposicao.py não grava mais esse literal — o script ficaria "
            "desalinhado do código que gerou o problema"
        )
        assert "title = 'Reposição'" in sql

    def test_restringe_ao_funil_de_origem_errado(self, sql):
        assert FUNIL_FRIO in sql, "sem o UUID do funil frio, o script arrisca mexer em card fora do incidente"

    def test_nao_mexe_em_card_ja_fechado(self, codigo):
        assert "closed_at IS NULL" in codigo

    def test_so_mexe_em_card_que_ninguem_tocou(self, codigo):
        # Mesmos critérios do corretivo anterior (corrigir_deals_reposicao.sql),
        # confirmados contra os mesmos 19 cards em 09/09/2026: um card com
        # assigned_to/category/value preenchido, ou com updated_at bem depois do
        # created_at, foi tocado por humano — não é mais "puramente automático".
        assert "assigned_to IS NULL" in codigo
        assert "category IS NULL" in codigo
        assert "coalesce(d.value, 0) = 0" in codigo.replace("COALESCE", "coalesce")


class TestMapaDeOrigemEspelhaReposicaoPy:
    """O destino não é uma constante única — depende do funil de ORIGEM da venda
    do lead, exatamente como `reposicao_pipeline_para`."""

    def test_cita_os_dois_funis_de_reposicao_de_destino(self, sql):
        assert DESTINO_ATACADO in sql
        assert DESTINO_PL in sql

    def test_cita_os_dois_funis_de_origem(self, sql):
        assert ORIGEM_ATACADO in sql
        assert ORIGEM_PL in sql

    def test_mapa_bate_com_reposicao_pipeline_para(self, sql):
        from app.leads import reposicao
        # O mapa do SQL não pode ser uma tabela paralela inventada: tem que
        # produzir exatamente os mesmos pares que a função Python resolve.
        assert reposicao.reposicao_pipeline_para(ORIGEM_ATACADO) == DESTINO_ATACADO
        assert reposicao.reposicao_pipeline_para(ORIGEM_PL) == DESTINO_PL

    def test_origem_e_lida_da_etapa_fechado_ganho(self, codigo):
        # Mesmo critério de `deal_is_won` (reposicao.py): a verdade do "fechou"
        # é stage_id -> pipeline_stages.key, nunca a coluna legada `deals.stage`.
        assert "key = 'fechado_ganho'" in codigo

    def test_nunca_chuta_quando_lead_tem_origem_ambigua_ou_desconhecida(self, codigo_lower):
        # O card só pode ganhar destino quando as vendas fechadas do lead
        # mapeiam para EXATAMENTE UM funil de reposição — nunca zero, nunca
        # mais de um. É este HAVING que implementa o "nunca chuta" do plano.
        assert "having count(distinct destino_pipeline_id) = 1" in codigo_lower


class TestEtapaResolvidaPorKeyNaoPorRotulo:
    def test_resolve_por_key_novo(self, codigo):
        assert "key = 'novo'" in codigo

    def test_nao_resolve_etapa_por_rotulo(self, codigo):
        # "Cliente Ativo" pode (e deve) aparecer no cabeçalho explicando o
        # rótulo atual — mas fora de `codigo` (sem comentários) ele não pode
        # ser o CRITÉRIO de seleção da etapa, porque rótulo é editável na tela.
        assert "label = 'Cliente Ativo'" not in codigo
        assert "label = 'Novo'" not in codigo


class TestEnteredStageAt:
    def test_update_renova_entered_stage_at(self, codigo):
        m = re.search(r"UPDATE\s+deals\b.*?;", codigo, re.IGNORECASE | re.DOTALL)
        assert m, "não encontrei o UPDATE em deals"
        assert re.search(r"entered_stage_at\s*=\s*now\(\)", m.group(0), re.IGNORECASE), (
            "sem renovar entered_stage_at, o card movido pareceria parado há "
            "meses na etapa que acabou de receber — get_deals_stage_stagnant "
            "(20260904_esteiras_vendedor.sql) o consideraria elegível na hora"
        )


class TestSemComandoDestrutivo:
    def test_nao_tem_delete(self, codigo):
        assert not re.search(r"\bDELETE\s+FROM\b", codigo, re.IGNORECASE)

    def test_nao_tem_drop_de_objeto_permanente(self, codigo):
        # "ON COMMIT DROP" é o dialeto de temp table (autolimpeza da própria
        # transação) — não é um DROP destrutivo e não deve reprovar o teste.
        sem_temp_drop = re.sub(r"ON\s+COMMIT\s+DROP", "", codigo, flags=re.IGNORECASE)
        assert not re.search(
            r"\bDROP\s+(TABLE|FUNCTION|SCHEMA|DATABASE|INDEX|TRIGGER|VIEW)\b",
            sem_temp_drop,
            re.IGNORECASE,
        )

    def test_nao_tem_truncate(self, codigo):
        assert not re.search(r"\bTRUNCATE\b", codigo, re.IGNORECASE)

    def test_todo_update_tem_where(self, codigo):
        updates = re.findall(r"UPDATE\s+\S+.*?;", codigo, re.IGNORECASE | re.DOTALL)
        assert updates, "esperava pelo menos um UPDATE"
        for stmt in updates:
            assert re.search(r"\bWHERE\b", stmt, re.IGNORECASE), stmt[:200]

    def test_o_unico_update_e_em_deals(self, codigo):
        # Nada de leads/sales/conversion_events/etc. — o incidente é só deals.
        tabelas = re.findall(r"UPDATE\s+(?!deals\b)(\w+)", codigo, re.IGNORECASE)
        assert tabelas == [], tabelas

    def test_nao_toca_a_coluna_legada_stage(self, codigo):
        # `deals.stage` está congelada (leads/service.py) — a verdade da etapa
        # é stage_id/key. Escrever nela criaria um segundo lugar de verdade.
        assert not re.search(r"(?<!_)\bstage\b\s*=", codigo)


class TestBlocoDeConferencia:
    def test_tem_select_de_conferencia_antes_do_begin(self, sql):
        i_begin = sql.index("BEGIN;")
        antes = sql[:i_begin]
        assert re.search(r"\bSELECT\b", antes, re.IGNORECASE)

    def test_conferencia_lista_lead_funil_etapa_e_destino(self, sql):
        i_begin = sql.index("BEGIN;")
        antes = sql[:i_begin].lower()
        for coluna in ("lead", "funil_atual", "etapa_atual", "destino"):
            assert coluna in antes, coluna

    def test_tem_conferencia_depois_do_commit(self, sql):
        i_commit = sql.rindex("COMMIT;")
        depois = sql[i_commit:]
        assert re.search(r"\bSELECT\b", depois, re.IGNORECASE)


class TestGuardaDeSanidade:
    """A transação inteira aborta se o alvo não bater com o esperado — não
    move card nenhum "pela metade"."""

    def test_aborta_se_alvo_vazio(self, codigo):
        assert "RAISE EXCEPTION" in codigo
        assert re.search(r"total\s*=\s*0", codigo)

    def test_aborta_se_alvo_grande_demais(self, codigo):
        assert re.search(r"total\s*>\s*50", codigo), (
            "sem teto, um WHERE que passe a casar meio banco moveria meio banco"
        )


class TestNaoEhMigration:
    def test_explica_por_que_nao_e_migration(self, sql):
        assert "MIGRATION" in sql.upper()
        assert "supabase/migrations" in sql
