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

    def test_marca_criado_por_lote(self):
        # Fix round 1, Finding 1 (CRITICAL): marcador explicito de que ESTE
        # lote criou o lead. "NOT EXISTS (messages)" sozinho e uma proxy
        # falsa — leads pre-existentes sem mensagens tambem bateriam nela e
        # seriam apagados no rollback. So gerar_insert_lead escreve esse
        # marcador; gerar_update_conservador nunca deve escreve-lo.
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        assert '"criado_por_lote": "%s"' % generate_sql.LOTE in sql


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

    def test_nao_marca_criado_por_lote(self):
        # Fix round 1, Finding 1 (CRITICAL): e a outra metade do par que
        # protege os leads pre-existentes no rollback — o UPDATE conservador
        # jamais pode escrever "criado_por_lote", senao o DELETE do rollback
        # (que agora chaveia nesse marcador) passaria a atingi-los tambem.
        sql = generate_sql.gerar_update_conservador(_dados(), tem_dono=False)
        assert "criado_por_lote" not in sql


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

    def test_registra_lote_no_metadata(self):
        # Fix round 1, Finding 2 (Important): sem o lote no metadata do
        # opt-out, o rollback nao tem como restringir o "desfazer opt-out" a
        # este lote — um rollback futuro reabriria contato com quem pediu
        # para nao ser contactado em OUTRO lote.
        sql = generate_sql.gerar_update_optout("5515996830664", "2026-07-31", "x")
        assert '"lote": "%s"' % generate_sql.LOTE in sql


class TestNormalizacaoTelefone:
    def test_corrige_phone_do_registro_existente(self):
        sql = generate_sql.gerar_normalizacao_telefone("11981154002", "5511981154002")
        assert "UPDATE leads" in sql
        assert "SET phone = '5511981154002'" in sql
        assert "WHERE phone = '11981154002'" in sql

    def test_protegido_contra_colisao(self):
        sql = generate_sql.gerar_normalizacao_telefone("11981154002", "5511981154002")
        assert "NOT EXISTS" in sql


def _entradas():
    novos = [(_dados(), None, False)]
    existentes = [(_dados(), "Carina", True)]
    optouts = [("5515996830664", "2026-07-31", "Nao tenho interesse")]
    normalizacoes = [("11981154002", "5511981154002")]
    return novos, existentes, optouts, normalizacoes


class TestMontarArquivo:
    def test_abre_e_fecha_transacao(self):
        sql = generate_sql.montar_arquivo(*_entradas())
        assert sql.count("BEGIN;") == 1
        assert sql.count("COMMIT;") == 1
        assert sql.index("BEGIN;") < sql.index("COMMIT;")

    def test_para_no_primeiro_erro(self):
        sql = generate_sql.montar_arquivo(*_entradas())
        assert "ON_ERROR_STOP" in sql

    def test_nunca_menciona_tabelas_de_disparo(self):
        sql = generate_sql.montar_arquivo(*_entradas())
        for tabela in generate_sql.TABELAS_PROIBIDAS:
            assert tabela not in sql

    def test_nunca_altera_colunas_intocaveis(self):
        sql = generate_sql.montar_arquivo(*_entradas())
        for coluna in generate_sql.COLUNAS_INTOCAVEIS:
            assert ("SET %s" % coluna) not in sql
            assert ("%s = " % coluna) not in sql.replace("'pending'", "").replace("'imported'", "")

    def test_inclui_contagens_de_verificacao(self):
        sql = generate_sql.montar_arquivo(*_entradas())
        assert "SELECT count(*)" in sql

    def test_ordem_normalizacao_antes_dos_inserts(self):
        # normalizar o phone do Atma antes, senao o INSERT cria duplicata logica
        sql = generate_sql.montar_arquivo(*_entradas())
        assert sql.index("SET phone =") < sql.index("INSERT INTO leads")

    def test_verificacao_aborta_em_contagem_errada(self):
        # Fix round 1, Finding 3 (Important): um SELECT count(*) que so faz
        # \echo nao impede o COMMIT quando a contagem esta errada (psql -f
        # roda tudo de uma vez). Cada uma das 3 checagens tem que ser capaz
        # de abortar a transacao via RAISE EXCEPTION.
        sql = generate_sql.montar_arquivo(*_entradas())
        assert sql.count("RAISE EXCEPTION") == 3

    def test_contagem_esperada_deriva_do_tamanho_das_entradas(self):
        # Fix round 1, Finding 3: os numeros esperados nao podem ser
        # literais fixos (276/276/51) — tem que vir de len(novos) +
        # len(existentes) e len(optouts), senao o check pode divergir da
        # realidade do lote que de fato foi passado para montar_arquivo.
        novos, existentes, optouts, normalizacoes = _entradas()
        sql = generate_sql.montar_arquivo(novos, existentes, optouts, normalizacoes)
        esperado_leads_e_notas = len(novos) + len(existentes)
        esperado_optouts = len(optouts)
        assert sql.count("IF n <> %d THEN" % esperado_leads_e_notas) == 2
        assert ("IF n <> %d THEN" % esperado_optouts) in sql


class TestMontarRollback:
    def test_remove_notas_do_lote(self):
        sql = generate_sql.montar_rollback()
        assert "DELETE FROM lead_notes" in sql
        assert generate_sql.LOTE in sql

    def test_remove_leads_do_lote(self):
        sql = generate_sql.montar_rollback()
        assert "DELETE FROM leads" in sql

    def test_desmarca_optouts_aplicados_por_este_lote(self):
        sql = generate_sql.montar_rollback()
        assert "opt_out = false" in sql

    def test_em_transacao(self):
        sql = generate_sql.montar_rollback()
        assert "BEGIN;" in sql and "COMMIT;" in sql

    def test_delete_chaveado_no_marcador_criado_por_lote(self):
        # Fix round 1, Finding 1 (CRITICAL): "NOT EXISTS (messages)" sozinho
        # e uma proxy falsa para "este lote criou o lead" — confirmado em
        # produção que 3 dos 40 leads pre-existentes (incl. "Bia",
        # secretaria/active) nao tem mensagens e seriam apagados por engano.
        # O DELETE agora tem que chavear no marcador explicito
        # "criado_por_lote", com o NOT EXISTS(messages) como uma segunda
        # rede de seguranca independente, nao como sinal primario.
        sql = generate_sql.montar_rollback()
        trecho_delete = sql[sql.index("DELETE FROM leads"):]
        assert ("metadata->>'criado_por_lote' = '%s'" % generate_sql.LOTE) in trecho_delete
        assert "NOT EXISTS" in trecho_delete

    def test_optout_rollback_escopado_por_lote(self):
        # Fix round 1, Finding 2 (Important): sem o filtro por lote, um
        # rollback futuro desfaria opt-outs de OUTRO lote — reabrindo
        # contato com quem pediu para nao ser contactado.
        sql = generate_sql.montar_rollback()
        trecho_optout = sql[sql.index("SET opt_out = false"):sql.index("DELETE FROM leads")]
        assert ("metadata->>'lote' = '%s'" % generate_sql.LOTE) in trecho_optout
