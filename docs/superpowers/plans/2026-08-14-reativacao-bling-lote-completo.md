# Lote completo do Bling + aviso de inadimplentes — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gerar o SQL que cria no CRM os 1.218 leads do Bling que faltam — num funil dedicado com 8 etapas por recência, com tags, deals e briefing — e fazer o modal de disparo avisar quando houver inadimplentes entre os leads selecionados.

**Architecture:** Duas partes independentes. A Parte 1 é um gerador de SQL em Python (`scripts/reativacao/lote_completo.py`) que reaproveita a lógica pura já testada de `transform.py` e produz `preparar.sql` + `rollback.sql` para aplicação manual via `psql`; não executa nada contra o banco. A Parte 2 é frontend puro: uma função pura, um componente de banner e um guard de API, sem rota nova — o modal já recebe `lead_tags` e `metadata` de cada lead.

**Tech Stack:** Python 3.11 + pytest (Parte 1); Next.js App Router, TypeScript, vitest (Parte 2). Nenhuma dependência nova.

**Spec:** `docs/superpowers/specs/2026-08-14-reativacao-bling-lote-completo-design.md`

---

## Contexto que o executor precisa saber

**Não execute SQL contra o banco.** O artefato desta entrega é o arquivo `.sql`. Ele é revisado, depois aplicado por um humano via `psql` seguindo o runbook (Task 12). O banco de produção não tem backup automático.

**Duas normalizações de telefone convivem e isso é proposital:**
- `transform.normalizar_telefone()` — preserva 12 dígitos como estão (existe para não corromper números internacionais). Usada pelo lote de 10/08.
- `transform.normalizar_telefone_canonico()` — Task 1, nova — injeta o 9º dígito **só em celular brasileiro** (assinante começando em 6-9), respeita DDI explícito (`+` ou `00`) e recusa DDD inexistente. **É a que este lote usa**, porque a forma de 13 dígitos é a que o webhook do WhatsApp grava; usar a antiga criaria lead duplicado quando a pessoa respondesse. Dos 338 números de 12 dígitos, 94 são celulares antigos que ganham o 9 e **244 são fixos que ficam intactos**.

  **Ela diverge de `backend/app/leads/service.py::normalize_phone` e de `frontend/src/lib/phone.ts::normalizePhoneBR` de propósito.** As duas injetam o 9 em qualquer número de 12 dígitos começando com 55, o que transforma o fixo `(68) 3302-0386` no celular `68 9 3302-0386` — número de outra pessoa. Como este lote alimenta disparo de template, reproduzir esse defeito mandaria marketing para estranhos. Corrigir as duas funções originais afeta a base inteira e é trabalho separado.

**O lote de 10/08 (`generate_sql.py`) está pendente de aplicação e não pode quebrar.** Ele tem 92 testes em `backend/tests/test_reativacao_sql.py` e 51 em `test_reativacao_transform.py`. Por isso este lote ganha módulo próprio em vez de parametrizar o existente; as únicas mudanças em `transform.py` são aditivas (Tasks 1 e 2).

**Como rodar os testes:**
- Python: `cd backend && python -m pytest tests/test_reativacao_lote_completo.py -v`
- Frontend: `cd frontend && npm test` (vitest) e `npm run type-check`

**Entrada de dados:** `leads-bling-completo-2026-08-08-br (1).csv`, na raiz do repo. Separador `;`, encoding `utf-8-sig`. 2.771 linhas de dados.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `scripts/reativacao/transform.py` (modificar) | +`normalizar_telefone_canonico`, briefing com prefixo parametrizável e linha ICP opcional, aliases públicos dos parsers |
| `scripts/reativacao/lote_completo.py` (criar) | Constantes do lote, leitura/dedup do CSV, geração de cada bloco SQL, CLI |
| `backend/tests/test_reativacao_lote_completo.py` (criar) | Testes do gerador |
| `backend/tests/test_reativacao_transform.py` (modificar) | Testes das funções novas de `transform.py` |
| `scripts/reativacao/README-lote-completo.md` (criar) | Runbook de aplicação |
| `frontend/src/lib/constants.ts` (modificar) | `TAG_DEBITO_VENCIDO_ID` |
| `frontend/src/lib/inadimplentes.ts` (criar) | `findInadimplentes` — lógica pura |
| `frontend/src/lib/inadimplentes.test.ts` (criar) | Testes da função pura |
| `frontend/src/app/api/tags/[id]/route.ts` (modificar) | 409 em PUT/DELETE da tag fixa |
| `frontend/src/components/campaigns/inadimplentes-warning.tsx` (criar) | Banner |
| `frontend/src/components/campaigns/create-broadcast-modal.tsx` (modificar) | `metadata` no tipo local, banner nos passos 3 e 6 |

---

# PARTE 1 — Geração do SQL

### Task 1: Normalização canônica de telefone

**Files:**
- Modify: `scripts/reativacao/transform.py` (adicionar após `normalizar_telefone`, linha ~36)
- Test: `backend/tests/test_reativacao_transform.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicione ao fim de `backend/tests/test_reativacao_transform.py`:

```python
class TestNormalizarTelefoneCanonico:
    def test_br_doze_digitos_recebe_nono_digito(self):
        assert transform.normalizar_telefone_canonico("554342453258") == "5543942453258"

    def test_treze_digitos_permanece(self):
        assert transform.normalizar_telefone_canonico("5534991461669") == "5534991461669"

    def test_fixo_nao_recebe_nono_digito(self):
        # (34) 3215-1234 e FIXO (assinante comeca em 3). Injetar o 9 aqui
        # fabricaria 34 9 3215-1234, um celular que pode ser de outra pessoa.
        assert transform.normalizar_telefone_canonico("3432151234") == "553432151234"
        assert transform.normalizar_telefone_canonico("556833020386") == "556833020386"

    def test_celular_antigo_de_dez_digitos_recebe_o_nono(self):
        # (34) 9146-1669 e celular antigo (assinante comeca em 9).
        assert transform.normalizar_telefone_canonico("3491461669") == "5534991461669"

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
        # A antiga preserva 12 digitos sempre; a canonica injeta o 9 so em movel.
        assert transform.normalizar_telefone("5534914616690"[:12]) == "553491461669"
        assert transform.normalizar_telefone_canonico("553491461669") == "5534991461669"
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_transform.py::TestNormalizarTelefoneCanonico -v
```
Esperado: FAIL com `AttributeError: module 'transform' has no attribute 'normalizar_telefone_canonico'`.

- [ ] **Step 3: Implementar**

Em `scripts/reativacao/transform.py`, logo após `normalizar_telefone`:

```python
def normalizar_telefone_canonico(valor):
    """E.164 sem '+' com o 9o digito injetado APENAS em celular brasileiro.

    Converge com backend/app/leads/service.py::normalize_phone para celulares —
    a forma que o webhook do WhatsApp grava em leads.phone — e diverge dele de
    proposito em fixos. Nao cobre BSUID nem telefone dobrado, que sao entradas
    do webhook, nunca do CSV do Bling.

    Por que a forma de 13 digitos importa: gravar um celular com 12 digitos cria
    duplicata logica — quando a pessoa responder, o webhook grava o registro de
    13 digitos e a conversa fica partida entre dois leads (leads.phone e UNIQUE
    pela string exata).

    Por que fixo NAO recebe o 9: no plano de numeracao brasileiro o assinante
    movel comeca em 6-9 e o fixo em 2-5. Injetar o 9 em (34) 3215-1234 produz
    34 9 3215-1234 — um celular valido que provavelmente pertence a OUTRA
    pessoa. Como este lote alimenta disparo de template, isso mandaria
    marketing para estranhos. Sao 244 fixos nos 1.218 leads do lote.
    normalize_phone tem esse defeito; aqui ele nao e reproduzido.

    Internacionais so passam intactos se ja vierem com 12+ digitos: um numero
    estrangeiro de 10 ou 11 digitos e indistinguivel de um BR sem DDI e ganha
    o prefixo 55. O CSV do Bling entrega os 12 internacionais ja com DDI.
    """
    digitos = re.sub(r"\D", "", valor or "")
    if not digitos:
        return ""
    if digitos.startswith("0"):
        digitos = digitos[1:]
    if len(digitos) in (10, 11):
        digitos = "55" + digitos
    if len(digitos) not in (12, 13):
        return ""
    if len(digitos) == 12 and digitos.startswith("55") and digitos[4] in "6789":
        digitos = digitos[:4] + "9" + digitos[4:]
    return digitos
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd backend && python -m pytest tests/test_reativacao_transform.py -v
```
Esperado: PASS em tudo — os 51 testes antigos **e** os 9 novos.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/transform.py backend/tests/test_reativacao_transform.py
git commit -m "feat(reativacao): normalizacao canonica de telefone com 9o digito"
```

---

### Task 2: Briefing com prefixo parametrizável e linha ICP opcional

**Files:**
- Modify: `scripts/reativacao/transform.py:160` (`montar_briefing`) e fim do arquivo
- Test: `backend/tests/test_reativacao_transform.py`

**Por quê:** `PREFIXO_BRIEFING` está fixo no lote de 10/08, e a linha `ICP` renderiza `ICP ? (?)` quando o score não existe — este lote não tem score (vinha da planilha master enriquecida com BrasilAPI, que não é entrada aqui).

- [ ] **Step 1: Escrever os testes que falham**

Adicione ao fim de `backend/tests/test_reativacao_transform.py`:

```python
class TestBriefingParametrizavel:
    def _dados_minimos(self):
        return {
            "total_gasto": "0", "cpf_cnpj": "", "cidade": "Uberlandia", "uf": "MG",
            "id_bling": "999", "qtd_nfe": "0", "orcamentos": "0", "vendedor": "",
        }

    def test_prefixo_customizado_aparece(self):
        texto = transform.montar_briefing(self._dados_minimos(), prefixo="LOTE XPTO")
        assert "LOTE XPTO" in texto
        assert transform.PREFIXO_BRIEFING not in texto

    def test_prefixo_padrao_continua_o_do_lote_anterior(self):
        texto = transform.montar_briefing(self._dados_minimos())
        assert transform.PREFIXO_BRIEFING in texto

    def test_sem_icp_score_a_linha_vira_so_id_bling(self):
        texto = transform.montar_briefing(self._dados_minimos())
        assert "id_bling 999" in texto
        assert "ICP" not in texto

    def test_com_icp_score_a_linha_completa_permanece(self):
        dados = self._dados_minimos()
        dados["icp_score"] = "55"
        dados["icp_faixa"] = "C - medio"
        texto = transform.montar_briefing(dados)
        assert "ICP 55 (C - medio) · id_bling 999" in texto

    def test_parsers_publicos_expostos(self):
        assert transform.parse_numero("1.234,56") == 1234.56
        assert transform.parse_inteiro("42") == 42
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_transform.py::TestBriefingParametrizavel -v
```
Esperado: FAIL — `montar_briefing() got an unexpected keyword argument 'prefixo'`.

- [ ] **Step 3: Implementar**

Em `scripts/reativacao/transform.py`, troque a assinatura e as duas linhas indicadas:

```python
def montar_briefing(dados, prefixo=None):
    """Monta o texto da nota que o vendedor le no card do lead.

    `prefixo` permite reuso entre lotes (o de 10/08 usa o default). Regras em
    docs/superpowers/specs/2026-08-08-reativacao-crm-preparacao-design.md e
    docs/superpowers/specs/2026-08-14-reativacao-bling-lote-completo-design.md
    """
    linhas = []
```

Troque `linhas.append(PREFIXO_BRIEFING)` por:

```python
    linhas.append(prefixo or PREFIXO_BRIEFING)
```

Troque o bloco final da linha ICP por:

```python
    icp = (dados.get("icp_score") or "").strip()
    if icp:
        linhas.append("ICP %s (%s) · id_bling %s" % (
            icp,
            dados.get("icp_faixa") or "?",
            dados.get("id_bling") or "?",
        ))
    else:
        # Lotes sem enriquecimento de ICP (ex.: reativacao_bling_2026-08-14)
        # nao devem renderizar "ICP ? (?)".
        linhas.append("id_bling %s" % (dados.get("id_bling") or "?"))
```

E ao fim do arquivo, os aliases públicos:

```python
# Aliases publicos dos parsers: outros modulos do pacote (lote_completo.py)
# precisam deles, e depender de nome com underscore atravessa fronteira de API.
parse_numero = _num
parse_inteiro = _int
```

- [ ] **Step 4: Rodar a suíte inteira**

```bash
cd backend && python -m pytest tests/test_reativacao_transform.py tests/test_reativacao_sql.py -v
```
Esperado: PASS em tudo. Os 92 testes de `test_reativacao_sql.py` usam dados com `icp_score="55"`, então a linha ICP completa continua igual para o lote de 10/08.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/transform.py backend/tests/test_reativacao_transform.py
git commit -m "feat(reativacao): briefing com prefixo parametrizavel e ICP opcional"
```

---

### Task 3: Constantes e seleção da coorte

**Files:**
- Create: `scripts/reativacao/lote_completo.py`
- Test: `backend/tests/test_reativacao_lote_completo.py`

- [ ] **Step 1: Escrever os testes que falham**

Crie `backend/tests/test_reativacao_lote_completo.py`:

```python
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

    def test_crm_e_comparado_normalizado(self):
        # O CRM guarda 12 digitos; a coorte normaliza para 13. Tem que casar.
        linhas = [_linha(id_bling="1", whatsapp="554342453258")]
        resultado = lote_completo.selecionar_faltantes(linhas, {"5543942453258"})
        assert resultado.novos == []
        assert resultado.ja_no_crm == 1
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py -v
```
Esperado: FAIL com `ModuleNotFoundError: No module named 'lote_completo'`.

- [ ] **Step 3: Implementar**

Crie `scripts/reativacao/lote_completo.py`:

```python
# scripts/reativacao/lote_completo.py
"""Gera o SQL do lote completo do Bling. Nao executa nada.

O artefato revisavel e o proprio .sql, aplicado por um humano via psql depois
do pg_dump. Ver docs/superpowers/plans/2026-08-14-reativacao-bling-lote-completo.md

Difere de generate_sql.py (lote de 10/08) em tres pontos: usa
transform.normalizar_telefone_canonico (injeta o 9o digito), cria funil +
etapas + deals, e nao tem curadoria manual de saudacao nem score de ICP.
"""
import csv
import json
import re
from collections import namedtuple

import transform

LOTE = "reativacao_bling_2026-08-14"
ORIGEM = "reativacao_bling"
AUTOR_NOTA = "Sistema — Reativação Bling 08/26"
PREFIXO_BRIEFING = "REATIVAÇÃO BLING 14/08/2026 — lote reativacao_bling_2026-08-14"

# UUIDs hardcoded: deixam os INSERTs idempotentes e dao ao rollback um alvo
# preciso. O de TAG_DEBITO_VENCIDO e referenciado pelo frontend
# (frontend/src/lib/constants.ts) — mudar aqui exige mudar la.
PIPELINE_ID = "b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09"
PIPELINE_NOME = "Reativação Bling"

# (key, label, cor, uuid) — a ordem da tupla e a ordem no Kanban.
ETAPAS = (
    ("ativo_0_3m",         "Ativo (0-3m)",        "#5aad65", "a1c4e7b2-5d38-4f61-9a02-7e5b3c8d1f40"),
    ("inativo_3_6m",       "Inativo 3-6m",        "#d4b84a", "b2d5f8c3-6e49-4a72-8b13-6f4c2d9e0a51"),
    ("inativo_6_12m",      "Inativo 6-12m",       "#d4a04a", "c3e6a9d4-7f50-4b83-9c24-5a3d1e8f2b62"),
    ("inativo_12_24m",     "Inativo 12-24m",      "#e07a7a", "d4f7b0e5-8a61-4c94-8d35-4b2e0f7a3c73"),
    ("inativo_24_36m",     "Inativo 24-36m",      "#c46a6a", "e5a8c1f6-9b72-4d05-9e46-3c1f0a6b4d84"),
    ("inativo_36m_mais",   "Inativo 36m+",        "#9ca3af", "f6b9d2a7-0c83-4e16-8f57-2d0a1b5c6e95"),
    ("pedido_sem_faturar", "Pedido sem faturar",  "#9b7abf", "07cae3b8-1d94-4f27-9068-1e0b2c4d7fa6"),
    ("lead_sem_compra",    "Nunca comprou",       "#b0aca6", "18dbf4c9-2ea5-4038-8179-0f1c3d5e8ab7"),
)

ETAPA_POR_SEGMENTO = {
    "ativo_0_3m": "ativo_0_3m",
    "inativo_3_6m": "inativo_3_6m",
    "inativo_6_12m": "inativo_6_12m",
    "inativo_12_24m": "inativo_12_24m",
    "inativo_24_36m": "inativo_24_36m",
    "inativo_36m+": "inativo_36m_mais",
    "pedido_sem_faturar": "pedido_sem_faturar",
    "lead_sem_compra": "lead_sem_compra",
}

TAG_LOTE_ID = "7c4e2a19-3f68-4b02-9d5a-1e8f6c0b3d47"
TAG_LOTE_NOME = "Reativação Bling 08/26"
TAG_DEBITO_ID = "3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210"
TAG_DEBITO_NOME = "Débito vencido"
TAG_B2B_ID = "2249642b-e4f2-420e-8482-d07b325a28c8"  # ja existe no banco
TAG_ECOMMERCE_ID = "5e2f7a83-4b91-4c60-a8d2-9f3e1b0c7d54"
TAG_SEM_VENDEDOR_ID = "6f3a8b94-5c02-4d71-b9e3-0a4f2c1d8e65"

# (uuid, nome, cor) das tags que este lote cria. B2B fica fora: ja existe.
TAGS_A_CRIAR = (
    (TAG_LOTE_ID, TAG_LOTE_NOME, "#7C3AED"),
    (TAG_DEBITO_ID, TAG_DEBITO_NOME, "#DC2626"),
    (TAG_ECOMMERCE_ID, "E-commerce", "#0D9488"),
    (TAG_SEM_VENDEDOR_ID, "Sem vendedor", "#6B7280"),
)

PLATAFORMAS_ECOMMERCE = ("TRAY TECNOLOGIA EM ECOMMERCE LTDA", "WooCommerce", "Licitação")

# Guardrail: o SQL gerado nunca pode tocar o disparo.
TABELAS_PROIBIDAS = ("broadcasts", "broadcast_leads")

Coorte = namedtuple("Coorte", "novos ja_no_crm sem_telefone duplicados_no_csv")


def sql_literal(valor):
    """Escapa para literal SQL; vazio/None viram NULL."""
    if valor is None:
        return "NULL"
    texto = str(valor).strip()
    if not texto:
        return "NULL"
    return "'" + texto.replace("'", "''") + "'"


def etapa_de(linha):
    """Key da etapa a partir do segmento_reativacao do Bling."""
    segmento = (linha.get("segmento_reativacao") or "").strip()
    if segmento not in ETAPA_POR_SEGMENTO:
        raise ValueError(
            "segmento desconhecido no CSV: %r — o funil tem 8 etapas fixas e um "
            "segmento novo faria o lead sumir silenciosamente" % segmento
        )
    return ETAPA_POR_SEGMENTO[segmento]


def perfil_comercial(linha):
    """B2B | E-commerce | Sem vendedor — vira tag.

    IDs numericos no campo vendedor sao vendedores humanos cujo nome nao foi
    resolvido na extracao do Bling, entao contam como B2B.
    """
    vendedor = (linha.get("vendedor") or "").strip()
    if vendedor in PLATAFORMAS_ECOMMERCE:
        return "E-commerce"
    if not vendedor:
        return "Sem vendedor"
    return "B2B"


def telefone_da_linha(linha):
    """Primeiro telefone utilizavel, na forma canonica."""
    for campo in ("whatsapp", "celular", "telefone"):
        fone = transform.normalizar_telefone_canonico(linha.get(campo))
        if fone:
            return fone
    return ""


def selecionar_faltantes(linhas, telefones_crm):
    """Divide o CSV em: a criar, ja no CRM, sem telefone, duplicados.

    `telefones_crm` deve chegar JA normalizado pela forma canonica — quem
    carrega o arquivo do banco (carregar_telefones_crm) faz isso.
    """
    novos, vistos = [], set()
    ja_no_crm = sem_telefone = duplicados = 0
    for linha in linhas:
        fone = telefone_da_linha(linha)
        if not fone:
            sem_telefone += 1
            continue
        if fone in telefones_crm:
            ja_no_crm += 1
            continue
        if fone in vistos:
            duplicados += 1
            continue
        vistos.add(fone)
        enriquecida = dict(linha)
        enriquecida["_phone"] = fone
        novos.append(enriquecida)
    return Coorte(novos, ja_no_crm, sem_telefone, duplicados)


def carregar_csv(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def carregar_telefones_crm(caminho):
    """Lê o dump de telefones do CRM (uma coluna por linha) já normalizado.

    Aborta em arquivo vazio: tratar "CRM vazio" como estado normal faria o
    script criar 1.218 leads duplicados sobre uma base que ja os tem.
    """
    with open(caminho, encoding="utf-8") as fh:
        fones = {transform.normalizar_telefone_canonico(l) for l in fh if l.strip()}
    fones.discard("")
    if not fones:
        raise ValueError(
            "telefones_crm vazio: %s — o CRM tem 2.339 leads, um arquivo vazio "
            "significa extracao quebrada, nao base vazia" % caminho
        )
    return fones
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py -v
```
Esperado: PASS nos 12 testes.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/lote_completo.py backend/tests/test_reativacao_lote_completo.py
git commit -m "feat(reativacao): constantes e selecao da coorte do lote completo"
```

---

### Task 4: SQL do funil e das 8 etapas

**Files:**
- Modify: `scripts/reativacao/lote_completo.py`
- Test: `backend/tests/test_reativacao_lote_completo.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
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
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py::TestSqlFunil -v
```
Esperado: FAIL — `module 'lote_completo' has no attribute 'gerar_pipeline_e_etapas'`.

- [ ] **Step 3: Implementar**

Adicione a `lote_completo.py`:

```python
def gerar_pipeline_e_etapas():
    """Funil + 8 etapas, idempotentes pelo UUID fixo.

    owner_user_id NULL e is_universal false seguem o padrao dos funis da
    Valeria: visiveis para todos, sem dono designado (decisao D3 do spec —
    numero, template e dono sao decididos quando a campanha for montada).
    """
    partes = [
        "-- Funil do lote e suas etapas",
        "INSERT INTO pipelines (id, name, order_index, owner_user_id, is_universal)",
        "VALUES (%s, %s, 99, NULL, false)" % (
            sql_literal(PIPELINE_ID), sql_literal(PIPELINE_NOME)),
        "ON CONFLICT (id) DO NOTHING;",
        "",
    ]
    for indice, (key, label, cor, uuid_) in enumerate(ETAPAS):
        partes.append(
            "INSERT INTO pipeline_stages (id, pipeline_id, label, key, dot_color, "
            "order_index, is_protected) VALUES (%s, %s, %s, %s, %s, %d, false) "
            "ON CONFLICT (id) DO NOTHING;" % (
                sql_literal(uuid_), sql_literal(PIPELINE_ID), sql_literal(label),
                sql_literal(key), sql_literal(cor), indice)
        )
    partes.append("")
    return "\n".join(partes)
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py -v
```
Esperado: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/lote_completo.py backend/tests/test_reativacao_lote_completo.py
git commit -m "feat(reativacao): SQL do funil e das 8 etapas"
```

---

### Task 5: SQL dos leads

**Files:**
- Modify: `scripts/reativacao/lote_completo.py`
- Test: `backend/tests/test_reativacao_lote_completo.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
class TestSqlLead:
    def test_insere_com_telefone_canonico(self):
        linha = _linha(whatsapp="554342453258")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert "'5543942453258'" in sql
        assert "ON CONFLICT (phone) DO NOTHING" in sql

    def test_nome_vem_limpo_de_sufixo_empresarial(self):
        linha = _linha(nome="CAFE TESTE LTDA")
        linha["_phone"] = lote_completo.telefone_da_linha(linha)
        sql = lote_completo.gerar_insert_lead(linha)
        assert "'Cafe Teste'" in sql

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
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py::TestSqlLead -v
```
Esperado: FAIL — `no attribute 'gerar_insert_lead'`.

- [ ] **Step 3: Implementar**

```python
def metadata_do_lead(linha):
    """Chaves de rastreio + os numeros do debito que o banner da UI exibe.

    origem+lote juntas sao o que o rollback usa; criado_por_lote marca quem
    este lote CRIOU (distinto de quem ele apenas tocou).
    """
    dados = {
        "origem": ORIGEM,
        "lote": LOTE,
        "criado_por_lote": LOTE,
        "id_bling": (linha.get("id_bling") or "").strip(),
        "segmento": etapa_de(linha),
        "vendedor_anterior": (linha.get("vendedor") or "").strip(),
        "total_gasto": transform.parse_numero(linha.get("total_gasto")),
        "ultima_compra": (linha.get("ultima_compra") or "").strip(),
        "whatsapp_tipo": (linha.get("whatsapp_tipo") or "").strip(),
        "phone_raw": (linha.get("whatsapp") or "").strip(),
    }
    if transform.parse_numero(linha.get("valor_vencido")) > 0:
        dados["valor_vencido"] = transform.parse_numero(linha.get("valor_vencido"))
        dados["titulos_vencidos"] = transform.parse_inteiro(linha.get("titulos_vencidos"))
        dados["dias_atraso_max"] = transform.parse_inteiro(linha.get("dias_atraso_max"))
    return dados


def nome_do_lead(linha):
    """leads.name e o que o cliente le como {{1}} no template do WhatsApp.

    Este lote nao tem coluna 'saudacao' curada a mao (o de 10/08 tinha, para
    276 linhas); escolher_saudacao limpa codigo/CNPJ do inicio e sufixos
    empresariais do nome legal do Bling.
    """
    return transform.escolher_saudacao(None, linha.get("nome"))


def gerar_insert_lead(linha):
    """INSERT idempotente de um lead novo.

    ai_enabled entra como literal booleano, nunca via sql_literal (que
    renderizaria a STRING 'False'): leads.ai_enabled e NOT NULL DEFAULT TRUE, e
    o motor de automacao seleciona por "ai_enabled = true AND stage = ...".

    assigned_to fica de fora (decisao D3): sem dono ate a campanha ser montada.
    """
    metadata = json.dumps(metadata_do_lead(linha), ensure_ascii=False, sort_keys=True)
    return (
        "INSERT INTO leads (phone, name, company, razao_social, nome_fantasia, "
        "cnpj, email, endereco, telefone_comercial, stage, status, channel, "
        "ai_enabled, opt_out, metadata) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, 'pending', 'imported', 'manual', false, false, %s::jsonb) "
        "ON CONFLICT (phone) DO NOTHING;" % (
            sql_literal(linha["_phone"]),
            sql_literal(nome_do_lead(linha)),
            sql_literal(linha.get("nome")),
            sql_literal(linha.get("razao_social") or linha.get("nome")),
            sql_literal(linha.get("fantasia")),  # coluna do Bling e "fantasia"
            sql_literal(re.sub(r"\D", "", linha.get("cpf_cnpj") or "")),
            sql_literal(linha.get("email")),
            sql_literal(linha.get("endereco_entrega") or linha.get("logradouro")),
            sql_literal(linha.get("telefone")),
            sql_literal(metadata),
        )
    )
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py -v
```
Esperado: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/lote_completo.py backend/tests/test_reativacao_lote_completo.py
git commit -m "feat(reativacao): SQL de insercao dos leads do lote completo"
```

---

### Task 6: SQL das notas de briefing

**Files:**
- Modify: `scripts/reativacao/lote_completo.py`
- Test: `backend/tests/test_reativacao_lote_completo.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
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
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py::TestSqlNota -v
```
Esperado: FAIL — `no attribute 'gerar_insert_nota'`.

- [ ] **Step 3: Implementar**

```python
def dados_do_briefing(linha):
    """Adapta os nomes de coluna do CSV cru para o que montar_briefing espera."""
    dados = dict(linha)
    dados["produto_para_citar"] = (linha.get("produto_top1") or "").strip()
    return dados


def gerar_insert_nota(linha):
    """Nota de briefing, idempotente: nao duplica se ja houver nota deste autor."""
    conteudo = transform.montar_briefing(dados_do_briefing(linha), prefixo=PREFIXO_BRIEFING)
    return (
        "INSERT INTO lead_notes (lead_id, author, content)\n"
        "SELECT l.id, %s, %s FROM leads l WHERE l.phone = %s\n"
        "  AND NOT EXISTS (SELECT 1 FROM lead_notes n WHERE n.lead_id = l.id "
        "AND n.author = %s);" % (
            sql_literal(AUTOR_NOTA), sql_literal(conteudo),
            sql_literal(linha["_phone"]), sql_literal(AUTOR_NOTA))
    )
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py -v
```
Esperado: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/lote_completo.py backend/tests/test_reativacao_lote_completo.py
git commit -m "feat(reativacao): SQL das notas de briefing do lote completo"
```

---

### Task 7: SQL dos deals

**Files:**
- Modify: `scripts/reativacao/lote_completo.py`
- Test: `backend/tests/test_reativacao_lote_completo.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
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
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py::TestSqlDeal -v
```
Esperado: FAIL — `no attribute 'gerar_insert_deal'`.

- [ ] **Step 3: Implementar**

```python
UUID_POR_ETAPA = {key: uuid_ for key, _label, _cor, uuid_ in ETAPAS}


def gerar_insert_deal(linha):
    """Um deal por lead, na etapa do seu segmento.

    Titulo segue a convencao de frontend/src/lib/import-deals.ts:33 —
    "<nome> - <funil>". Idempotente: nao cria segundo deal no mesmo funil.
    """
    titulo = "%s - %s" % (nome_do_lead(linha), PIPELINE_NOME)
    return (
        "INSERT INTO deals (lead_id, title, value, stage, pipeline_id, stage_id)\n"
        "SELECT l.id, %s, 0, 'novo', %s, %s FROM leads l WHERE l.phone = %s\n"
        "  AND NOT EXISTS (SELECT 1 FROM deals d WHERE d.lead_id = l.id "
        "AND d.pipeline_id = %s);" % (
            sql_literal(titulo), sql_literal(PIPELINE_ID),
            sql_literal(UUID_POR_ETAPA[etapa_de(linha)]),
            sql_literal(linha["_phone"]), sql_literal(PIPELINE_ID))
    )
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py -v
```
Esperado: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/lote_completo.py backend/tests/test_reativacao_lote_completo.py
git commit -m "feat(reativacao): SQL dos deals no funil do lote"
```

---

### Task 8: SQL das tags

**Files:**
- Modify: `scripts/reativacao/lote_completo.py`
- Test: `backend/tests/test_reativacao_lote_completo.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
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
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py::TestSqlTags -v
```
Esperado: FAIL — `no attribute 'gerar_tags'`.

- [ ] **Step 3: Implementar**

```python
def _vinculo_tag(tag_id, telefones):
    """Associa a tag a um conjunto de telefones, sem duplicar vinculo.

    NOT EXISTS em vez de ON CONFLICT porque nao ha garantia de constraint
    unica em lead_tags(lead_id, tag_id).
    """
    if not telefones:
        return ""
    lista = ", ".join(sql_literal(f) for f in sorted(telefones))
    return (
        "INSERT INTO lead_tags (lead_id, tag_id)\n"
        "SELECT l.id, %s FROM leads l WHERE l.phone IN (%s)\n"
        "  AND NOT EXISTS (SELECT 1 FROM lead_tags t WHERE t.lead_id = l.id "
        "AND t.tag_id = %s);\n" % (sql_literal(tag_id), lista, sql_literal(tag_id))
    )


def gerar_tags(coorte):
    """Cria as tags do lote e associa cada uma ao seu subconjunto.

    B2B ja existe no banco (2249642b-...), entao so ganha vinculo.
    """
    partes = ["-- Tags do lote"]
    for tag_id, nome, cor in TAGS_A_CRIAR:
        partes.append(
            "INSERT INTO tags (id, name, color) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING;" % (
                sql_literal(tag_id), sql_literal(nome), sql_literal(cor))
        )
    partes.append("")

    por_perfil = {"B2B": set(), "E-commerce": set(), "Sem vendedor": set()}
    todos, com_debito = set(), set()
    for linha in coorte:
        fone = linha["_phone"]
        todos.add(fone)
        por_perfil[perfil_comercial(linha)].add(fone)
        if transform.parse_numero(linha.get("valor_vencido")) > 0:
            com_debito.add(fone)

    partes.append(_vinculo_tag(TAG_LOTE_ID, todos))
    partes.append(_vinculo_tag(TAG_B2B_ID, por_perfil["B2B"]))
    partes.append(_vinculo_tag(TAG_ECOMMERCE_ID, por_perfil["E-commerce"]))
    partes.append(_vinculo_tag(TAG_SEM_VENDEDOR_ID, por_perfil["Sem vendedor"]))
    partes.append(_vinculo_tag(TAG_DEBITO_ID, com_debito))
    return "\n".join(p for p in partes if p is not None)
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py -v
```
Esperado: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/lote_completo.py backend/tests/test_reativacao_lote_completo.py
git commit -m "feat(reativacao): SQL das tags de lote, perfil e debito"
```

---

### Task 9: Montagem do arquivo, verificação e rollback

**Files:**
- Modify: `scripts/reativacao/lote_completo.py`
- Test: `backend/tests/test_reativacao_lote_completo.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
class TestMontagem:
    def _coorte(self):
        linhas = [_linha(id_bling=str(i), whatsapp="551190000%04d" % i) for i in range(1, 4)]
        return lote_completo.selecionar_faltantes(linhas, set()).novos

    def test_abre_em_transacao_e_fecha_com_commit(self):
        sql = lote_completo.montar_arquivo(self._coorte())
        assert sql.startswith("\\set ON_ERROR_STOP on")
        assert "BEGIN;" in sql
        assert sql.rstrip().endswith("COMMIT;")

    def test_nunca_toca_as_tabelas_de_disparo(self):
        sql = lote_completo.montar_arquivo(self._coorte())
        for tabela in lote_completo.TABELAS_PROIBIDAS:
            assert tabela not in sql

    def test_tem_bloco_de_verificacao_por_contagem(self):
        sql = lote_completo.montar_arquivo(self._coorte())
        assert sql.count("RAISE EXCEPTION") == 4
        assert "esperado 3" in sql

    def test_rollback_remove_na_ordem_de_dependencia(self):
        sql = lote_completo.montar_rollback()
        pos = [sql.index(t) for t in ("lead_tags", "deals", "pipeline_stages", "pipelines")]
        assert pos == sorted(pos)

    def test_rollback_apaga_so_o_que_este_lote_criou(self):
        sql = lote_completo.montar_rollback()
        assert "criado_por_lote" in sql
        assert lote_completo.LOTE in sql
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py::TestMontagem -v
```
Esperado: FAIL — `no attribute 'montar_arquivo'`.

- [ ] **Step 3: Implementar**

```python
def _bloco_verificacao(rotulo, expressao_where, esperado):
    """RAISE EXCEPTION aborta a transacao inteira e desfaz tudo que veio antes."""
    return (
        "\\echo '--- %s (esperado %d) ---'\n"
        "DO $$\nDECLARE encontrado integer;\nBEGIN\n"
        "  SELECT count(*) INTO encontrado FROM %s;\n"
        "  IF encontrado <> %d THEN\n"
        "    RAISE EXCEPTION 'esperado %d em %s, encontrado %%', encontrado;\n"
        "  END IF;\nEND $$;\n" % (
            rotulo, esperado, expressao_where, esperado, esperado, rotulo)
    )


def montar_arquivo(coorte):
    """preparar.sql completo, em transacao unica."""
    total = len(coorte)
    partes = [
        "\\set ON_ERROR_STOP on",
        "-- Lote %s — %d leads. NAO EDITAR A MAO: regenerar com lote_completo.py" % (LOTE, total),
        "BEGIN;",
        "",
        gerar_pipeline_e_etapas(),
        "-- Leads",
    ]
    partes.extend(gerar_insert_lead(l) for l in coorte)
    partes.append("\n-- Notas de briefing")
    partes.extend(gerar_insert_nota(l) for l in coorte)
    partes.append("\n-- Deals")
    partes.extend(gerar_insert_deal(l) for l in coorte)
    partes.append("")
    partes.append(gerar_tags(coorte))
    partes.append("-- Verificacao (aborta a transacao inteira se nao bater)")
    partes.append(_bloco_verificacao(
        "leads do lote",
        "leads WHERE metadata->>'origem' = '%s' AND metadata->>'lote' = '%s'" % (ORIGEM, LOTE),
        total))
    partes.append(_bloco_verificacao(
        "notas do lote", "lead_notes WHERE author = '%s'" % AUTOR_NOTA, total))
    partes.append(_bloco_verificacao(
        "deals do funil", "deals WHERE pipeline_id = '%s'" % PIPELINE_ID, total))
    partes.append(_bloco_verificacao(
        "etapas do funil", "pipeline_stages WHERE pipeline_id = '%s'" % PIPELINE_ID,
        len(ETAPAS)))
    partes.append("COMMIT;")
    return "\n".join(partes)


def montar_rollback():
    """Desfaz exatamente o que este lote criou, na ordem de dependencia."""
    tags_do_lote = [TAG_LOTE_ID, TAG_DEBITO_ID, TAG_ECOMMERCE_ID,
                    TAG_SEM_VENDEDOR_ID, TAG_B2B_ID]
    lista_tags = ", ".join(sql_literal(t) for t in tags_do_lote)
    return "\n".join([
        "\\set ON_ERROR_STOP on",
        "-- Rollback do lote %s" % LOTE,
        "BEGIN;",
        "",
        "-- 1. Vinculos de tag dos leads que este lote criou.",
        "DELETE FROM lead_tags WHERE tag_id IN (%s) AND lead_id IN (" % lista_tags,
        "  SELECT id FROM leads WHERE metadata->>'criado_por_lote' = %s);" % sql_literal(LOTE),
        "",
        "-- 2. As tags que este lote criou (B2B ja existia: nao apagar).",
        "DELETE FROM tags WHERE id IN (%s);" % ", ".join(
            sql_literal(t) for t, _n, _c in TAGS_A_CRIAR),
        "",
        "-- 3. Deals do funil, depois as etapas, depois o funil.",
        "DELETE FROM deals WHERE pipeline_id = %s;" % sql_literal(PIPELINE_ID),
        "DELETE FROM pipeline_stages WHERE pipeline_id = %s;" % sql_literal(PIPELINE_ID),
        "DELETE FROM pipelines WHERE id = %s;" % sql_literal(PIPELINE_ID),
        "",
        "-- 4. Notas de briefing deste lote.",
        "DELETE FROM lead_notes WHERE author = %s;" % sql_literal(AUTOR_NOTA),
        "",
        "-- 5. Os leads que este lote CRIOU (nunca os pre-existentes).",
        "DELETE FROM leads WHERE metadata->>'criado_por_lote' = %s;" % sql_literal(LOTE),
        "",
        "\\echo '--- deve retornar 0 ---'",
        "SELECT count(*) FROM leads WHERE metadata->>'criado_por_lote' = %s;" % sql_literal(LOTE),
        "COMMIT;",
    ])
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py -v
```
Esperado: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/lote_completo.py backend/tests/test_reativacao_lote_completo.py
git commit -m "feat(reativacao): montagem do preparar.sql com verificacao e rollback"
```

---

### Task 10: CLI com trava de contagem

**Files:**
- Modify: `scripts/reativacao/lote_completo.py`
- Test: `backend/tests/test_reativacao_lote_completo.py`

- [ ] **Step 1: Escrever os testes que falham**

```python
class TestCli:
    def _escrever_csv(self, tmp_path, linhas):
        caminho = tmp_path / "bling.csv"
        campos = list(linhas[0].keys())
        with caminho.open("w", encoding="utf-8-sig", newline="") as fh:
            escritor = csv.DictWriter(fh, fieldnames=campos, delimiter=";")
            escritor.writeheader()
            for l in linhas:
                escritor.writerow(l)
        return caminho

    def test_gera_os_dois_arquivos(self, tmp_path):
        csv_path = self._escrever_csv(tmp_path, [
            _linha(id_bling="1", whatsapp="5511900000001"),
            _linha(id_bling="2", whatsapp="5511900000002"),
        ])
        crm = tmp_path / "crm.txt"
        crm.write_text("5534999999999\n", encoding="utf-8")
        saida = tmp_path / "out"
        codigo = lote_completo.main([
            "--csv", str(csv_path), "--telefones-crm", str(crm),
            "--esperado-novos", "2", "--saida", str(saida)])
        assert codigo == 0
        assert (saida / "preparar.sql").exists()
        assert (saida / "rollback.sql").exists()

    def test_contagem_diferente_do_esperado_aborta_sem_escrever(self, tmp_path):
        csv_path = self._escrever_csv(tmp_path, [_linha(id_bling="1", whatsapp="5511900000001")])
        crm = tmp_path / "crm.txt"
        crm.write_text("5534999999999\n", encoding="utf-8")
        saida = tmp_path / "out"
        codigo = lote_completo.main([
            "--csv", str(csv_path), "--telefones-crm", str(crm),
            "--esperado-novos", "999", "--saida", str(saida)])
        assert codigo == 1
        assert not (saida / "preparar.sql").exists()
```

Adicione `import csv` ao topo do arquivo de teste se ainda não estiver lá.

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py::TestCli -v
```
Esperado: FAIL — `no attribute 'main'`.

- [ ] **Step 3: Implementar**

Adicione ao topo `import argparse`, `import os`, `import sys`, e ao fim do arquivo:

```python
def main(argv=None):
    parser = argparse.ArgumentParser(description="Gera o SQL do lote completo do Bling.")
    parser.add_argument("--csv", required=True, help="CSV completo do Bling")
    parser.add_argument("--telefones-crm", required=True,
                        help="uma coluna: todos os telefones que ja existem em leads")
    parser.add_argument("--esperado-novos", type=int, required=True,
                        help="trava: aborta se a contagem calculada nao bater")
    parser.add_argument("--saida", required=True)
    args = parser.parse_args(argv)

    linhas = carregar_csv(args.csv)
    telefones_crm = carregar_telefones_crm(args.telefones_crm)
    coorte = selecionar_faltantes(linhas, telefones_crm)

    print("linhas no CSV:        %d" % len(linhas))
    print("ja no CRM:            %d" % coorte.ja_no_crm)
    print("sem telefone:         %d" % coorte.sem_telefone)
    print("duplicados no CSV:    %d" % coorte.duplicados_no_csv)
    print("leads a criar:        %d" % len(coorte.novos))

    if len(coorte.novos) != args.esperado_novos:
        print("ERRO: contagem nao bate com o esperado -> %d != %d" % (
            len(coorte.novos), args.esperado_novos), file=sys.stderr)
        return 1

    preparar = montar_arquivo(coorte.novos)
    for tabela in TABELAS_PROIBIDAS:
        if tabela in preparar:
            print("ERRO: SQL referencia tabela proibida %r" % tabela, file=sys.stderr)
            return 1

    os.makedirs(args.saida, exist_ok=True)
    with open(os.path.join(args.saida, "preparar.sql"), "w", encoding="utf-8") as fh:
        fh.write(preparar)
    with open(os.path.join(args.saida, "rollback.sql"), "w", encoding="utf-8") as fh:
        fh.write(montar_rollback())
    print("gerado: %s/preparar.sql" % args.saida)
    print("gerado: %s/rollback.sql" % args.saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Rodar a suíte inteira**

```bash
cd backend && python -m pytest tests/test_reativacao_lote_completo.py tests/test_reativacao_transform.py tests/test_reativacao_sql.py -v
```
Esperado: PASS em tudo.

- [ ] **Step 5: Commit**

```bash
git add scripts/reativacao/lote_completo.py backend/tests/test_reativacao_lote_completo.py
git commit -m "feat(reativacao): CLI do lote completo com trava de contagem"
```

---

### Task 11: Rodagem real contra o CSV de produção

**Files:** nenhum — é validação.

- [ ] **Step 1: Extrair os telefones do CRM**

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -A -t -c \"select phone from leads\"" > /tmp/telefones_crm.txt
wc -l /tmp/telefones_crm.txt
```
Esperado: ~2.339 linhas. **Se vier vazio, pare** — o CLI aborta com `ValueError`, que é o comportamento correto.

- [ ] **Step 2: Gerar o SQL**

```bash
cd "Agentes AI/ValerIA" && python scripts/reativacao/lote_completo.py \
  --csv "leads-bling-completo-2026-08-08-br (1).csv" \
  --telefones-crm /tmp/telefones_crm.txt \
  --esperado-novos 1218 \
  --saida /tmp/lote_completo
```
Esperado na saída:
```
linhas no CSV:        2771
ja no CRM:            288
sem telefone:         1231
duplicados no CSV:    34
leads a criar:        1218
```

Se `leads a criar` divergir de 1.218, **não force o número**: investigue. A causa mais provável é a base ter mudado desde 14/08/2026 (leads novos entraram por conversa). Nesse caso, atualize `--esperado-novos` para o valor novo **depois** de confirmar que a diferença se explica por leads que passaram a existir.

- [ ] **Step 3: Conferir os guardrails do arquivo**

```bash
grep -c "INSERT INTO leads"           /tmp/lote_completo/preparar.sql   # 1218
grep -c "INSERT INTO lead_notes"      /tmp/lote_completo/preparar.sql   # 1218
grep -c "INSERT INTO deals"           /tmp/lote_completo/preparar.sql   # 1218
grep -c "INSERT INTO pipeline_stages" /tmp/lote_completo/preparar.sql   # 8
grep -c "INSERT INTO tags"            /tmp/lote_completo/preparar.sql   # 4
grep -c "RAISE EXCEPTION"             /tmp/lote_completo/preparar.sql   # 4
grep -cE "broadcasts|broadcast_leads" /tmp/lote_completo/preparar.sql   # 0
grep -c "assigned_to"                 /tmp/lote_completo/preparar.sql   # 0
```
Qualquer divergência: **não aplique**. Volte ao código, nunca edite o `.sql` à mão.

- [ ] **Step 4: Ler três notas de briefing à mão**

```bash
grep -A 20 "REATIVAÇÃO BLING" /tmp/lote_completo/preparar.sql | head -60
```
Confira que o nome do lead não é razão social crua, que a linha `ICP` não aparece, e que a linha de débito aparece nos que têm valor vencido.

- [ ] **Step 5: Commit da conferência**

```bash
git commit --allow-empty -m "chore(reativacao): rodagem real conferida (1218 leads, guardrails ok)"
```

---

### Task 12: Runbook

**Files:**
- Create: `scripts/reativacao/README-lote-completo.md`

- [ ] **Step 1: Escrever o runbook**

Crie `scripts/reativacao/README-lote-completo.md` com exatamente este conteúdo:

````markdown
# Lote completo do Bling — runbook

Cria 1.218 leads no CRM com funil, etapas, deals, tags e briefing.
**Não dispara nada** — nenhum registro em `broadcasts`/`broadcast_leads`.

- Spec: `docs/superpowers/specs/2026-08-14-reativacao-bling-lote-completo-design.md`
- Plano: `docs/superpowers/plans/2026-08-14-reativacao-bling-lote-completo.md`
- Código: `scripts/reativacao/lote_completo.py` (só gera arquivos, não executa)

## 0. Backup — obrigatório

O banco não tem backup automático (`archive_mode = off`, sem cron). Não é
"seria bom": é o único jeito de voltar atrás do que o rollback não cobre.

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D pg_dump -U postgres --no-owner postgres > /root/backup-pre-lote-completo-\$(date +%F).sql; ls -lh /root/backup-pre-lote-completo-*.sql"
```

Esperado: arquivo de ~106 MB. Muito menor que isso = dump truncado, **pare**.

## 1. Extrair os telefones que já existem no CRM

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -A -t -c \"select phone from leads\"" > /tmp/telefones_crm.txt
wc -l /tmp/telefones_crm.txt
```

Esperado: ~2.339 linhas. Arquivo vazio faz o CLI abortar com `ValueError` — que
é o comportamento certo: "CRM vazio" nunca é estado normal, e tratá-lo como tal
criaria 1.218 leads duplicados.

## 2. Gerar o SQL

```bash
python scripts/reativacao/lote_completo.py \
  --csv "leads-bling-completo-2026-08-08-br (1).csv" \
  --telefones-crm /tmp/telefones_crm.txt \
  --esperado-novos 1218 \
  --saida /tmp/lote_completo
```

`--esperado-novos` não é documentação: se a contagem não bater exatamente, o CLI
sai com código 1 e **não escreve arquivo nenhum**. Se divergir, investigue antes
de mudar o número — a causa provável é a base ter ganhado leads desde 14/08/2026.

## 3. Conferir os guardrails

```bash
grep -c "INSERT INTO leads"           /tmp/lote_completo/preparar.sql   # 1218
grep -c "INSERT INTO lead_notes"      /tmp/lote_completo/preparar.sql   # 1218
grep -c "INSERT INTO deals"           /tmp/lote_completo/preparar.sql   # 1218
grep -c "INSERT INTO pipeline_stages" /tmp/lote_completo/preparar.sql   # 8
grep -c "INSERT INTO tags"            /tmp/lote_completo/preparar.sql   # 4
grep -c "RAISE EXCEPTION"             /tmp/lote_completo/preparar.sql   # 4
grep -cE "broadcasts|broadcast_leads" /tmp/lote_completo/preparar.sql   # 0
grep -c "assigned_to"                 /tmp/lote_completo/preparar.sql   # 0
```

Divergiu? **Não aplique.** Volte ao `lote_completo.py` — o `.sql` nunca deve ser
editado à mão.

## 4. Aplicar

```bash
scp /tmp/lote_completo/preparar.sql root@173.249.15.11:/tmp/
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker cp /tmp/preparar.sql \$D:/tmp/; docker exec \$D psql -U postgres -v ON_ERROR_STOP=1 -f /tmp/preparar.sql"
```

**Se terminar sem erro, tudo foi aplicado e committado. Se aparecer
`ERROR: esperado N ..., encontrado M`, a transação inteira foi revertida e nada
persistiu** — nem lead, nem nota, nem deal, mesmo que os `\echo` de sucesso
tenham aparecido antes. Não existe meio-termo: ou o `COMMIT;` rodou, ou não.

## 5. Verificar

Os quatro blocos `RAISE EXCEPTION` já checaram as contagens antes do `COMMIT`.
O que resta é confirmar que cada etapa é selecionável na UI de disparo — o
critério que justifica a estrutura de funil único (o filtro corta em 1.000):

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -c \"select s.label, count(d.id) from pipeline_stages s left join deals d on d.stage_id = s.id where s.pipeline_id = 'b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09' group by s.label, s.order_index order by s.order_index\""
```

Esperado — **nenhuma linha pode passar de 1.000**:

| Etapa | Deals |
|---|---|
| Ativo (0-3m) | 76 |
| Inativo 3-6m | 68 |
| Inativo 6-12m | 71 |
| Inativo 12-24m | 63 |
| Inativo 24-36m | 102 |
| Inativo 36m+ | 670 |
| Pedido sem faturar | 62 |
| Nunca comprou | 106 |

E a tag fixa de inadimplência, que o modal de disparo lê:

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -c \"select count(*) from lead_tags where tag_id = '3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210'\""
```

Esperado: **182**.

## 6. Rollback

```bash
scp /tmp/lote_completo/rollback.sql root@173.249.15.11:/tmp/
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker cp /tmp/rollback.sql \$D:/tmp/; docker exec \$D psql -U postgres -v ON_ERROR_STOP=1 -f /tmp/rollback.sql"
```

Desfaz, nesta ordem: vínculos de tag dos leads criados, as 4 tags novas, os
deals do funil, as 8 etapas, o funil, as notas de briefing, e os leads que este
lote criou (chaveado em `metadata->>'criado_por_lote'`).

**Não apaga a tag `B2B`** — ela já existia e é usada por outros 271 leads; só o
vínculo dos leads deste lote sai.

Ao contrário do lote de 10/08, aqui o rollback é completo: este lote só cria,
nunca atualiza lead pré-existente nem normaliza telefone alheio. O único caso
não coberto é um lead deste lote que já tenha recebido mensagem antes do
rollback — aí a conversa some junto. Se isso for possível, restaure o dump do
passo 0 em vez de rodar o rollback.
````

- [ ] **Step 2: Commit**

```bash
git add scripts/reativacao/README-lote-completo.md
git commit -m "docs(reativacao): runbook de aplicacao do lote completo"
```

---

# PARTE 2 — Aviso de inadimplentes na UI

### Task 13: Constante da tag fixa

**Files:**
- Modify: `frontend/src/lib/constants.ts`

- [ ] **Step 1: Adicionar a constante**

Ao fim de `frontend/src/lib/constants.ts`:

```typescript
/**
 * Tag fixa de inadimplência. O modal de criação de disparo depende dela para
 * avisar quando há leads com débito vencido entre os selecionados, então o
 * UUID é estável entre ambientes e a API bloqueia rename/exclusão dessa tag.
 *
 * Duplicado em scripts/reativacao/lote_completo.py (TAG_DEBITO_ID) — os dois
 * lados não compartilham runtime. Mudar aqui exige mudar lá.
 */
export const TAG_DEBITO_VENCIDO_ID = "3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210";
```

- [ ] **Step 2: Verificar que compila**

```bash
cd frontend && npm run type-check
```
Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/constants.ts
git commit -m "feat(disparo): constante da tag fixa de inadimplencia"
```

---

### Task 14: `findInadimplentes`

**Files:**
- Create: `frontend/src/lib/inadimplentes.ts`
- Test: `frontend/src/lib/inadimplentes.test.ts`

- [ ] **Step 1: Escrever os testes que falham**

Crie `frontend/src/lib/inadimplentes.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { findInadimplentes, valorVencidoDe, type LeadComTags } from "@/lib/inadimplentes";
import { TAG_DEBITO_VENCIDO_ID } from "@/lib/constants";

const OUTRA_TAG = "2249642b-e4f2-420e-8482-d07b325a28c8";

function lead(over: Partial<LeadComTags> & { id: string }): LeadComTags {
  return {
    name: "Fulano",
    phone: "5534999999999",
    lead_tags: [],
    metadata: null,
    ...over,
  } as LeadComTags;
}

describe("findInadimplentes", () => {
  it("devolve vazio quando nada está selecionado", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }] })];
    const r = findInadimplentes(leads, new Set());
    expect(r.leads).toEqual([]);
    expect(r.totalVencido).toBe(0);
  });

  it("devolve vazio quando nenhum selecionado tem a tag", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: OUTRA_TAG, tags: null }] })];
    expect(findInadimplentes(leads, new Set(["a"])).leads).toEqual([]);
  });

  it("soma valor_vencido dos selecionados com a tag", () => {
    const leads = [
      lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: 1000 } }),
      lead({ id: "b", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: 234.56 } }),
    ];
    const r = findInadimplentes(leads, new Set(["a", "b"]));
    expect(r.leads.map((l) => l.id)).toEqual(["a", "b"]);
    expect(r.totalVencido).toBeCloseTo(1234.56);
  });

  it("ignora lead com a tag que não está selecionado", () => {
    const leads = [
      lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: 100 } }),
      lead({ id: "b", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: 900 } }),
    ];
    const r = findInadimplentes(leads, new Set(["a"]));
    expect(r.leads).toHaveLength(1);
    expect(r.totalVencido).toBe(100);
  });

  it("conta lead com a tag mas sem metadata, somando zero", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: null })];
    const r = findInadimplentes(leads, new Set(["a"]));
    expect(r.leads).toHaveLength(1);
    expect(r.totalVencido).toBe(0);
  });

  it("aceita valor_vencido como string com vírgula decimal", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: "1.234,56" } })];
    expect(findInadimplentes(leads, new Set(["a"])).totalVencido).toBeCloseTo(1234.56);
  });

  it("trata valor_vencido inválido como zero sem quebrar", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: "abc" } })];
    const r = findInadimplentes(leads, new Set(["a"]));
    expect(r.leads).toHaveLength(1);
    expect(r.totalVencido).toBe(0);
  });

  it("tolera lead_tags ausente", () => {
    const leads = [{ id: "a", name: "X", phone: "55", metadata: null } as LeadComTags];
    expect(findInadimplentes(leads, new Set(["a"])).leads).toEqual([]);
  });
});

describe("valorVencidoDe", () => {
  it("parseia string no formato brasileiro igual à soma", () => {
    expect(valorVencidoDe(lead({ id: "a", metadata: { valor_vencido: "1.234,56" } }))).toBeCloseTo(1234.56);
  });
  it("devolve 0 para metadata ausente ou lixo", () => {
    expect(valorVencidoDe(lead({ id: "a", metadata: null }))).toBe(0);
    expect(valorVencidoDe(lead({ id: "a", metadata: { valor_vencido: "abc" } }))).toBe(0);
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd frontend && npx vitest run src/lib/inadimplentes.test.ts
```
Esperado: FAIL — não resolve `@/lib/inadimplentes`.

- [ ] **Step 3: Implementar**

Crie `frontend/src/lib/inadimplentes.ts`:

```typescript
import { TAG_DEBITO_VENCIDO_ID } from "@/lib/constants";

export interface LeadComTags {
  id: string;
  name: string | null;
  phone: string;
  lead_tags?: { tag_id: string; tags: { id: string; name: string; color: string } | null }[];
  metadata?: Record<string, unknown> | null;
}

export interface ResultadoInadimplentes {
  leads: LeadComTags[];
  totalVencido: number;
}

/**
 * Parse tolerante: o valor vem de `metadata` (jsonb), então pode chegar como
 * número, como string no formato brasileiro ("1.234,56") ou ausente. Nada aqui
 * pode lançar — um alerta que quebra a tela é pior que um alerta impreciso.
 */
function parseValor(bruto: unknown): number {
  if (typeof bruto === "number") return Number.isFinite(bruto) ? bruto : 0;
  if (typeof bruto !== "string") return 0;
  const normalizado = bruto.trim().replace(/\./g, "").replace(",", ".");
  const valor = Number.parseFloat(normalizado);
  return Number.isFinite(valor) ? valor : 0;
}

export function temDebitoVencido(lead: LeadComTags): boolean {
  return (lead.lead_tags ?? []).some((lt) => lt.tag_id === TAG_DEBITO_VENCIDO_ID);
}

/** Valor vencido de um lead, já parseado. Use isto na UI — nunca `Number(...)`
 *  direto sobre o metadata, que devolve NaN em "1.234,56". */
export function valorVencidoDe(lead: LeadComTags): number {
  return parseValor(lead.metadata?.valor_vencido);
}

/**
 * Quais dos leads SELECIONADOS têm a tag fixa de débito vencido.
 *
 * Leads tagueados à mão depois da importação não têm `valor_vencido` no
 * metadata — eles contam na lista e somam zero, nunca somem do aviso.
 */
export function findInadimplentes(
  leads: LeadComTags[],
  selectedIds: Set<string>
): ResultadoInadimplentes {
  const encontrados = leads.filter((l) => selectedIds.has(l.id) && temDebitoVencido(l));
  const totalVencido = encontrados.reduce(
    (soma, l) => soma + parseValor(l.metadata?.valor_vencido),
    0
  );
  return { leads: encontrados, totalVencido };
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd frontend && npx vitest run src/lib/inadimplentes.test.ts
```
Esperado: PASS nos 10 testes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/inadimplentes.ts frontend/src/lib/inadimplentes.test.ts
git commit -m "feat(disparo): findInadimplentes com parse tolerante de metadata"
```

---

### Task 15: Guard 409 na API de tags

**Files:**
- Modify: `frontend/src/app/api/tags/[id]/route.ts`

- [ ] **Step 1: Implementar o guard**

Em `frontend/src/app/api/tags/[id]/route.ts`, adicione o import e o guard no início de **ambos** os handlers:

```typescript
import { TAG_DEBITO_VENCIDO_ID } from "@/lib/constants";

// A tag fixa de inadimplência é contrato do modal de disparo: se alguém a
// renomear ou apagar pela UI, o aviso de débito vencido some em silêncio —
// o pior modo de falha possível para um alerta.
const TAG_FIXA_ERRO =
  "A tag \"Débito vencido\" é fixa: o modal de criação de disparo depende dela " +
  "para avisar sobre leads inadimplentes.";
```

No `PUT`, logo após `const { id } = await params;`:

```typescript
  if (id === TAG_DEBITO_VENCIDO_ID) {
    return NextResponse.json({ error: TAG_FIXA_ERRO }, { status: 409 });
  }
```

No `DELETE`, logo após `const { id } = await params;`:

```typescript
  if (id === TAG_DEBITO_VENCIDO_ID) {
    return NextResponse.json({ error: TAG_FIXA_ERRO }, { status: 409 });
  }
```

- [ ] **Step 2: Verificar que compila**

```bash
cd frontend && npm run type-check && npm run lint
```
Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/tags/[id]/route.ts
git commit -m "feat(disparo): bloqueia rename e exclusao da tag fixa de inadimplencia"
```

---

### Task 16: Componente do banner

**Files:**
- Create: `frontend/src/components/campaigns/inadimplentes-warning.tsx`

- [ ] **Step 1: Implementar**

```tsx
"use client";

import { useState } from "react";
import { findInadimplentes, valorVencidoDe, type LeadComTags } from "@/lib/inadimplentes";

const MOEDA = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

interface InadimplentesWarningProps {
  leads: LeadComTags[];
  selectedLeadIds: Set<string>;
  onDeselect?: (ids: string[]) => void;
  variant: "selection" | "review";
}

/**
 * Avisa que há leads com débito vencido entre os selecionados.
 *
 * Não bloqueia a criação do disparo (decisão D5 do spec de 14/08): a base
 * inclui inadimplentes de propósito; o papel do aviso é tornar a inclusão num
 * disparo específico consciente, não impedi-la.
 */
export function InadimplentesWarning({
  leads,
  selectedLeadIds,
  onDeselect,
  variant,
}: InadimplentesWarningProps) {
  const [expandido, setExpandido] = useState(false);
  const { leads: inadimplentes, totalVencido } = findInadimplentes(leads, selectedLeadIds);

  if (inadimplentes.length === 0) return null;

  const total = MOEDA.format(totalVencido);

  if (variant === "review") {
    return (
      <p className="text-[13px] text-[#c41c1c]">
        ⚠ {inadimplentes.length} dos {selectedLeadIds.size} com débito vencido ({total})
      </p>
    );
  }

  const visiveis = expandido ? inadimplentes : inadimplentes.slice(0, 3);
  const restantes = inadimplentes.length - visiveis.length;

  return (
    <div className="border border-[#c41c1c]/30 bg-[#c41c1c]/5 rounded-[6px] p-3 space-y-2">
      <p className="text-[13px] text-[#c41c1c] font-medium">
        ⚠ {inadimplentes.length} dos {selectedLeadIds.size} selecionados têm débito vencido
        {totalVencido > 0 && <span className="font-normal"> ({total})</span>}
      </p>

      <ul className="space-y-0.5">
        {visiveis.map((lead) => {
          const valor = valorVencidoDe(lead);
          const dias = lead.metadata?.dias_atraso_max;
          return (
            <li key={lead.id} className="text-[12px] text-[#7b7b78] flex gap-2">
              <span className="text-[#111111] truncate max-w-[160px]">
                {lead.name ?? "—"}
              </span>
              <span>{lead.phone}</span>
              {valor > 0 && <span>{MOEDA.format(valor)}</span>}
              {dias ? <span>· {String(dias)}d</span> : null}
            </li>
          );
        })}
      </ul>

      <div className="flex items-center gap-3">
        {restantes > 0 && (
          <button
            type="button"
            onClick={() => setExpandido(true)}
            className="text-[12px] text-[#7b7b78] underline hover:text-[#111111] transition-colors"
          >
            + {restantes} outro{restantes !== 1 ? "s" : ""}
          </button>
        )}
        {expandido && inadimplentes.length > 3 && (
          <button
            type="button"
            onClick={() => setExpandido(false)}
            className="text-[12px] text-[#7b7b78] underline hover:text-[#111111] transition-colors"
          >
            ver menos
          </button>
        )}
        {onDeselect && (
          <button
            type="button"
            onClick={() => onDeselect(inadimplentes.map((l) => l.id))}
            className="ml-auto text-[12px] text-[#111111] border border-[#dedbd6] px-2 py-0.5 rounded-[4px] bg-white hover:border-[#111111] transition-colors"
          >
            Desmarcar os {inadimplentes.length}
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar que compila**

```bash
cd frontend && npm run type-check && npm run lint
```
Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/campaigns/inadimplentes-warning.tsx
git commit -m "feat(disparo): banner de leads com debito vencido"
```

---

### Task 17: Ligar o banner no modal

**Files:**
- Modify: `frontend/src/components/campaigns/create-broadcast-modal.tsx`

- [ ] **Step 1: Adicionar `metadata` ao tipo local e importar o componente**

Na interface `Lead` (linha ~20), adicione o campo:

```typescript
interface Lead {
  id: string;
  name: string | null;
  phone: string;
  company: string | null;
  nome_fantasia: string | null;
  lead_tags?: { tag_id: string; tags: { id: string; name: string; color: string } | null }[];
  metadata?: Record<string, unknown> | null;
}
```

E o import junto dos demais (após a linha do `LeadFilterPanel`):

```typescript
import { InadimplentesWarning } from "@/components/campaigns/inadimplentes-warning";
```

- [ ] **Step 2: Adicionar o handler de desmarcar**

Junto de `selectAllLeads` / `deselectAllLeads`, acrescente:

```typescript
  const deselectLeads = useCallback((ids: string[]) => {
    setSelectedLeadIds((atual) => {
      const proximo = new Set(atual);
      ids.forEach((id) => proximo.delete(id));
      return proximo;
    });
  }, []);
```

- [ ] **Step 3: Inserir o banner no passo 3**

No bloco `{step === 3 && ...}`, dentro da coluna da tabela, **logo acima** do `{/* Count badge */}`:

```tsx
                      <InadimplentesWarning
                        leads={leads}
                        selectedLeadIds={selectedLeadIds}
                        onDeselect={deselectLeads}
                        variant="selection"
                      />
```

- [ ] **Step 4: Inserir o resumo no passo 6**

No bloco `{step === 6 && ...}`, logo **abaixo** do parágrafo que mostra `Leads:` (o que renderiza `${selectedLeadIds.size} lead${...} do CRM`), adicione:

```tsx
                  {leadTab === "crm" && (
                    <InadimplentesWarning
                      leads={leads}
                      selectedLeadIds={selectedLeadIds}
                      variant="review"
                    />
                  )}
```

- [ ] **Step 5: Verificar**

```bash
cd frontend && npm run type-check && npm run lint && npm test
```
Esperado: sem erros de tipo, sem lint, e a suíte inteira passando.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/campaigns/create-broadcast-modal.tsx
git commit -m "feat(disparo): aviso de inadimplentes nos passos de selecao e revisao"
```

---

### Task 18: Verificação manual no navegador

**Files:** nenhum — é validação.

- [ ] **Step 1: Subir o ambiente**

```bash
cd frontend && npm run dev
```
Abra `http://127.0.0.1:3000/campanhas` e comece a criar um disparo.

- [ ] **Step 2: Conferir os cinco comportamentos**

1. Sem nenhum lead com a tag selecionado, o passo 3 fica **idêntico** ao de antes.
2. Selecionando um lead com `Débito vencido`, o banner aparece com contagem, nome, telefone, valor e dias.
3. `+N outros` expande e `ver menos` recolhe.
4. `Desmarcar os N` limpa todos de uma vez e o banner some.
5. No passo 6 a linha compacta aparece e **o botão de criar o disparo continua habilitado**.

> Se a Parte 1 ainda não foi aplicada ao banco, nenhum lead terá a tag. Para testar antes, crie a tag e vincule a um lead manualmente:
> ```sql
> INSERT INTO tags (id, name, color) VALUES ('3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210', 'Débito vencido', '#DC2626') ON CONFLICT (id) DO NOTHING;
> UPDATE leads SET metadata = metadata || '{"valor_vencido": 1234.56, "dias_atraso_max": 190}'::jsonb WHERE phone = '<um telefone de teste>';
> INSERT INTO lead_tags (lead_id, tag_id) SELECT id, '3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210' FROM leads WHERE phone = '<um telefone de teste>';
> ```
> Desfaça depois com `DELETE FROM lead_tags WHERE tag_id = '3d1b8e6c-...';`

- [ ] **Step 3: Conferir o guard da tag**

```bash
curl -i -X DELETE http://127.0.0.1:3000/api/tags/3d1b8e6c-7a24-4f95-b8d1-5c0e9a47f210
```
Esperado: `HTTP/1.1 409` com a mensagem sobre a tag fixa.

- [ ] **Step 4: Commit da verificação**

```bash
git commit --allow-empty -m "chore(disparo): verificacao manual do aviso de inadimplentes"
```

---

## Riscos conhecidos

**244 dos 1.218 são telefone fixo** (assinante começando em 2-5). Eles ficam gravados com 12 dígitos, sem o 9º injetado — o contrário fabricaria um celular que muito provavelmente pertence a **outra pessoa** (`(68) 3302-0386` do Poder Judiciário viraria `68 9 3302-0386`), e este lote alimenta disparo de template. Isso diverge de `backend/app/leads/service.py::normalize_phone` e de `frontend/src/lib/phone.ts`, que injetam o 9 em qualquer número de 12 dígitos começando com 55 — os dois têm o mesmo defeito, e corrigi-los é trabalho separado (afeta a base inteira, não só este lote).

A consequência de preservar 12 dígitos: se um desses fixos for um número de WhatsApp Business, o webhook vai gravar a forma de 13 dígitos e criar um segundo lead. É um risco menor que mandar marketing para estranho, mas existe. `whatsapp_tipo` fica em `metadata` para dar como filtrar esses 244 na hora de montar o disparo; se quiser que vire tag selecionável na UI, é uma linha em `TAGS_A_CRIAR` e uma chamada de `_vinculo_tag`.

**A Parte 1 não é reexecutável cegamente.** Todos os INSERTs são idempotentes, mas `--esperado-novos` trava a geração se a contagem mudar. Se a base ganhar leads entre a geração e a aplicação, regenere a partir da Task 11 passo 1.

**A tag `B2B` já existe e é usada por outros 271 leads.** O rollback (Task 9) apaga só o *vínculo* dos leads deste lote com ela, nunca a tag.
