"""P1.3 — busca manual de contato Bling aceita CPF/CNPJ digitado com máscara.

Caso Vida Natural (call de 01/10): o vendedor colou o CNPJ formatado e nada voltou, porque
`doc_digits` só tem dígitos e o termo ia cru para o `ilike`.
"""
import app.bling.router as br


class _Q:
    def __init__(self):
        self.eqs = {}
        self.ors = []

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.eqs[col] = val
        return self

    def or_(self, expr):
        self.ors.append(expr)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        class R:
            data = []
        return R()


def _rodar(monkeypatch, termo):
    q = _Q()

    class SB:
        def table(self, _nome):
            return q

    monkeypatch.setattr(br, "get_supabase", lambda: SB())
    br._query_contacts(termo, 20, "default")
    return q


def test_cnpj_com_mascara_vira_filtro_exato_em_doc_digits(monkeypatch):
    q = _rodar(monkeypatch, "12.345.678/0001-90")
    assert q.eqs["doc_digits"] == "12345678000190"
    assert q.eqs["account"] == "default"
    assert q.ors == [], "documento nao pode cair no ilike de nome"


def test_cpf_com_mascara_vira_filtro_exato(monkeypatch):
    q = _rodar(monkeypatch, " 123.456.789-09 ")
    assert q.eqs["doc_digits"] == "12345678909"


def test_cnpj_so_digitos_tambem_usa_filtro_exato(monkeypatch):
    q = _rodar(monkeypatch, "12345678000190")
    assert q.eqs["doc_digits"] == "12345678000190"


def test_nome_continua_no_ilike(monkeypatch):
    q = _rodar(monkeypatch, "Vida Natural")
    assert "doc_digits" not in q.eqs
    assert q.ors == ["nome.ilike.%Vida Natural%,fantasia.ilike.%Vida Natural%,"
                     "doc_digits.ilike.%Vida Natural%"]


def test_numero_que_nao_e_documento_continua_no_ilike(monkeypatch):
    # 8 digitos: pedaco de CNPJ ou telefone — nao e documento inteiro.
    q = _rodar(monkeypatch, "12.345.678")
    assert "doc_digits" not in q.eqs
    assert len(q.ors) == 1


def test_texto_com_letras_e_11_digitos_nao_e_documento():
    assert br._documento_do_termo("Loja 123.456.789-09") is None
    assert br._documento_do_termo("") is None
    assert br._documento_do_termo(None) is None
