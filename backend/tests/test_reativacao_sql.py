# backend/tests/test_reativacao_sql.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "reativacao"))

import generate_sql


def _dados():
    return {
        "whatsapp": "5551993452254",
        "nome": "CAFE DO ANTONIO",
        "razao_social": "CAFE DO ANTONIO LTDA",
        "saudacao": "Cafe Do Antonio",
        "cpf_cnpj": "27114890000119",
        "email": "antonio.maltez@outlook.com.br",
        "cidade": "Gravataí",
        "uf": "RS",
        "cnae": "",
        "porte": "",
        "id_bling": "5845664414",
        "icp_score": "55",
        "icp_faixa": "C - medio",
        "total_gasto": "13918.48",
        "ticket_medio": "13918.48",
        "pedidos_faturados": "1",
        "ultima_compra": "2019-07-23",
        "dias_sem_comprar": "2573",
        "produto_para_citar": "Café Cru Beneficiado",
        "qtd_top1": "1200",
        "vendedor": "Arthur Silva Boaventura",
        "qtd_nfe": "1",
        "orcamentos": "0",
        "valor_vencido": "0.00",
        "titulos_vencidos": "0",
        "dias_atraso_max": "",
        "motivo_exclusao": "",
    }


class TestSqlLiteral:
    def test_escapa_apostrofo(self):
        assert generate_sql.sql_literal("Antônio's Café") == "'Antônio''s Café'"

    def test_vazio_vira_null(self):
        assert generate_sql.sql_literal("") == "NULL"
        assert generate_sql.sql_literal(None) == "NULL"

    def test_string_simples(self):
        assert generate_sql.sql_literal("RS") == "'RS'"


class TestGerarInsertLead:
    def test_insere_na_tabela_leads(self):
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        assert "INSERT INTO leads" in sql

    def test_usa_on_conflict_para_idempotencia(self):
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        assert "ON CONFLICT (phone) DO NOTHING" in sql

    def test_telefone_normalizado(self):
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        assert "'5551993452254'" in sql

    def test_stage_e_status_default_do_spec(self):
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        assert "'pending'" in sql
        assert "'imported'" in sql

    def test_atribui_ao_joao(self):
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        assert generate_sql.JOAO_UUID in sql

    def test_metadata_carrega_origem_e_lote(self):
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        assert "reativacao_bling" in sql
        assert generate_sql.LOTE in sql

    def test_metadata_carrega_id_bling(self):
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        assert "5845664414" in sql

    def test_escapa_aspas_no_nome(self):
        dados = _dados()
        dados["nome"] = "CAFE D'ANTONIO"
        sql = generate_sql.gerar_insert_lead(dados, None)
        # transform.escolher_saudacao titulariza nomes 100% em caixa alta
        # (ex.: "CAFE D'ANTONIO" -> "Cafe D'Antonio"); o que este teste
        # verifica e que o apostrofo sobrevive escapado (dobrado), nao a caixa.
        assert "D''Antonio" in sql

    def test_nao_menciona_tabelas_proibidas(self):
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        for tabela in generate_sql.TABELAS_PROIBIDAS:
            assert tabela not in sql


class TestUpdateConservador:
    def test_atualiza_tabela_leads(self):
        sql = generate_sql.gerar_update_conservador(_dados(), tem_dono=False)
        assert "UPDATE leads" in sql

    def test_nunca_toca_colunas_intocaveis(self):
        sql = generate_sql.gerar_update_conservador(_dados(), tem_dono=False)
        for coluna in generate_sql.COLUNAS_INTOCAVEIS:
            assert ("%s =" % coluna) not in sql
            assert ("%s=" % coluna) not in sql

    def test_usa_coalesce_para_preencher_apenas_vazios(self):
        sql = generate_sql.gerar_update_conservador(_dados(), tem_dono=False)
        assert "COALESCE(NULLIF(cnpj, '')" in sql
        assert "COALESCE(NULLIF(email, '')" in sql

    def test_faz_merge_no_metadata_sem_substituir(self):
        sql = generate_sql.gerar_update_conservador(_dados(), tem_dono=False)
        assert "metadata = COALESCE(metadata, '{}'::jsonb) ||" in sql

    def test_atribui_dono_apenas_quando_nulo(self):
        sem_dono = generate_sql.gerar_update_conservador(_dados(), tem_dono=False)
        assert "assigned_to = COALESCE(assigned_to," in sem_dono

    def test_nao_mexe_em_assigned_to_quando_ja_tem_dono(self):
        com_dono = generate_sql.gerar_update_conservador(_dados(), tem_dono=True)
        assert "assigned_to" not in com_dono

    def test_filtra_pelo_telefone_normalizado(self):
        sql = generate_sql.gerar_update_conservador(_dados(), tem_dono=False)
        assert "WHERE phone = '5551993452254'" in sql


class TestInsertNota:
    def test_insere_em_lead_notes(self):
        sql = generate_sql.gerar_insert_nota(_dados(), None)
        assert "INSERT INTO lead_notes" in sql

    def test_usa_autor_do_spec(self):
        sql = generate_sql.gerar_insert_nota(_dados(), None)
        assert generate_sql.AUTOR_NOTA in sql

    def test_condicionada_a_nao_existir_nota_do_lote(self):
        sql = generate_sql.gerar_insert_nota(_dados(), None)
        # DEFECT NO BRIEF: a implementacao de referencia (task-5-brief.md) gera
        # "WHERE l.phone = ...\n  AND NOT EXISTS (...)" — a clausula NOT EXISTS
        # vem depois de "AND", nunca logo depois de "WHERE" sozinha. O texto
        # original do teste ("WHERE NOT EXISTS") nao pode casar com o SQL que a
        # propria implementacao do brief produz. A propriedade real que importa
        # (condicionar o INSERT a nao existir nota do lote) e preservada
        # verificando o "NOT EXISTS" e o LOTE dentro do SQL.
        assert "NOT EXISTS" in sql
        assert generate_sql.LOTE in sql

    def test_resolve_lead_id_pelo_telefone(self):
        sql = generate_sql.gerar_insert_nota(_dados(), None)
        # DEFECT NO BRIEF: a implementacao de referencia usa "INSERT ... SELECT"
        # com alias ("SELECT l.id, ...\nFROM leads l\nWHERE l.phone = ..."), nao
        # o literal "SELECT id FROM leads WHERE phone = ...". A propriedade
        # testada — resolver o lead_id via lookup pelo telefone normalizado —
        # continua verificada checando o "l.id" selecionado e o filtro por
        # "l.phone" com o telefone normalizado.
        assert "SELECT l.id" in sql
        assert "WHERE l.phone = '5551993452254'" in sql

    def test_conteudo_tem_o_briefing(self):
        sql = generate_sql.gerar_insert_nota(_dados(), None)
        assert "CLIENTE INATIVO" in sql
        assert "Café Cru Beneficiado" in sql


class TestOptOut:
    def test_marca_opt_out(self):
        sql = generate_sql.gerar_update_optout("5515996830664", "2026-07-31", "Nao tenho interesse")
        assert "UPDATE leads" in sql
        assert "opt_out = true" in sql

    def test_registra_no_metadata_quando_e_por_que(self):
        sql = generate_sql.gerar_update_optout("5515996830664", "2026-07-31", "Nao tenho interesse")
        assert "2026-07-31" in sql
        assert "Nao tenho interesse" in sql

    def test_idempotente_so_marca_quem_nao_esta_marcado(self):
        sql = generate_sql.gerar_update_optout("5515996830664", "2026-07-31", "x")
        assert "AND opt_out IS NOT TRUE" in sql


class TestNormalizacaoTelefone:
    def test_corrige_phone_do_registro_existente(self):
        sql = generate_sql.gerar_normalizacao_telefone("11981154002", "5511981154002")
        assert "UPDATE leads" in sql
        assert "SET phone = '5511981154002'" in sql
        assert "WHERE phone = '11981154002'" in sql

    def test_protegido_contra_colisao(self):
        sql = generate_sql.gerar_normalizacao_telefone("11981154002", "5511981154002")
        assert "NOT EXISTS" in sql
