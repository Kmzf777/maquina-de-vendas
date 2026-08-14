# backend/tests/test_reativacao_lote_completo.py
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "reativacao"))

import lote_completo


def _linha(**kw):
    base = {
        "id_bling": "1", "nome": "CAFE TESTE LTDA", "whatsapp": "5534991461669",
        "celular": "", "telefone": "", "segmento_reativacao": "ativo_0_3m",
        "vendedor": "Joao Bras", "total_gasto": "1000,00", "valor_vencido": "0,00",
        "titulos_vencidos": "0", "dias_atraso_max": "0", "cpf_cnpj": "",
        "cidade": "Uberlandia", "uf": "MG", "email": "", "endereco": "",
        "whatsapp_tipo": "celular", "ultima_compra": "2026-08-01",
        "produto_top1": "Cafe Canastra", "qtd_top1": "10", "ticket_medio": "100,00",
        "pedidos_faturados": "10", "dias_sem_comprar": "5", "qtd_nfe": "10",
        "orcamentos": "0", "razao_social": "", "nome_fantasia": "",
        "telefone_comercial": "", "fantasia": "",
    }
    base.update(kw)
    return base


class TestEtapaDe:
    def test_mapeia_cada_segmento(self):
        assert lote_completo.etapa_de(_linha(segmento_reativacao="ativo_0_3m")) == "ativo_0_3m"
        assert lote_completo.etapa_de(_linha(segmento_reativacao="inativo_36m+")) == "inativo_36m_mais"
        assert lote_completo.etapa_de(_linha(segmento_reativacao="lead_sem_compra")) == "lead_sem_compra"

    def test_segmento_desconhecido_aborta(self):
        with pytest.raises(ValueError, match="segmento desconhecido"):
            lote_completo.etapa_de(_linha(segmento_reativacao="marciano"))


class TestPerfilComercial:
    def test_vendedor_humano_e_b2b(self):
        assert lote_completo.perfil_comercial(_linha(vendedor="Arthur Silva")) == "B2B"

    def test_id_numerico_do_bling_e_b2b(self):
        assert lote_completo.perfil_comercial(_linha(vendedor="5850735359")) == "B2B"

    def test_plataformas_sao_ecommerce(self):
        assert lote_completo.perfil_comercial(_linha(vendedor="WooCommerce")) == "E-commerce"
        assert lote_completo.perfil_comercial(
            _linha(vendedor="TRAY TECNOLOGIA EM ECOMMERCE LTDA")) == "E-commerce"
        assert lote_completo.perfil_comercial(_linha(vendedor="Licitação")) == "E-commerce"

    def test_vazio_e_sem_vendedor(self):
        assert lote_completo.perfil_comercial(_linha(vendedor="")) == "Sem vendedor"


class TestSelecionarFaltantes:
    def test_exclui_quem_ja_esta_no_crm(self):
        linhas = [_linha(id_bling="1", whatsapp="5534991461669"),
                  _linha(id_bling="2", whatsapp="5511988887777")]
        resultado = lote_completo.selecionar_faltantes(linhas, {"5534991461669"})
        assert [l["id_bling"] for l in resultado.novos] == ["2"]
        assert resultado.ja_no_crm == 1

    def test_dedup_mantem_a_primeira_ocorrencia(self):
        linhas = [_linha(id_bling="1", whatsapp="5511988887777", nome="PRIMEIRO"),
                  _linha(id_bling="2", whatsapp="(11) 98888-7777", nome="SEGUNDO")]
        resultado = lote_completo.selecionar_faltantes(linhas, set())
        assert len(resultado.novos) == 1
        assert resultado.novos[0]["nome"] == "PRIMEIRO"
        assert resultado.duplicados_no_csv == 1

    def test_sem_telefone_fica_de_fora(self):
        linhas = [_linha(id_bling="1", whatsapp="", celular="", telefone="")]
        resultado = lote_completo.selecionar_faltantes(linhas, set())
        assert resultado.novos == []
        assert resultado.sem_telefone == 1

    def test_cai_para_celular_e_telefone_quando_whatsapp_vazio(self):
        linhas = [_linha(id_bling="1", whatsapp="", celular="11988887777")]
        resultado = lote_completo.selecionar_faltantes(linhas, set())
        assert resultado.novos[0]["_phone"] == "5511988887777"

    def test_telefone_truncado_cai_para_a_proxima_coluna(self):
        linhas = [_linha(id_bling="1", whatsapp="+33 6 68 60 37",
                         celular="11988887777")]
        resultado = lote_completo.selecionar_faltantes(linhas, set())
        assert resultado.novos[0]["_phone"] == "5511988887777"

    def test_crm_e_comparado_normalizado(self):
        # O CSV traz o celular antigo de 12 digitos; a coorte normaliza para 13,
        # que e a forma que o CRM guarda. Tem que casar.
        linhas = [_linha(id_bling="1", whatsapp="553491461669")]
        resultado = lote_completo.selecionar_faltantes(linhas, {"5534991461669"})
        assert resultado.novos == []
        assert resultado.ja_no_crm == 1


class TestSqlFunil:
    def test_cria_pipeline_com_uuid_fixo(self):
        sql = lote_completo.gerar_pipeline_e_etapas()
        assert lote_completo.PIPELINE_ID in sql
        assert "INSERT INTO pipelines" in sql
        assert "ON CONFLICT (id) DO NOTHING" in sql

    def test_pipeline_nasce_sem_dono(self):
        sql = lote_completo.gerar_pipeline_e_etapas()
        assert "NULL" in sql.split("INSERT INTO pipelines")[1].split(";")[0]

    def test_cria_as_oito_etapas_na_ordem(self):
        sql = lote_completo.gerar_pipeline_e_etapas()
        assert sql.count("INSERT INTO pipeline_stages") == 8
        for indice, (_key, label, _cor, uuid_) in enumerate(lote_completo.ETAPAS):
            assert uuid_ in sql
            assert label in sql
            assert ", %d, false)" % indice in sql

    def test_nenhuma_etapa_e_protegida(self):
        sql = lote_completo.gerar_pipeline_e_etapas()
        assert "true)" not in sql.split("pipeline_stages")[-1]


class TestSqlLead:
    def test_insere_com_telefone_canonico(self):
        linha = _linha(whatsapp="553491461669")   # celular antigo: ganha o 9
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert "'5534991461669'" in sql
        assert "ON CONFLICT (phone) DO NOTHING" in sql

    def test_fixo_entra_com_doze_digitos(self):
        linha = _linha(whatsapp="554342453258")   # fixo: preserva 12 digitos
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert "'554342453258'" in sql

    def test_nome_vem_limpo_de_sufixo_empresarial(self):
        linha = _linha(nome="CAFE TESTE LTDA")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert "'Cafe Teste'" in sql

    def test_nome_fantasia_vem_da_coluna_fantasia_do_bling(self):
        # A coluna do CSV do Bling e "fantasia"; "nome_fantasia" e o nome da
        # coluna no CRM. Ler pelo nome do CRM devolvia NULL em todos os leads.
        linha = _linha(nome="CAFE TESTE LTDA")
        linha["fantasia"] = "Cafe do Teste"
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert "'Cafe do Teste'" in sql

    def test_metadata_tem_as_chaves_de_rastreio(self):
        linha = _linha(id_bling="777", vendedor="Arthur Silva")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        # Testa o dicionario direto: extrair JSON de dentro do SQL por split e
        # fragil e o que quebra e o teste, nao o codigo.
        metadata = lote_completo.metadata_do_lead(linha)
        assert metadata["origem"] == lote_completo.ORIGEM
        assert metadata["lote"] == lote_completo.LOTE
        assert metadata["criado_por_lote"] == lote_completo.LOTE
        assert metadata["id_bling"] == "777"
        assert metadata["vendedor_anterior"] == "Arthur Silva"
        assert metadata["segmento"] == "ativo_0_3m"

    def test_metadata_carrega_debito_quando_existe(self):
        linha = _linha(valor_vencido="1.234,56", titulos_vencidos="3", dias_atraso_max="190")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert '"valor_vencido": 1234.56' in sql
        assert '"titulos_vencidos": 3' in sql
        assert '"dias_atraso_max": 190' in sql

    def test_metadata_omite_debito_quando_zerado(self):
        linha = _linha(valor_vencido="0,00")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert "valor_vencido" not in sql

    def test_ai_enabled_entra_como_booleano_e_nao_string(self):
        linha = _linha()
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert "'False'" not in sql
        assert "false" in sql

    def test_nao_escreve_assigned_to(self):
        linha = _linha()
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert "assigned_to" not in sql


class TestSqlNota:
    def test_usa_o_prefixo_do_lote_e_nao_o_de_agosto_10(self):
        linha = _linha()
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_nota(linha)
        assert "REATIVAÇÃO BLING 14/08/2026" in sql
        assert "10/08/2026" not in sql

    def test_nao_renderiza_icp(self):
        linha = _linha()
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        assert "ICP" not in lote_completo.gerar_insert_nota(linha)

    def test_linha_de_debito_aparece_quando_ha_vencido(self):
        linha = _linha(valor_vencido="1.234,56", titulos_vencidos="3", dias_atraso_max="190")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_nota(linha)
        assert "DÉBITO VENCIDO" in sql
        assert "190" in sql

    def test_lead_sem_compra_troca_o_bloco_de_historico(self):
        linha = _linha(total_gasto="0,00", segmento_reativacao="lead_sem_compra")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_nota(linha)
        assert "LEAD SEM COMPRA" in sql

    def test_e_idempotente_por_autor(self):
        linha = _linha()
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_nota(linha)
        assert "NOT EXISTS" in sql
        assert lote_completo.AUTOR_NOTA in sql

    def test_aspas_simples_no_conteudo_sao_escapadas(self):
        linha = _linha(nome="CAFE D'ANTONIO")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_nota(linha)
        assert "D''ANTONIO" in sql or "D'ANTONIO" not in sql.replace("''", "")


class TestSqlDeal:
    def test_deal_cai_na_etapa_do_segmento(self):
        linha = _linha(segmento_reativacao="inativo_36m+")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_deal(linha)
        assert "f6b9d2a7-0c83-4e16-8f57-2d0a1b5c6e95" in sql

    def test_titulo_segue_a_convencao_do_crm(self):
        linha = _linha(nome="CAFE TESTE LTDA")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_deal(linha)
        assert "'Cafe Teste - Reativação Bling'" in sql

    def test_valor_zero_e_stage_novo(self):
        linha = _linha()
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_deal(linha)
        assert "0, 'novo'" in sql

    def test_nao_duplica_deal_no_mesmo_funil(self):
        linha = _linha()
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_deal(linha)
        assert "NOT EXISTS" in sql
        assert lote_completo.PIPELINE_ID in sql


class TestSqlTags:
    def _coorte(self):
        linhas = [
            _linha(id_bling="1", whatsapp="5511900000001", vendedor="Arthur"),
            _linha(id_bling="2", whatsapp="5511900000002", vendedor="WooCommerce"),
            _linha(id_bling="3", whatsapp="5511900000003", vendedor=""),
            _linha(id_bling="4", whatsapp="5511900000004", vendedor="Arthur",
                   valor_vencido="500,00", titulos_vencidos="1", dias_atraso_max="30"),
        ]
        return lote_completo.selecionar_faltantes(linhas, set()).novos

    def test_cria_as_quatro_tags_novas_e_nao_a_b2b(self):
        sql = lote_completo.gerar_tags(self._coorte())
        criacoes = [s for s in sql.split(";") if "INSERT INTO tags" in s]
        assert len(criacoes) == 4
        # B2B ja existe no banco: aparece no vinculo, nunca numa criacao.
        assert all(lote_completo.TAG_B2B_ID not in c for c in criacoes)
        assert lote_completo.TAG_B2B_ID in sql

    def test_tag_do_lote_cobre_todos(self):
        sql = lote_completo.gerar_tags(self._coorte())
        bloco = [b for b in sql.split(";") if lote_completo.TAG_LOTE_ID in b and "lead_tags" in b][0]
        for fone in ("5511900000001", "5511900000002", "5511900000003", "5511900000004"):
            assert fone in bloco

    def test_b2b_so_pega_quem_tem_vendedor_humano(self):
        sql = lote_completo.gerar_tags(self._coorte())
        bloco = [b for b in sql.split(";") if lote_completo.TAG_B2B_ID in b and "lead_tags" in b][0]
        assert "5511900000001" in bloco
        assert "5511900000004" in bloco
        assert "5511900000002" not in bloco
        assert "5511900000003" not in bloco

    def test_debito_so_pega_quem_tem_valor_vencido(self):
        sql = lote_completo.gerar_tags(self._coorte())
        bloco = [b for b in sql.split(";") if lote_completo.TAG_DEBITO_ID in b and "lead_tags" in b][0]
        assert "5511900000004" in bloco
        assert "5511900000001" not in bloco

    def test_vinculo_e_idempotente(self):
        sql = lote_completo.gerar_tags(self._coorte())
        assert sql.count("NOT EXISTS") >= 4

    def test_tag_sem_ninguem_nao_gera_vinculo_vazio(self):
        coorte = [c for c in self._coorte() if c["id_bling"] == "1"]
        sql = lote_completo.gerar_tags(coorte)
        assert lote_completo.TAG_DEBITO_ID not in sql.split("INSERT INTO lead_tags")[-1]
