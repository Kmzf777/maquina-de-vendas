# backend/tests/test_reativacao_transform.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "reativacao"))

import transform


class TestNormalizarTelefone:
    def test_celular_com_55_permanece(self):
        assert transform.normalizar_telefone("5534991461669") == "5534991461669"

    def test_celular_sem_55_recebe_prefixo(self):
        assert transform.normalizar_telefone("34991461669") == "5534991461669"

    def test_formatado_com_pontuacao(self):
        assert transform.normalizar_telefone("(34) 99146-1669") == "5534991461669"

    def test_fixo_dez_digitos_recebe_55(self):
        assert transform.normalizar_telefone("3432151234") == "553432151234"

    def test_vazio_devolve_vazio(self):
        assert transform.normalizar_telefone("") == ""
        assert transform.normalizar_telefone(None) == ""

    def test_curto_demais_devolve_vazio(self):
        assert transform.normalizar_telefone("12345") == ""

    def test_internacional_portugal_preservado(self):
        assert transform.normalizar_telefone("351960124975") == "351960124975"

    def test_internacional_emirados_preservado(self):
        assert transform.normalizar_telefone("971586080859") == "971586080859"

    def test_br_13_digitos_inalterado(self):
        assert transform.normalizar_telefone("5534991461669") == "5534991461669"


class TestEscolherSaudacao:
    def test_nome_do_crm_tem_prioridade(self):
        assert transform.escolher_saudacao("Carina", "Divina Terra - BALNEARIO CAMBORIU") == "Carina"

    def test_sem_nome_crm_usa_bling_limpo(self):
        assert transform.escolher_saudacao(None, "ARMAZEM SAO PEDRO LTDA") == "Armazem Sao Pedro"

    def test_remove_codigo_numerico_no_inicio(self):
        assert transform.escolher_saudacao("", "35.791.341 EVERTON GENTIL") == "Everton Gentil"

    def test_nome_crm_em_branco_cai_no_bling(self):
        assert transform.escolher_saudacao("   ", "Café do Antônio") == "Café do Antônio"

    def test_preserva_acento_quando_nao_esta_todo_maiusculo(self):
        assert transform.escolher_saudacao(None, "Café Canastra Empório") == "Café Canastra Empório"


class TestClassificarPerfil:
    def test_capsula(self):
        assert transform.classificar_perfil("Cápsula Compatível Nespresso - Canastra Clássico") == "cápsula"

    def test_capsula_sem_acento(self):
        assert transform.classificar_perfil("Capsula Canastra Classico") == "cápsula"

    def test_cafe_verde_industrial(self):
        assert transform.classificar_perfil("Café Cru Beneficiado") == "café verde/industrial"

    def test_granel(self):
        assert transform.classificar_perfil("Café Canastra Granel Suave Grãos 2kg") == "granel/volume"

    def test_drip(self):
        assert transform.classificar_perfil("Café Canastra Drip Coffee Clássico Display 10un") == "drip"

    def test_kit(self):
        assert transform.classificar_perfil("KIT DEGUSTAÇÃO 2") == "kit/presente"

    def test_cafe_convencional_nao_tem_perfil(self):
        assert transform.classificar_perfil("Café Canastra Canela Moído 250g") == ""
        assert transform.classificar_perfil("Café Especial Canastra Clássico Moído - Pacote com 250 gramas") == ""

    def test_vazio(self):
        assert transform.classificar_perfil("") == ""
        assert transform.classificar_perfil(None) == ""

    def test_capsula_ganha_de_granel_quando_ambos_aparecem(self):
        # ordem de precedencia importa: capsula e o sinal mais forte de perfil
        assert transform.classificar_perfil("Cápsula Canastra granel") == "cápsula"


def _dados_base():
    return {
        "saudacao": "Café do Antônio",
        "nome": "CAFE DO ANTONIO",
        "dias_sem_comprar": "2573",
        "ultima_compra": "2019-07-23",
        "pedidos_faturados": "1",
        "total_gasto": "13918.48",
        "ticket_medio": "13918.48",
        "produto_para_citar": "Café Cru Beneficiado",
        "qtd_top1": "1200",
        "cpf_cnpj": "27114890000119",
        "cidade": "Gravataí",
        "uf": "RS",
        "cnae": "",
        "porte": "",
        "qtd_nfe": "1",
        "orcamentos": "0",
        "valor_vencido": "0.00",
        "titulos_vencidos": "0",
        "dias_atraso_max": "",
        "vendedor": "Arthur Silva Boaventura",
        "icp_score": "55",
        "icp_faixa": "C - medio",
        "id_bling": "5845664414",
        "motivo_exclusao": "",
    }


class TestMontarBriefing:
    def test_comeca_com_prefixo_do_lote(self):
        texto = transform.montar_briefing(_dados_base())
        assert texto.startswith(transform.PREFIXO_BRIEFING)

    def test_inclui_historico_de_compra(self):
        texto = transform.montar_briefing(_dados_base())
        assert "CLIENTE INATIVO há 2.573 dias" in texto
        assert "última compra: 23/07/2019" in texto
        assert "1 pedido" in texto
        assert "R$ 13.918,48" in texto

    def test_inclui_produto_com_quantidade(self):
        texto = transform.montar_briefing(_dados_base())
        assert "Comprava: Café Cru Beneficiado (1.200 un)" in texto

    def test_inclui_linha_de_perfil_quando_atipico(self):
        texto = transform.montar_briefing(_dados_base())
        assert "PERFIL: café verde/industrial" in texto

    def test_omite_linha_de_perfil_no_cafe_convencional(self):
        dados = _dados_base()
        dados["produto_para_citar"] = "Café Canastra Canela Moído 250g"
        texto = transform.montar_briefing(dados)
        assert "PERFIL:" not in texto

    def test_inclui_vendedor_anterior(self):
        texto = transform.montar_briefing(_dados_base())
        assert "Vendedor anterior: Arthur Silva Boaventura" in texto

    def test_perfil_atipico_aparece_mesmo_sem_historico_de_compra(self):
        # Fix round 3 (menor): a linha PERFIL vivia dentro do ramo "tem
        # compra" de montar_briefing — 3 dos 46 leads de perfil atipico que
        # NUNCA compraram (produto_para_citar preenchido, mas
        # total_gasto=0) ficavam sem a linha PERFIL. Precisa renderizar
        # sempre que o produto for conhecido, independente do historico.
        dados = _dados_base()
        dados.update({"total_gasto": "0.00", "pedidos_faturados": "0",
                      "ultima_compra": "", "dias_sem_comprar": "",
                      "produto_para_citar": "Cápsula Compatível Nespresso"})
        texto = transform.montar_briefing(dados)
        assert "LEAD SEM COMPRA — cadastrado no Bling, nunca faturou" in texto
        assert "PERFIL: cápsula" in texto

    def test_lead_sem_compra_troca_bloco_de_historico(self):
        dados = _dados_base()
        dados.update({"total_gasto": "0.00", "pedidos_faturados": "0",
                      "ultima_compra": "", "dias_sem_comprar": "",
                      "produto_para_citar": ""})
        texto = transform.montar_briefing(dados)
        assert "LEAD SEM COMPRA — cadastrado no Bling, nunca faturou" in texto
        assert "CLIENTE INATIVO" not in texto
        assert "Comprava:" not in texto

    def test_data_de_ultima_compra_indisponivel_omite_parenteses_vazio(self):
        # total_gasto > 0 mantem o ramo CLIENTE INATIVO, mas ultima_compra vem
        # com o sentinela do Bling ('0000-00-00') — formatar_data devolve '',
        # e a linha nao deve sobrar com um parenteses vazio "(última compra: )".
        dados = _dados_base()
        dados["ultima_compra"] = "0000-00-00"
        texto = transform.montar_briefing(dados)
        assert "(última compra: )" not in texto
        linha_inativo = next(l for l in texto.splitlines() if l.startswith("CLIENTE INATIVO"))
        assert linha_inativo == "CLIENTE INATIVO há 2.573 dias"

    def test_data_de_ultima_compra_disponivel_mantem_parenteses(self):
        # caso normal: com data valida, o parenteses com a data continua.
        texto = transform.montar_briefing(_dados_base())
        linha_inativo = next(l for l in texto.splitlines() if l.startswith("CLIENTE INATIVO"))
        assert linha_inativo == "CLIENTE INATIVO há 2.573 dias (última compra: 23/07/2019)"

    def test_debito_vencido_vira_alerta_de_cobranca(self):
        dados = _dados_base()
        dados.update({"valor_vencido": "1234.56", "titulos_vencidos": "3",
                      "dias_atraso_max": "180"})
        texto = transform.montar_briefing(dados)
        assert "DÉBITO VENCIDO: R$ 1.234,56 (3 títulos, máx 180 dias de atraso)" in texto
        assert "Sem débito em aberto" not in texto

    def test_sem_debito_declara_explicitamente(self):
        texto = transform.montar_briefing(_dados_base())
        assert "Sem débito em aberto" in texto

    def test_exclusao_aparece_na_primeira_linha(self):
        dados = _dados_base()
        dados["motivo_exclusao"] = "operação de café encerrada (cliente avisou)"
        texto = transform.montar_briefing(dados)
        primeira = texto.splitlines()[0]
        assert primeira == "⚠ FORA DA CAMPANHA: operação de café encerrada (cliente avisou)"
        assert transform.PREFIXO_BRIEFING in texto

    def test_cnpj_sai_formatado(self):
        texto = transform.montar_briefing(_dados_base())
        assert "CNPJ 27.114.890/0001-19" in texto

    def test_cidade_uf(self):
        texto = transform.montar_briefing(_dados_base())
        assert "Gravataí/RS" in texto

    def test_inclui_id_bling_e_icp(self):
        texto = transform.montar_briefing(_dados_base())
        assert "id_bling 5845664414" in texto
        assert "ICP 55" in texto

    def test_total_gasto_em_formato_br_nao_e_confundido_com_lead_sem_compra(self):
        # 13918,48 e o mesmo valor de _dados_base(), so que no formato BR (o
        # CSV Excel-friendly usa virgula decimal). Achatar isso para 0.0
        # classificaria erroneamente um cliente pagante como "nunca comprou".
        dados = _dados_base()
        dados["total_gasto"] = "13918,48"
        texto = transform.montar_briefing(dados)
        assert "CLIENTE INATIVO" in texto
        assert "LEAD SEM COMPRA" not in texto
        assert "R$ 13.918,48" in texto

    def test_cpf_de_pessoa_fisica_sai_rotulado_como_cpf_nao_cnpj(self):
        dados = _dados_base()
        dados["cpf_cnpj"] = "12345678901"
        texto = transform.montar_briefing(dados)
        assert "CPF 123.456.789-01" in texto
        assert "CNPJ" not in texto

    def test_documento_vazio_nao_deixa_rotulo_nem_espaco_sobrando(self):
        dados = _dados_base()
        dados["cpf_cnpj"] = ""
        texto = transform.montar_briefing(dados)
        assert "CNPJ" not in texto
        assert "CPF" not in texto
        # sem rotulo, a linha de cadastro nao deve ter espaco sobrando entre
        # 'Cadastro:' e o separador de cidade/uf (o documento inexiste).
        linha_cadastro = next(l for l in texto.splitlines() if l.startswith("Cadastro"))
        assert linha_cadastro == "Cadastro: · Gravataí/RS"


class TestNum:
    def test_formato_us_ponto_decimal(self):
        assert transform._num("1234.56") == 1234.56

    def test_formato_br_ponto_milhar_virgula_decimal(self):
        assert transform._num("1.234,56") == 1234.56

    def test_formato_br_so_virgula_decimal(self):
        assert transform._num("1234,56") == 1234.56

    def test_formato_br_milhar_grande(self):
        assert transform._num("13.918,48") == 13918.48

    def test_vazio_none_invalido_devolvem_zero(self):
        assert transform._num("") == 0.0
        assert transform._num(None) == 0.0
        assert transform._num("abc") == 0.0


class TestFormatarData:
    def test_data_valida(self):
        assert transform.formatar_data("2019-07-23") == "23/07/2019"

    def test_vazia(self):
        assert transform.formatar_data("") == ""

    def test_sentinela_bling_zero_absoluto(self):
        assert transform.formatar_data("0000-00-00") == ""

    def test_sentinela_bling_ano_zero_com_dia_mes_validos(self):
        assert transform.formatar_data("0000-01-01") == ""


class TestNormalizarTelefoneCanonico:
    def test_br_doze_digitos_recebe_nono_digito(self):
        assert transform.normalizar_telefone_canonico("554342453258") == "5543942453258"

    def test_treze_digitos_permanece(self):
        assert transform.normalizar_telefone_canonico("5534991461669") == "5534991461669"

    def test_fixo_dez_digitos_vira_treze(self):
        assert transform.normalizar_telefone_canonico("3432151234") == "5534932151234"

    def test_onze_digitos_recebe_55(self):
        assert transform.normalizar_telefone_canonico("34991461669") == "5534991461669"

    def test_zero_inicial_e_descartado(self):
        assert transform.normalizar_telefone_canonico("034991461669") == "5534991461669"

    def test_internacional_nao_recebe_nono_digito(self):
        assert transform.normalizar_telefone_canonico("971542711390") == "971542711390"
        assert transform.normalizar_telefone_canonico("353892098541") == "353892098541"

    def test_formatado_com_pontuacao(self):
        assert transform.normalizar_telefone_canonico("(43) 4245-3258") == "5543942453258"

    def test_vazio_e_invalido_devolvem_vazio(self):
        assert transform.normalizar_telefone_canonico("") == ""
        assert transform.normalizar_telefone_canonico(None) == ""
        assert transform.normalizar_telefone_canonico("123") == ""

    def test_divergencia_documentada_com_a_funcao_antiga(self):
        # A funcao antiga preserva 12 digitos; a canonica injeta o 9.
        assert transform.normalizar_telefone("554342453258") == "554342453258"
        assert transform.normalizar_telefone_canonico("554342453258") == "5543942453258"
