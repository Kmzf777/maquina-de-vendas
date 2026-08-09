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
