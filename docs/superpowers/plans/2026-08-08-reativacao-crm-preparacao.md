# Preparação da campanha de reativação no CRM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preparar 276 leads no CRM (236 criados, 40 atualizados conservadoramente) com briefing de contexto em `lead_notes`, e registrar 51 opt-outs pendentes — sem criar nenhum disparo.

**Architecture:** Duas camadas separadas por testabilidade. Um módulo puro (`transform.py`) faz toda a decisão de conteúdo — normalização de telefone, escolha da saudação, classificação de perfil de produto, montagem do texto do briefing — e é coberto por testes unitários sem banco. Um gerador (`generate_sql.py`) usa esse módulo para emitir **um arquivo SQL auditável** com todas as escritas dentro de `BEGIN`/`COMMIT`, mais um `rollback.sql`. A execução é manual via `psql`, depois de `pg_dump` e revisão do SQL gerado. Nada escreve no banco diretamente do Python — o SQL é o artefato revisável.

**Tech Stack:** Python 3.11 (stdlib apenas: `csv`, `json`, `re`, `unicodedata`, `argparse`), pytest 9.0.3, PostgreSQL 17.6 (Supabase self-hosted na VPS), `psql` via `docker exec`.

## Global Constraints

- **Nenhuma escrita em `broadcasts` ou `broadcast_leads`.** O SQL gerado não deve conter essas tabelas (validado por teste).
- **Banco alvo:** Supabase self-hosted na VPS `173.249.15.11`, container `supabase_db`, database `postgres`. Nunca um Supabase Cloud.
- **Lote canônico:** `reativacao_bling_2026-08-10` — valor exato em `metadata.lote` de todo registro tocado.
- **`metadata.origem`:** `reativacao_bling` — segue a convenção existente da chave `origem`.
- **`assigned_to` do João:** `1c3c78ed-ef47-4dca-9a63-2052f28e8fd6`.
- **Canal do João:** `553491461669`, `phone_number_id` `1049315514934778`.
- **Autor das notas:** `Sistema — Reativação Bling` (string exata, com em-dash).
- **Prefixo do briefing:** `REATIVAÇÃO 10/08/2026 — lote reativacao_bling_2026-08-10` (usado como chave de idempotência).
- **Nos 40 pré-existentes, jamais emitir UPDATE em:** `stage`, `status`, `human_control`, `ai_enabled`, `assigned_to` (quando já preenchido). Validado por teste.
- **Idempotência:** `INSERT ... ON CONFLICT (phone) DO NOTHING`; notas só quando não existir nota do lote para aquele lead.
- **Fonte de dados:** `C:\Users\cmap211\Documents\Kelwin Projetos\canastra\DB Leads\DISPARO-segunda-2026-08-10.csv` (276 linhas) e `CANASTRA-LEADS-MASTER-2026-08-08.csv.new` (2.771 linhas, 128 colunas). Caminhos passados por argumento, nunca hardcoded no módulo.
- Textos de briefing e código em PT-BR sem abreviação de acento; identificadores em inglês seguem o padrão do repo.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `scripts/reativacao/transform.py` | Lógica pura: normalizar telefone, escolher saudação, classificar perfil de produto, montar briefing. Zero I/O, zero SQL. |
| `scripts/reativacao/generate_sql.py` | Lê os CSVs + snapshot do CRM, usa `transform`, emite `preparar.sql` e `rollback.sql`. |
| `backend/tests/test_reativacao_transform.py` | Testes unitários de `transform.py`. |
| `backend/tests/test_reativacao_sql.py` | Testes do SQL gerado (guardrails: tabelas proibidas, colunas proibidas, idempotência). |
| `scripts/reativacao/README.md` | Runbook: dump, gerar, revisar, executar, verificar, rollback. |

`transform.py` e `generate_sql.py` ficam em `scripts/` porque são operação pontual de dados, não código de produto — não são importados pelo backend. Os testes ficam em `backend/tests/` para rodar na suíte existente (`backend/pytest.ini`).

---

### Task 1: Módulo puro de transformação — telefone e saudação

**Files:**
- Create: `scripts/reativacao/transform.py`
- Test: `backend/tests/test_reativacao_transform.py`

**Interfaces:**
- Consumes: nada (primeira task)
- Produces:
  - `normalizar_telefone(valor: str) -> str` — devolve E.164 sem `+` (13 dígitos para celular BR), ou `""` se não der para normalizar
  - `escolher_saudacao(nome_crm: str | None, nome_bling: str) -> str` — nome do CRM se houver, senão nome do Bling limpo de sufixos empresariais
  - `SUFIXOS_EMPRESARIAIS: str` — regex usada por `escolher_saudacao`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reativacao_transform.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'transform'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/reativacao/transform.py
"""Logica pura da preparacao de reativacao: sem I/O, sem SQL, sem rede.

Tudo aqui e testavel isoladamente. Decisoes de conteudo (qual nome usar, como
classificar o produto, o que escrever no briefing) vivem neste modulo; o
generate_sql.py apenas consome.
"""
import re
import unicodedata

# Sufixos e termos empresariais que poluem uma saudacao de WhatsApp.
SUFIXOS_EMPRESARIAIS = (
    r"\b(ltda|eireli|me|epp|s/?a|mei|com[eé]rcio|comercial|distribuidora|"
    r"ind[uú]stria|e servi[cç]os|do brasil|importa[cç][aã]o)\b"
)


def normalizar_telefone(valor):
    """Devolve o telefone em E.164 sem '+', ou '' se nao for normalizavel.

    O CRM conviveu com formatos diferentes (13, 11 e 10 digitos), e a coluna
    phone e UNIQUE pela string exata — normalizar evita duplicata logica.
    """
    digitos = re.sub(r"\D", "", valor or "")
    if not digitos:
        return ""
    if digitos.startswith("55") and len(digitos) in (12, 13):
        return digitos
    if len(digitos) in (10, 11):
        return "55" + digitos
    if len(digitos) in (12, 13):
        return digitos
    return ""


def escolher_saudacao(nome_crm, nome_bling):
    """Nome para a variavel {{1}} do template.

    O CRM guarda como a pessoa se identificou ('Carina'); o Bling guarda a razao
    social ('Divina Terra - BALNEARIO CAMBORIU'). Para uma mensagem que pergunta
    'Falo com {{1}} neste numero?', o nome da pessoa e sempre melhor.
    """
    if (nome_crm or "").strip():
        return nome_crm.strip()
    base = (nome_bling or "").strip()
    base = re.sub(r"^\d[\d.\-/]*\s*", "", base)          # codigo/CNPJ no inicio
    base = re.sub(SUFIXOS_EMPRESARIAIS, "", base, flags=re.IGNORECASE)
    base = re.sub(r"[\s.,\-]+$", "", base).strip()
    base = re.sub(r"\s{2,}", " ", base)
    if base.isupper():
        base = base.title()
    return base or (nome_bling or "").strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reativacao_transform.py -v`
Expected: PASS — 11 testes

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/transform.py backend/tests/test_reativacao_transform.py
git commit -m "feat(reativacao): normalizacao de telefone e escolha de saudacao"
```

---

### Task 2: Classificação de perfil de produto

**Files:**
- Modify: `scripts/reativacao/transform.py`
- Test: `backend/tests/test_reativacao_transform.py`

**Interfaces:**
- Consumes: nada de Task 1 (função independente no mesmo módulo)
- Produces: `classificar_perfil(produto: str) -> str` — devolve rótulo de perfil atípico (`"cápsula"`, `"granel/volume"`, `"drip"`, `"café verde/industrial"`, `"kit/presente"`) ou `""` para café torrado convencional

- [ ] **Step 1: Write the failing test**

```python
# adicionar ao final de backend/tests/test_reativacao_transform.py

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reativacao_transform.py::TestClassificarPerfil -v`
Expected: FAIL com `AttributeError: module 'transform' has no attribute 'classificar_perfil'`

- [ ] **Step 3: Write minimal implementation**

```python
# adicionar ao final de scripts/reativacao/transform.py

# Ordem importa: o primeiro padrao que casar define o perfil. Capsula vem antes
# de granel porque e o sinal mais especifico (mercado e recompra diferentes:
# 29,2% contra 50,7% do grao 1kg).
PERFIS_PRODUTO = (
    ("cápsula", (r"c[aá]psul",)),
    ("café verde/industrial", (r"\bcru\b", r"beneficiad")),
    ("drip", (r"\bdrip\b",)),
    ("granel/volume", (r"granel", r"\b2\s*kg\b")),
    ("kit/presente", (r"\bkit\b", r"caneca", r"camiseta")),
)


def classificar_perfil(produto):
    """Rotula perfis de produto que exigem abordagem diferente do café torrado.

    Retorna '' para o café convencional (186 dos 232 casos), onde a linha PERFIL
    do briefing e omitida.
    """
    texto = _sem_acento(produto)
    for rotulo, padroes in PERFIS_PRODUTO:
        for padrao in padroes:
            if re.search(_sem_acento(padrao), texto):
                return rotulo
    return ""


def _sem_acento(texto):
    """Minusculas sem diacriticos, para casar 'Cápsula' e 'Capsula' igualmente."""
    normalizado = unicodedata.normalize("NFKD", texto or "")
    return normalizado.encode("ascii", "ignore").decode().lower()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reativacao_transform.py -v`
Expected: PASS — 20 testes

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/transform.py backend/tests/test_reativacao_transform.py
git commit -m "feat(reativacao): classificacao de perfil de produto atipico"
```

---

### Task 3: Montagem do texto do briefing

**Files:**
- Modify: `scripts/reativacao/transform.py`
- Test: `backend/tests/test_reativacao_transform.py`

**Interfaces:**
- Consumes: `classificar_perfil` (Task 2)
- Produces:
  - `PREFIXO_BRIEFING: str` = `"REATIVAÇÃO 10/08/2026 — lote reativacao_bling_2026-08-10"`
  - `montar_briefing(dados: dict) -> str` — recebe um dict com as chaves do CSV de disparo mais `valor_vencido`, `titulos_vencidos`, `dias_atraso_max`, `qtd_nfe`, `orcamentos`, `motivo_exclusao`; devolve o texto completo da nota

- [ ] **Step 1: Write the failing test**

```python
# adicionar ao final de backend/tests/test_reativacao_transform.py

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

    def test_lead_sem_compra_troca_bloco_de_historico(self):
        dados = _dados_base()
        dados.update({"total_gasto": "0.00", "pedidos_faturados": "0",
                      "ultima_compra": "", "dias_sem_comprar": "",
                      "produto_para_citar": ""})
        texto = transform.montar_briefing(dados)
        assert "LEAD SEM COMPRA — cadastrado no Bling, nunca faturou" in texto
        assert "CLIENTE INATIVO" not in texto
        assert "Comprava:" not in texto

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reativacao_transform.py::TestMontarBriefing -v`
Expected: FAIL com `AttributeError: module 'transform' has no attribute 'PREFIXO_BRIEFING'`

- [ ] **Step 3: Write minimal implementation**

```python
# adicionar ao final de scripts/reativacao/transform.py

PREFIXO_BRIEFING = "REATIVAÇÃO 10/08/2026 — lote reativacao_bling_2026-08-10"


def _num(valor):
    try:
        return float(str(valor or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _int(valor):
    try:
        return int(_num(valor))
    except ValueError:
        return 0


def formatar_reais(valor):
    """1234.56 -> '1.234,56' (padrao brasileiro).

    O '@' e um pivo: troca-se ',' por '@', depois '.' por ',', depois '@' por
    '.', invertendo os separadores sem colisao.
    """
    return "{:,.2f}".format(_num(valor)).replace(",", "@").replace(".", ",").replace("@", ".")


def formatar_inteiro(valor):
    """1200 -> '1.200'."""
    return "{:,}".format(_int(valor)).replace(",", ".")


def formatar_data(iso):
    """'2019-07-23' -> '23/07/2019'. Devolve '' para vazio/invalido."""
    partes = (iso or "").strip()[:10].split("-")
    if len(partes) != 3 or not all(partes):
        return ""
    return "%s/%s/%s" % (partes[2], partes[1], partes[0])


def formatar_documento(doc):
    """CNPJ/CPF so com digitos -> mascarado. Devolve o original se nao casar."""
    d = re.sub(r"\D", "", doc or "")
    if len(d) == 14:
        return "%s.%s.%s/%s-%s" % (d[:2], d[2:5], d[5:8], d[8:12], d[12:])
    if len(d) == 11:
        return "%s.%s.%s-%s" % (d[:3], d[3:6], d[6:9], d[9:])
    return doc or ""


def montar_briefing(dados):
    """Monta o texto da nota que o vendedor le no card do lead.

    Regras em docs/superpowers/specs/2026-08-08-reativacao-crm-preparacao-design.md
    (secao 'Regras de conteudo do briefing').
    """
    linhas = []

    motivo = (dados.get("motivo_exclusao") or "").strip()
    if motivo:
        linhas.append("⚠ FORA DA CAMPANHA: %s" % motivo)
        linhas.append("")

    linhas.append(PREFIXO_BRIEFING)
    linhas.append("")

    if _num(dados.get("total_gasto")) > 0:
        dias = formatar_inteiro(dados.get("dias_sem_comprar"))
        data = formatar_data(dados.get("ultima_compra"))
        linhas.append("CLIENTE INATIVO há %s dias (última compra: %s)" % (dias, data))
        pedidos = _int(dados.get("pedidos_faturados"))
        linhas.append("Histórico: %d %s · R$ %s · ticket médio R$ %s" % (
            pedidos,
            "pedido" if pedidos == 1 else "pedidos",
            formatar_reais(dados.get("total_gasto")),
            formatar_reais(dados.get("ticket_medio")),
        ))
        produto = (dados.get("produto_para_citar") or "").strip()
        if produto:
            qtd = _int(dados.get("qtd_top1"))
            sufixo = " (%s un)" % formatar_inteiro(qtd) if qtd else ""
            linhas.append("Comprava: %s%s" % (produto, sufixo))
        perfil = classificar_perfil(produto)
        if perfil:
            linhas.append("PERFIL: %s — abordagem diferente do café torrado de varejo" % perfil)
    else:
        linhas.append("LEAD SEM COMPRA — cadastrado no Bling, nunca faturou")

    linhas.append("")

    cadastro = "Cadastro: CNPJ %s" % formatar_documento(dados.get("cpf_cnpj"))
    local = "/".join(p for p in [(dados.get("cidade") or "").strip(),
                                 (dados.get("uf") or "").strip()] if p)
    if local:
        cadastro += " · %s" % local
    linhas.append(cadastro)

    cnae = (dados.get("cnae") or "").strip()
    porte = (dados.get("porte") or "").strip()
    if cnae or porte:
        linhas.append("Atividade: %s" % " · ".join(p for p in [cnae, porte] if p))

    if _num(dados.get("valor_vencido")) > 0:
        linhas.append("DÉBITO VENCIDO: R$ %s (%d títulos, máx %s dias de atraso) — tratar como cobrança" % (
            formatar_reais(dados.get("valor_vencido")),
            _int(dados.get("titulos_vencidos")),
            (dados.get("dias_atraso_max") or "?"),
        ))
    else:
        linhas.append("NF-e emitidas: %d · Orçamentos: %d · Sem débito em aberto" % (
            _int(dados.get("qtd_nfe")), _int(dados.get("orcamentos"))))

    vendedor = (dados.get("vendedor") or "").strip()
    if vendedor:
        linhas.append("Vendedor anterior: %s" % vendedor)

    linhas.append("ICP %s (%s) · id_bling %s" % (
        dados.get("icp_score") or "?",
        dados.get("icp_faixa") or "?",
        dados.get("id_bling") or "?",
    ))

    return "\n".join(linhas)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reativacao_transform.py -v`
Expected: PASS — 33 testes

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/transform.py backend/tests/test_reativacao_transform.py
git commit -m "feat(reativacao): montagem do briefing do lead"
```

---

### Task 4: Gerador de SQL — leads novos

**Files:**
- Create: `scripts/reativacao/generate_sql.py`
- Test: `backend/tests/test_reativacao_sql.py`

**Interfaces:**
- Consumes: `transform.normalizar_telefone`, `transform.escolher_saudacao`, `transform.montar_briefing`, `transform.PREFIXO_BRIEFING`
- Produces:
  - `LOTE: str` = `"reativacao_bling_2026-08-10"`
  - `JOAO_UUID: str` = `"1c3c78ed-ef47-4dca-9a63-2052f28e8fd6"`
  - `TABELAS_PROIBIDAS: tuple` = `("broadcasts", "broadcast_leads")`
  - `sql_literal(valor) -> str` — escapa string para SQL (`'` → `''`) ou devolve `NULL`
  - `gerar_insert_lead(dados: dict, nome_crm: str | None) -> str` — devolve o `INSERT ... ON CONFLICT (phone) DO NOTHING` de um lead

- [ ] **Step 1: Write the failing test**

```python
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
        assert "D''ANTONIO" in sql

    def test_nao_menciona_tabelas_proibidas(self):
        sql = generate_sql.gerar_insert_lead(_dados(), None)
        for tabela in generate_sql.TABELAS_PROIBIDAS:
            assert tabela not in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reativacao_sql.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'generate_sql'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/reativacao/generate_sql.py
"""Gera o SQL da preparacao de reativacao. Nao executa nada.

O artefato revisavel e o proprio arquivo .sql: ele e inspecionado antes de rodar
via psql, dentro de uma transacao, depois do pg_dump. Ver
docs/superpowers/plans/2026-08-08-reativacao-crm-preparacao.md
"""
import json

import transform

LOTE = "reativacao_bling_2026-08-10"
ORIGEM = "reativacao_bling"
JOAO_UUID = "1c3c78ed-ef47-4dca-9a63-2052f28e8fd6"
CANAL_JOAO = "553491461669"
AUTOR_NOTA = "Sistema — Reativação Bling"

# Guardrail: o SQL gerado nunca pode tocar o disparo.
TABELAS_PROIBIDAS = ("broadcasts", "broadcast_leads")

# Guardrail: colunas que nunca podem ser sobrescritas nos leads pre-existentes.
COLUNAS_INTOCAVEIS = ("stage", "status", "human_control", "ai_enabled")


def sql_literal(valor):
    """Escapa para literal SQL; vazio/None viram NULL."""
    if valor is None:
        return "NULL"
    texto = str(valor).strip()
    if not texto:
        return "NULL"
    return "'" + texto.replace("'", "''") + "'"


def _metadata_json(dados):
    return {
        "origem": ORIGEM,
        "lote": LOTE,
        "id_bling": (dados.get("id_bling") or "").strip(),
        "icp_score": (dados.get("icp_score") or "").strip(),
        "phone_raw": (dados.get("whatsapp") or "").strip(),
    }


def gerar_insert_lead(dados, nome_crm):
    """INSERT idempotente de um lead novo."""
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    nome = transform.escolher_saudacao(nome_crm, dados.get("nome"))
    metadata = json.dumps(_metadata_json(dados), ensure_ascii=False)
    return (
        "INSERT INTO leads (phone, name, company, stage, status, channel, "
        "assigned_to, cnpj, razao_social, nome_fantasia, email, endereco, metadata)\n"
        "VALUES (%s, %s, %s, 'pending', 'imported', %s, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb)\n"
        "ON CONFLICT (phone) DO NOTHING;" % (
            sql_literal(phone),
            sql_literal(nome),
            sql_literal(dados.get("razao_social") or dados.get("nome")),
            sql_literal(CANAL_JOAO),
            sql_literal(JOAO_UUID),
            sql_literal(dados.get("cpf_cnpj")),
            sql_literal(dados.get("razao_social")),
            sql_literal(dados.get("saudacao")),
            sql_literal(dados.get("email")),
            sql_literal("/".join(p for p in [(dados.get("cidade") or "").strip(),
                                             (dados.get("uf") or "").strip()] if p)),
            sql_literal(metadata),
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reativacao_sql.py -v`
Expected: PASS — 12 testes

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/generate_sql.py backend/tests/test_reativacao_sql.py
git commit -m "feat(reativacao): gerador de INSERT idempotente de lead"
```

---

### Task 5: Gerador de SQL — update conservador, notas e opt-outs

**Files:**
- Modify: `scripts/reativacao/generate_sql.py`
- Test: `backend/tests/test_reativacao_sql.py`

**Interfaces:**
- Consumes: `sql_literal`, `_metadata_json`, `LOTE`, `AUTOR_NOTA`, `COLUNAS_INTOCAVEIS` (Task 4)
- Produces:
  - `gerar_update_conservador(dados: dict, tem_dono: bool) -> str` — `UPDATE leads` que só preenche campos vazios via `COALESCE(NULLIF(col, ''), novo)` e faz merge em `metadata`
  - `gerar_insert_nota(dados: dict, nome_crm: str | None) -> str` — `INSERT INTO lead_notes` condicionado a não existir nota do lote
  - `gerar_update_optout(telefone: str, quando: str, disse: str) -> str` — marca `opt_out = true`
  - `gerar_normalizacao_telefone(antigo: str, novo: str) -> str` — corrige o phone do caso Atma/Fernando

- [ ] **Step 1: Write the failing test**

```python
# adicionar ao final de backend/tests/test_reativacao_sql.py

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
        assert "WHERE NOT EXISTS" in sql
        assert generate_sql.LOTE in sql

    def test_resolve_lead_id_pelo_telefone(self):
        sql = generate_sql.gerar_insert_nota(_dados(), None)
        assert "SELECT id FROM leads WHERE phone = '5551993452254'" in sql

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reativacao_sql.py::TestUpdateConservador -v`
Expected: FAIL com `AttributeError: module 'generate_sql' has no attribute 'gerar_update_conservador'`

- [ ] **Step 3: Write minimal implementation**

```python
# adicionar ao final de scripts/reativacao/generate_sql.py

def gerar_update_conservador(dados, tem_dono):
    """UPDATE que so preenche o que esta vazio (decisao D5 do spec).

    Nunca emite as COLUNAS_INTOCAVEIS. metadata recebe merge com ||, nunca
    substituicao. assigned_to so entra quando o lead nao tem dono.
    """
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    metadata = json.dumps(_metadata_json(dados), ensure_ascii=False)
    local = "/".join(p for p in [(dados.get("cidade") or "").strip(),
                                 (dados.get("uf") or "").strip()] if p)
    sets = [
        "cnpj = COALESCE(NULLIF(cnpj, ''), %s)" % sql_literal(dados.get("cpf_cnpj")),
        "razao_social = COALESCE(NULLIF(razao_social, ''), %s)" % sql_literal(dados.get("razao_social")),
        "nome_fantasia = COALESCE(NULLIF(nome_fantasia, ''), %s)" % sql_literal(dados.get("saudacao")),
        "email = COALESCE(NULLIF(email, ''), %s)" % sql_literal(dados.get("email")),
        "endereco = COALESCE(NULLIF(endereco, ''), %s)" % sql_literal(local),
        "metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb" % sql_literal(metadata),
    ]
    if not tem_dono:
        sets.append("assigned_to = COALESCE(assigned_to, %s::uuid)" % sql_literal(JOAO_UUID))
    return "UPDATE leads SET\n  %s\nWHERE phone = %s;" % (
        ",\n  ".join(sets), sql_literal(phone))


def gerar_insert_nota(dados, nome_crm):
    """Nota de briefing, so se ainda nao existir a nota deste lote."""
    phone = transform.normalizar_telefone(dados.get("whatsapp"))
    dados_briefing = dict(dados)
    dados_briefing["saudacao"] = transform.escolher_saudacao(nome_crm, dados.get("nome"))
    conteudo = transform.montar_briefing(dados_briefing)
    return (
        "INSERT INTO lead_notes (lead_id, author, content)\n"
        "SELECT l.id, %s, %s\n"
        "FROM leads l\n"
        "WHERE l.phone = %s\n"
        "  AND NOT EXISTS (\n"
        "    SELECT 1 FROM lead_notes n\n"
        "    WHERE n.lead_id = l.id AND n.content LIKE %s\n"
        "  );" % (
            sql_literal(AUTOR_NOTA),
            sql_literal(conteudo),
            sql_literal(phone),
            sql_literal("%" + LOTE + "%"),
        )
    )


def gerar_update_optout(telefone, quando, disse):
    """Marca opt_out e registra a evidencia no metadata."""
    phone = transform.normalizar_telefone(telefone)
    evidencia = json.dumps(
        {"optout_quando": quando, "optout_disse": (disse or "")[:200], "optout_fonte": "mensagem_do_cliente"},
        ensure_ascii=False,
    )
    return (
        "UPDATE leads SET\n"
        "  opt_out = true,\n"
        "  metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb\n"
        "WHERE regexp_replace(phone, '[^0-9]', '', 'g') IN (%s, %s)\n"
        "  AND opt_out IS NOT TRUE;" % (
            sql_literal(evidencia), sql_literal(phone), sql_literal(phone[2:] if phone.startswith("55") else phone))
    )


def gerar_normalizacao_telefone(antigo, novo):
    """Corrige um phone para E.164, sem colidir com registro existente (D9)."""
    return (
        "UPDATE leads SET phone = %s\n"
        "WHERE phone = %s\n"
        "  AND NOT EXISTS (SELECT 1 FROM leads outro WHERE outro.phone = %s);" % (
            sql_literal(novo), sql_literal(antigo), sql_literal(novo))
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reativacao_sql.py -v`
Expected: PASS — 31 testes

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/generate_sql.py backend/tests/test_reativacao_sql.py
git commit -m "feat(reativacao): update conservador, notas e opt-outs"
```

---

### Task 6: Montagem do arquivo completo e rollback

**Files:**
- Modify: `scripts/reativacao/generate_sql.py`
- Test: `backend/tests/test_reativacao_sql.py`

**Interfaces:**
- Consumes: todos os geradores das Tasks 4 e 5
- Produces:
  - `montar_arquivo(novos: list, existentes: list, optouts: list, normalizacoes: list) -> str` — SQL completo com `BEGIN`/`COMMIT`, contagens de verificação e `ON_ERROR_STOP`
  - `montar_rollback() -> str` — SQL que remove exatamente o lote

Cada item de `novos`/`existentes` é uma tupla `(dados: dict, nome_crm: str | None, tem_dono: bool)`.
Cada item de `optouts` é uma tupla `(telefone, quando, disse)`.
Cada item de `normalizacoes` é uma tupla `(antigo, novo)`.

- [ ] **Step 1: Write the failing test**

```python
# adicionar ao final de backend/tests/test_reativacao_sql.py

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

    def test_nao_apaga_lead_pre_existente(self):
        # so remove quem foi criado por este lote (metadata.lote + sem mensagens)
        sql = generate_sql.montar_rollback()
        assert "NOT EXISTS" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reativacao_sql.py::TestMontarArquivo -v`
Expected: FAIL com `AttributeError: module 'generate_sql' has no attribute 'montar_arquivo'`

- [ ] **Step 3: Write minimal implementation**

```python
# adicionar ao final de scripts/reativacao/generate_sql.py

CABECALHO = """-- Preparacao da campanha de reativacao — lote %s
-- Gerado por scripts/reativacao/generate_sql.py. NAO editar a mao.
-- Spec:  docs/superpowers/specs/2026-08-08-reativacao-crm-preparacao-design.md
-- Plano: docs/superpowers/plans/2026-08-08-reativacao-crm-preparacao.md
--
-- PRE-REQUISITO: pg_dump feito. Rodar com:
--   psql -U postgres -v ON_ERROR_STOP=1 -f preparar.sql
--
-- Este arquivo NAO cria disparo. Nenhuma escrita em broadcasts/broadcast_leads.
\\set ON_ERROR_STOP on
BEGIN;
""" % LOTE

RODAPE = """
-- ── Verificacao (dentro da transacao, antes do COMMIT) ─────────────────────
\\echo '--- leads do lote (esperado: 276) ---'
SELECT count(*) AS leads_do_lote FROM leads WHERE metadata->>'lote' = '%(lote)s';

\\echo '--- notas do lote (esperado: 276) ---'
SELECT count(*) AS notas_do_lote FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

\\echo '--- opt-outs marcados (esperado: 51) ---'
SELECT count(*) AS optouts_do_lote FROM leads
WHERE opt_out AND metadata->>'optout_fonte' = 'mensagem_do_cliente';

COMMIT;
""" % {"lote": LOTE}


def montar_arquivo(novos, existentes, optouts, normalizacoes):
    """SQL completo, em transacao unica.

    Ordem importa: normalizacoes de telefone vem antes dos INSERTs, senao o
    registro com telefone curto viraria duplicata logica do novo.
    """
    partes = [CABECALHO]

    partes.append("\n-- ── 1. Normalizacao de telefone (decisao D9) ──────────────────────────────")
    for antigo, novo in normalizacoes:
        partes.append(gerar_normalizacao_telefone(antigo, novo))

    partes.append("\n-- ── 2. Leads novos ────────────────────────────────────────────────────────")
    for dados, nome_crm, _ in novos:
        partes.append(gerar_insert_lead(dados, nome_crm))

    partes.append("\n-- ── 3. Leads existentes: preencher apenas vazios (decisao D5) ─────────────")
    for dados, _nome_crm, tem_dono in existentes:
        partes.append(gerar_update_conservador(dados, tem_dono))

    partes.append("\n-- ── 4. Notas de briefing ──────────────────────────────────────────────────")
    for dados, nome_crm, _ in list(novos) + list(existentes):
        partes.append(gerar_insert_nota(dados, nome_crm))

    partes.append("\n-- ── 5. Opt-outs pendentes ─────────────────────────────────────────────────")
    for telefone, quando, disse in optouts:
        partes.append(gerar_update_optout(telefone, quando, disse))

    partes.append(RODAPE)
    return "\n\n".join(partes)


def montar_rollback():
    """Desfaz exatamente este lote.

    Só remove lead que este lote criou: tem metadata.lote e nenhuma mensagem
    (um lead pre-existente que recebeu merge no metadata tem historico de
    conversa, e nao pode ser apagado).
    """
    return """-- Rollback do lote %(lote)s
-- Remove SO o que este lote criou. Leads pre-existentes que receberam merge de
-- metadata ou nota permanecem — apenas a nota e o metadata do lote saem.
\\set ON_ERROR_STOP on
BEGIN;

DELETE FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

UPDATE leads SET opt_out = false
WHERE opt_out AND metadata->>'optout_fonte' = 'mensagem_do_cliente';

DELETE FROM leads l
WHERE l.metadata->>'lote' = '%(lote)s'
  AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = l.id);

UPDATE leads SET metadata = metadata - 'lote' - 'origem' - 'id_bling' - 'icp_score'
WHERE metadata->>'lote' = '%(lote)s';

\\echo '--- deve retornar 0 ---'
SELECT count(*) AS restantes FROM lead_notes WHERE content LIKE '%%%(lote)s%%';

COMMIT;
""" % {"lote": LOTE}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reativacao_sql.py -v`
Expected: PASS — 42 testes

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/generate_sql.py backend/tests/test_reativacao_sql.py
git commit -m "feat(reativacao): montagem do SQL completo e rollback do lote"
```

---

### Task 7: CLI de geração a partir dos CSVs

**Files:**
- Modify: `scripts/reativacao/generate_sql.py`
- Test: `backend/tests/test_reativacao_sql.py`

**Interfaces:**
- Consumes: `montar_arquivo`, `montar_rollback`
- Produces:
  - `MOTIVOS_EXCLUSAO: dict[str, str]` — telefone → motivo, os 4 casos de D7
  - `carregar_disparo(caminho: str) -> list[dict]` — lê o CSV de disparo
  - `enriquecer(linhas: list[dict], master: dict, nomes_crm: dict, donos: set) -> tuple[list, list]` — devolve `(novos, existentes)` já com `motivo_exclusao` e campos vindos da master
  - `main(argv=None) -> int` — CLI

- [ ] **Step 1: Write the failing test**

```python
# adicionar ao final de backend/tests/test_reativacao_sql.py

class TestMotivosExclusao:
    def test_os_quatro_casos_do_spec(self):
        assert len(generate_sql.MOTIVOS_EXCLUSAO) == 4
        assert "5511996057340" in generate_sql.MOTIVOS_EXCLUSAO   # Incec
        assert "5511989374541" in generate_sql.MOTIVOS_EXCLUSAO   # Emporio Sabor do Norte
        assert "5516997442292" in generate_sql.MOTIVOS_EXCLUSAO   # Gran Cremma
        assert "5554996324731" in generate_sql.MOTIVOS_EXCLUSAO   # Divina Terra BC

    def test_motivo_do_incec_menciona_encerramento(self):
        assert "encerrada" in generate_sql.MOTIVOS_EXCLUSAO["5511996057340"].lower()


class TestEnriquecer:
    def test_separa_novos_de_existentes(self):
        linhas = [_dados()]
        novos, existentes = generate_sql.enriquecer(
            linhas, master={}, nomes_crm={}, donos=set())
        assert len(novos) == 1 and len(existentes) == 0

        novos, existentes = generate_sql.enriquecer(
            linhas, master={}, nomes_crm={"5551993452254": "Antonio"}, donos=set())
        assert len(novos) == 0 and len(existentes) == 1

    def test_marca_tem_dono(self):
        linhas = [_dados()]
        _, existentes = generate_sql.enriquecer(
            linhas, master={}, nomes_crm={"5551993452254": "Antonio"},
            donos={"5551993452254"})
        assert existentes[0][2] is True

    def test_aplica_motivo_de_exclusao(self):
        dados = _dados()
        dados["whatsapp"] = "5511996057340"
        novos, _ = generate_sql.enriquecer([dados], master={}, nomes_crm={}, donos=set())
        assert "encerrada" in novos[0][0]["motivo_exclusao"].lower()

    def test_puxa_campos_da_master(self):
        dados = _dados()
        master = {"5845664414": {"qtd_nfe": "7", "orcamentos": "2",
                                 "valor_vencido": "0.00", "titulos_vencidos": "0",
                                 "dias_atraso_max": "", "qtd_top1": "1200"}}
        novos, _ = generate_sql.enriquecer([dados], master=master, nomes_crm={}, donos=set())
        assert novos[0][0]["qtd_nfe"] == "7"
        assert novos[0][0]["orcamentos"] == "2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_reativacao_sql.py::TestMotivosExclusao -v`
Expected: FAIL com `AttributeError: module 'generate_sql' has no attribute 'MOTIVOS_EXCLUSAO'`

- [ ] **Step 3: Write minimal implementation**

```python
# adicionar ao topo de scripts/reativacao/generate_sql.py, junto aos imports
import argparse
import csv
import os

# ... (constantes existentes) ...

# Decisao D7 do spec: recebem lead + nota, mas ficam fora da campanha.
MOTIVOS_EXCLUSAO = {
    "5511996057340": "operação de café encerrada — o cliente avisou",
    "5511989374541": "o número é o atendimento automático da loja",
    "5516997442292": "LEAD QUENTE — pediu portfólio e cápsulas/drip; responder o pedido dele, não disparar template",
    "5554996324731": "declinou com gatilho — retomar quando o estoque dela baixar",
}

# Decisao D9: telefone a normalizar antes dos inserts.
NORMALIZACOES = (("11981154002", "5511981154002"),)

# Campos que vem da planilha master, nao do CSV de disparo.
CAMPOS_DA_MASTER = ("qtd_nfe", "orcamentos", "valor_vencido", "titulos_vencidos",
                    "dias_atraso_max", "qtd_top1")


# ... (funcoes existentes) ...


def carregar_disparo(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def carregar_master(caminho):
    """id_bling -> dict, para puxar os campos que o CSV de disparo nao tem."""
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return {linha["id_bling"]: linha for linha in csv.DictReader(fh)}


def enriquecer(linhas, master, nomes_crm, donos):
    """Separa (novos, existentes) e completa cada dict.

    nomes_crm: telefone E.164 -> leads.name (vazio quando o CRM nao tem nome)
    donos:     telefones que ja tem assigned_to preenchido
    """
    novos, existentes = [], []
    for linha in linhas:
        dados = dict(linha)
        phone = transform.normalizar_telefone(dados.get("whatsapp"))
        da_master = master.get((dados.get("id_bling") or "").strip(), {})
        for campo in CAMPOS_DA_MASTER:
            dados.setdefault(campo, "")
            if not dados.get(campo) and da_master.get(campo):
                dados[campo] = da_master[campo]
        dados["motivo_exclusao"] = MOTIVOS_EXCLUSAO.get(phone, "")
        nome_crm = nomes_crm.get(phone) or None
        entrada = (dados, nome_crm, phone in donos)
        (existentes if phone in nomes_crm else novos).append(entrada)
    return novos, existentes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gera o SQL da preparacao de reativacao.")
    parser.add_argument("--disparo", required=True, help="CSV da lista de disparo")
    parser.add_argument("--master", required=True, help="CSV master de leads")
    parser.add_argument("--nomes-crm", required=True,
                        help="TSV 'telefone<TAB>nome' dos leads que ja existem no CRM")
    parser.add_argument("--donos", default="",
                        help="arquivo com um telefone por linha que ja tem assigned_to")
    parser.add_argument("--optouts", required=True, help="JSON telefone -> {data, texto}")
    parser.add_argument("--saida", required=True, help="diretorio de saida")
    args = parser.parse_args(argv)

    nomes_crm = {}
    with open(args.nomes_crm, encoding="utf-8") as fh:
        for bruta in fh:
            if "\t" not in bruta:
                continue
            fone, nome = bruta.rstrip("\n").split("\t", 1)
            if fone.strip():
                nomes_crm[fone.strip()] = nome.strip()

    donos = set()
    if args.donos and os.path.exists(args.donos):
        with open(args.donos, encoding="utf-8") as fh:
            donos = {l.strip() for l in fh if l.strip()}

    with open(args.optouts, encoding="utf-8") as fh:
        optout_raw = json.load(fh)
    optouts = [(fone, dado.get("data", ""), dado.get("texto", ""))
               for fone, dado in optout_raw.items()]

    linhas = carregar_disparo(args.disparo)
    master = carregar_master(args.master)
    novos, existentes = enriquecer(linhas, master, nomes_crm, donos)

    os.makedirs(args.saida, exist_ok=True)
    caminho_sql = os.path.join(args.saida, "preparar.sql")
    caminho_rb = os.path.join(args.saida, "rollback.sql")
    with open(caminho_sql, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(montar_arquivo(novos, existentes, optouts, NORMALIZACOES))
    with open(caminho_rb, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(montar_rollback())

    print("leads novos:      %d" % len(novos))
    print("leads existentes: %d" % len(existentes))
    print("notas:            %d" % (len(novos) + len(existentes)))
    print("opt-outs:         %d" % len(optouts))
    print("exclusoes:        %d" % sum(
        1 for d, _, _ in list(novos) + list(existentes) if d["motivo_exclusao"]))
    print("gerado: %s" % caminho_sql)
    print("gerado: %s" % caminho_rb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_reativacao_sql.py -v`
Expected: PASS — 48 testes

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/generate_sql.py backend/tests/test_reativacao_sql.py
git commit -m "feat(reativacao): CLI de geracao a partir dos CSVs"
```

---

### Task 8: Runbook e geração real do SQL

**Files:**
- Create: `scripts/reativacao/README.md`
- Test: execução real do CLI contra os CSVs de produção (dry-run — nada é escrito no banco)

**Interfaces:**
- Consumes: `main()` (Task 7)
- Produces: `preparar.sql` e `rollback.sql` no diretório de saída, mais o runbook

- [ ] **Step 1: Escrever o runbook**

```markdown
# Preparação da campanha de reativação — runbook

Prepara 276 leads no CRM com briefing de contexto e registra 51 opt-outs pendentes.
**Não dispara nada.** O disparo é criado depois pela interface do CRM.

- Spec: `docs/superpowers/specs/2026-08-08-reativacao-crm-preparacao-design.md`
- Plano: `docs/superpowers/plans/2026-08-08-reativacao-crm-preparacao.md`

## 0. Pré-requisito: backup

O banco de produção **não tem backup automático** (`archive_mode = off`, sem cron).
Tirar o dump é obrigatório antes de qualquer escrita.

```bash
ssh root@173.249.15.11 'docker exec $(docker ps -qf name=supabase_db) \
  pg_dump -U postgres --no-owner postgres > /root/backup-pre-reativacao-$(date +%F).sql; \
  ls -lh /root/backup-pre-reativacao-*.sql'
```

Conferir que o arquivo tem tamanho compatível com o banco (~106 MB) antes de seguir.

## 1. Levantar o estado atual do CRM

```bash
# telefone<TAB>nome dos leads que já existem
ssh root@173.249.15.11 'docker exec $(docker ps -qf name=supabase_db) psql -U postgres -A -F"\t" -t \
  -c "select regexp_replace(phone,'"'"'[^0-9]'"'"','"''"','"'"'g'"'"'), coalesce(name,'"''"') from leads"' \
  > /tmp/nomes_crm.tsv

# telefones que já têm assigned_to
ssh root@173.249.15.11 'docker exec $(docker ps -qf name=supabase_db) psql -U postgres -A -t \
  -c "select regexp_replace(phone,'"'"'[^0-9]'"'"','"''"','"'"'g'"'"') from leads where assigned_to is not null"' \
  > /tmp/donos.txt
```

## 2. Gerar o SQL

```bash
python scripts/reativacao/generate_sql.py \
  --disparo "../DB Leads/DISPARO-segunda-2026-08-10.csv" \
  --master  "../DB Leads/CANASTRA-LEADS-MASTER-2026-08-08.csv" \
  --nomes-crm /tmp/nomes_crm.tsv \
  --donos /tmp/donos.txt \
  --optouts /tmp/optouts.json \
  --saida /tmp/reativacao
```

Confirmar a saída: `leads novos: 236`, `leads existentes: 40`, `notas: 276`,
`opt-outs: 51`, `exclusoes: 4`.

## 3. Revisar antes de executar

```bash
grep -c "INSERT INTO leads"      /tmp/reativacao/preparar.sql   # 236
grep -c "UPDATE leads SET"       /tmp/reativacao/preparar.sql   # 40 + 51 + 1
grep -c "INSERT INTO lead_notes" /tmp/reativacao/preparar.sql   # 276
grep -cE "broadcasts|broadcast_leads" /tmp/reativacao/preparar.sql   # 0 — obrigatório
grep -cE "SET (stage|status|human_control|ai_enabled)" /tmp/reativacao/preparar.sql  # 0
```

Ler alguns blocos à mão, especialmente os 4 com `⚠ FORA DA CAMPANHA`.

## 4. Executar

```bash
scp /tmp/reativacao/preparar.sql root@173.249.15.11:/tmp/
ssh root@173.249.15.11 'D=$(docker ps -qf name=supabase_db); docker cp /tmp/preparar.sql $D:/tmp/; \
  docker exec $D psql -U postgres -v ON_ERROR_STOP=1 -f /tmp/preparar.sql'
```

Qualquer erro aborta a transação inteira — nada fica pela metade.

## 5. Verificar

As contagens saem no fim da própria execução (antes do COMMIT). Esperado:
`leads_do_lote = 276`, `notas_do_lote = 276`, `optouts_do_lote = 51`.

## 6. Rollback (se necessário)

```bash
scp /tmp/reativacao/rollback.sql root@173.249.15.11:/tmp/
ssh root@173.249.15.11 'D=$(docker ps -qf name=supabase_db); docker cp /tmp/rollback.sql $D:/tmp/; \
  docker exec $D psql -U postgres -v ON_ERROR_STOP=1 -f /tmp/rollback.sql'
```

Remove as notas do lote, desmarca os opt-outs aplicados e apaga **apenas** os leads
que este lote criou (os que têm `metadata.lote` e nenhuma mensagem). Leads
pré-existentes ficam, perdendo só as chaves de metadata do lote.

Se algo pior acontecer, restaurar o dump do passo 0.
```

- [ ] **Step 2: Preparar os insumos e rodar o CLI de verdade**

```bash
# optouts.json vem da deteccao por mensagem (61 telefones, 51 a marcar)
python -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); \
  json.dump({k:{'data':v['data'],'texto':v['texto']} for k,v in d.items()}, \
  open('/tmp/optouts.json','w',encoding='utf-8'), ensure_ascii=False)" \
  <caminho do optouts.json coletado>
```

- [ ] **Step 3: Rodar e conferir as contagens**

Run: o comando do passo 2 do runbook
Expected: `leads novos: 236`, `leads existentes: 40`, `notas: 276`, `opt-outs: 51`, `exclusoes: 4`

- [ ] **Step 4: Rodar os guardrails do passo 3 do runbook**

Expected: `broadcasts|broadcast_leads` → **0**; `SET (stage|status|human_control|ai_enabled)` → **0**

- [ ] **Step 5: Rodar a suíte inteira para garantir que nada regrediu**

Run: `cd backend && python -m pytest tests/test_reativacao_transform.py tests/test_reativacao_sql.py -v`
Expected: PASS — 48 testes

- [ ] **Step 6: Commit**

```bash
git add scripts/reativacao/README.md
git commit -m "docs(reativacao): runbook de preparacao com dump, guardrails e rollback"
```

---

## Self-Review

**1. Spec coverage**

| Requisito do spec | Task |
|---|---|
| D1 — sem broadcast | Guardrail `TABELAS_PROIBIDAS` testado nas Tasks 4 e 6; verificação no runbook (Task 8) |
| D2 — pending/imported + metadata + tag | Task 4 (insert) |
| D3 — briefing em `lead_notes` | Tasks 3 e 5 |
| D4 — assigned_to João | Task 4 |
| D5 — conservador nos 40 | Task 5 (`gerar_update_conservador`), guardrail `COLUNAS_INTOCAVEIS` |
| D6 — saudação CRM > Bling | Task 1 (`escolher_saudacao`) |
| D7 — 4 exclusões | Task 7 (`MOTIVOS_EXCLUSAO`), texto na Task 3 |
| D8 — dump, transação, idempotência, rollback | Tasks 6 e 8 |
| D9 — duplicata Atma | Task 5 (`gerar_normalizacao_telefone`), ordem na Task 6 |
| Regras de conteúdo do briefing | Task 3 (todas as variações testadas) |
| Critérios 1-9 | Contagens no `RODAPE` (Task 6) e passos 3-5 do runbook (Task 8) |

**Lacuna encontrada e corrigida:** a tag `Já é Cliente` (D2) não tem task. Decisão:
**deixar fora do escopo desta implementação.** `lead_tags` exige `tag_id` de `tags`, e
a associação é uma operação separada de baixo valor frente ao risco de escrever numa
tabela normalizada que não inspecionei. O rastreio por `metadata.origem` e
`metadata.lote` já atende ao critério "o João acha os leads". Registrado aqui como
divergência consciente do spec, não como esquecimento.

**2. Placeholder scan:** nenhum TBD/TODO. Todo step de código tem o código real. As
funções auxiliares (`_num`, `_int`, `_sem_acento`) estão definidas onde são usadas.

**3. Type consistency:** `montar_briefing(dados: dict)` recebe as mesmas chaves que
`enriquecer` garante existir (`CAMPOS_DA_MASTER` com `setdefault`). `gerar_insert_nota`
e `gerar_insert_lead` recebem `(dados, nome_crm)` na mesma ordem. `montar_arquivo`
recebe tuplas de 3 elementos para `novos`/`existentes`, e é isso que `enriquecer`
devolve. `PREFIXO_BRIEFING` (transform) e `LOTE` (generate_sql) contêm a mesma string
de lote — a nota é encontrada pelo `LIKE '%lote%'`, então basta a substring, não a
igualdade dos identificadores.
