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
        "telefone_comercial": "",
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
