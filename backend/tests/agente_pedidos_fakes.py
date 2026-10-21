"""Dubles dos testes do agente de pedidos: Supabase que FILTRA de verdade,
Redis em memoria e cliente Bling falso. Nada aqui fala com servico real."""
import re


def _casa_ilike(valor, padrao: str) -> bool:
    if valor is None:
        return False
    regex = "^" + ".*".join(re.escape(p) for p in padrao.lower().split("%")) + "$"
    return re.match(regex, str(valor).lower()) is not None


def _casa_condicao(linha: dict, cond: str) -> bool:
    coluna, op, alvo = cond.split(".", 2)
    if op == "ilike":
        return _casa_ilike(linha.get(coluna), alvo)
    if op == "eq":
        return str(linha.get(coluna)) == alvo
    if op == "in":
        valores = alvo.strip("()").split(",")
        return str(linha.get(coluna)) in valores
    raise AssertionError(f"operador nao suportado no duble: {op}")


def _separar_or(expr: str) -> list[str]:
    partes, nivel, atual = [], 0, ""
    for ch in expr:
        if ch == "(":
            nivel += 1
        elif ch == ")":
            nivel -= 1
        if ch == "," and nivel == 0:
            partes.append(atual)
            atual = ""
        else:
            atual += ch
    partes.append(atual)
    return partes


class FakeQuery:
    def __init__(self, sb, tabela):
        self.sb = sb
        self.tabela = tabela
        self.filtros = []
        self.ors = []
        self.limite = None
        self.unico = False
        self.ordem = None
        self.op = "select"
        self.valores = None

    def select(self, *_a, **_k):
        return self

    def eq(self, coluna, valor):
        self.filtros.append(lambda l, c=coluna, v=valor: l.get(c) == v)
        self.sb.eqs.append((self.tabela, coluna, valor))
        return self

    def in_(self, coluna, valores):
        valores = list(valores)
        self.filtros.append(lambda l, c=coluna, v=valores: l.get(c) in v)
        return self

    def ilike(self, coluna, padrao):
        self.filtros.append(lambda l, c=coluna, p=padrao: _casa_ilike(l.get(c), p))
        return self

    def or_(self, expr):
        self.ors.append(expr)
        conds = _separar_or(expr)
        self.filtros.append(lambda l, cs=conds: any(_casa_condicao(l, c) for c in cs))
        return self

    def order(self, coluna, *_a, **_k):
        self.ordem = coluna
        return self

    def limit(self, n, *_a, **_k):
        self.limite = n
        return self

    def maybe_single(self):
        self.unico = True
        return self

    def upsert(self, valores, **_k):
        self.op, self.valores = "upsert", valores
        return self

    def insert(self, valores, **_k):
        self.op, self.valores = "insert", valores
        return self

    def update(self, valores, **_k):
        self.op, self.valores = "update", valores
        return self

    def execute(self):
        class R:
            pass
        r = R()
        linhas = self.sb.tabelas.setdefault(self.tabela, [])
        if self.op in ("insert", "upsert"):
            novas = self.valores if isinstance(self.valores, list) else [self.valores]
            linhas.extend(dict(n) for n in novas)
            self.sb.escritas.append((self.op, self.tabela, self.valores))
            r.data = novas
            return r
        achadas = [l for l in linhas if all(f(l) for f in self.filtros)]
        if self.op == "update":
            for l in achadas:
                l.update(self.valores)
            self.sb.escritas.append(("update", self.tabela, self.valores))
            r.data = achadas
            return r
        if self.ordem:
            achadas = sorted(achadas, key=lambda l: str(l.get(self.ordem) or ""))
        if self.limite is not None:
            achadas = achadas[: self.limite]
        r.data = (achadas[0] if achadas else None) if self.unico else [dict(l) for l in achadas]
        return r


class FakeSupabase:
    def __init__(self, tabelas: dict | None = None):
        self.tabelas = {k: [dict(l) for l in v] for k, v in (tabelas or {}).items()}
        self.queries: list[FakeQuery] = []
        self.eqs: list[tuple] = []
        self.escritas: list[tuple] = []

    def table(self, nome):
        q = FakeQuery(self, nome)
        self.queries.append(q)
        return q


class FakeRedis:
    """get / set(nx, ex) / delete, como o redis.asyncio com decode_responses."""

    def __init__(self):
        self.dados: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, chave):
        return self.dados.get(chave)

    async def set(self, chave, valor, nx=False, ex=None):
        if nx and chave in self.dados:
            return None
        self.dados[chave] = valor
        self.ttls[chave] = ex
        return True

    async def delete(self, *chaves):
        n = 0
        for c in chaves:
            if c in self.dados:
                del self.dados[c]
                n += 1
        return n


class FakeBling:
    """Cliente Bling falso: respostas por (metodo, caminho), registra chamadas."""

    def __init__(self, respostas: dict | None = None):
        self.respostas = respostas or {}
        self.chamadas: list[tuple] = []

    def _responder(self, metodo, caminho, corpo):
        self.chamadas.append((metodo, caminho, corpo))
        r = self.respostas.get((metodo, caminho))
        if r is None:
            raise AssertionError(f"chamada inesperada ao Bling: {metodo} {caminho}")
        if callable(r):
            r = r(corpo)
        if isinstance(r, Exception):
            raise r
        return r

    async def get(self, caminho, params=None):
        return self._responder("GET", caminho, params)

    async def post(self, caminho, json=None):
        return self._responder("POST", caminho, json)

    async def put(self, caminho, json=None):
        return self._responder("PUT", caminho, json)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def posts(self, caminho=None):
        return [c for c in self.chamadas if c[0] == "POST" and (caminho is None or c[1] == caminho)]


# Espelho padrao usado pelos testes de rascunho.
ESPELHO = {
    "bling_contacts": [
        {"id": 10, "account": "default", "nome": "Empório X Ltda", "fantasia": "Empório X",
         "doc_digits": "11222333000181", "telefone_e164": "553432221111",
         "celular_e164": "5534999998888", "situacao": "A",
         "endereco": {"municipio": "Uberlândia", "uf": "MG"}},
        {"id": 11, "account": "default", "nome": "Mercado Y", "fantasia": None,
         "doc_digits": "52998224725", "telefone_e164": None, "celular_e164": None,
         "situacao": "A", "endereco": None},
        {"id": 12, "account": "default", "nome": "Empório Velho", "fantasia": None,
         "doc_digits": "00000000000191", "situacao": "I", "endereco": None},
        {"id": 20, "account": "secundaria", "nome": "Empório X da conta 2",
         "doc_digits": "11222333000181", "situacao": "A", "endereco": None},
        {"id": 900, "account": "default", "nome": "Fábrica Canastra", "doc_digits": "11444777000161",
         "situacao": "A", "endereco": None},
    ],
    "bling_products": [
        {"id": 1, "account": "default", "codigo": "GOU-M500", "nome": "Gourmet Moído 500g",
         "preco": 45.0, "unidade": "UN", "saldo_virtual": 30, "situacao": "A"},
        {"id": 2, "account": "default", "codigo": "ESP-G1K", "nome": "Especial Grão 1kg",
         "preco": 63.0, "unidade": "UN", "saldo_virtual": 5, "situacao": "A"},
        {"id": 3, "account": "default", "codigo": "OLD", "nome": "Gourmet Antigo",
         "preco": 10.0, "unidade": "UN", "saldo_virtual": 0, "situacao": "I"},
        {"id": 5, "account": "secundaria", "codigo": "GOU-M500", "nome": "Gourmet Moído 500g (2)",
         "preco": 44.0, "unidade": "UN", "saldo_virtual": 1, "situacao": "A"},
    ],
    "bling_payment_methods": [
        {"id": 100, "account": "default", "descricao": "Boleto", "situacao": 1, "finalidade": 2},
        {"id": 101, "account": "default", "descricao": "Pix", "situacao": 1, "finalidade": 3},
        {"id": 102, "account": "default", "descricao": "Transferência (pagar)", "situacao": 1,
         "finalidade": 1},
        {"id": 103, "account": "default", "descricao": "Cheque", "situacao": 0, "finalidade": 3},
    ],
    "bling_sellers": [
        {"id": 50, "account": "default", "nome": "João", "situacao": "A"},
        {"id": 51, "account": "default", "nome": "Antigo", "situacao": "I"},
        {"id": 60, "account": "secundaria", "nome": "Maria", "situacao": "A"},
    ],
}
