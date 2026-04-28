# Design: Fonte de Preços Private Label via CSV

**Data:** 2026-04-27
**Status:** Aprovado

---

## Problema

Os preços de private label estão hardcoded nos prompts `valeria_inbound/private_label.py` e `valeria_outbound/private_label.py`. Existe um CSV autoritativo em `.rags/tabela_precos_cafe_canastra.csv` com preços diferentes dos que estão no prompt, criando divergência silenciosa. Drip Coffee e Cápsulas Nespresso estão no prompt mas não no CSV e devem ser removidos.

---

## Solução

Injeção estática no import time. Cada arquivo `private_label.py` lê o CSV ao ser importado, monta o bloco de produtos a partir da coluna `descricao_para_rag`, e injeta em `PRIVATE_LABEL_PROMPT` via f-string. O CSV vira fonte única de verdade para produtos e preços.

---

## Arquitetura

```
.rags/tabela_precos_cafe_canastra.csv  ←  fonte única de verdade
        ↓ lido na importação do módulo
valeria_inbound/private_label.py
valeria_outbound/private_label.py
  → _build_products_block() → string com descricao_para_rag de cada linha
  → PRIVATE_LABEL_PROMPT = f"...{_products_block}..."
```

### Função de carregamento

```python
import csv
from pathlib import Path

_CSV_PATH = Path(__file__).parents[5] / ".rags" / "tabela_precos_cafe_canastra.csv"

def _build_products_block() -> str:
    lines = ["## PRODUTOS PRIVATE LABEL"]
    with open(_CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            lines.append(row["descricao_para_rag"])
    return "\n\n".join(lines)

_products_block = _build_products_block()
```

A função é idêntica nos dois arquivos (inbound e outbound). Não é extraída para um utilitário compartilhado — YAGNI.

---

## Arquivos Alterados

| Arquivo | Mudança |
|---|---|
| `backend/app/agent/prompts/valeria_inbound/private_label.py` | Adiciona `_build_products_block()`, injeta `_products_block` no prompt, remove seção hardcoded de produtos, remove Drip Coffee e Cápsulas, atualiza exemplos de preço |
| `backend/app/agent/prompts/valeria_outbound/private_label.py` | Mesmas mudanças |

Nenhum outro arquivo de produção é alterado. Nenhum consumidor do prompt precisa mudar — `PRIVATE_LABEL_PROMPT` continua sendo uma `str`.

---

## Remoções

- Seção `## PRODUTOS PRIVATE LABEL` hardcoded (250g, 500g, Microlote, Drip Coffee, Cápsulas)
- Drip Coffee e Cápsulas Nespresso: removidos completamente
- Exemplos de preço antigos em `## COMO APRESENTAR PRECOS`: atualizados para os valores do CSV
- Exemplo de cálculo na `REGRA PRIORITARIA`: `100 × R$44,90 = R$4.490,00` → `100 × R$48,70 = R$4.870,00`

O que permanece estático no prompt: Sabores Disponíveis, Informações Extras (grãos, pontuação, fazenda), todo o restante do fluxo.

---

## Tratamento de Erro

Se o CSV não existir, `FileNotFoundError` é lançado na importação. Falha rápida intencional — o app não sobe com configuração inválida.

---

## Testes

`test_private_label_calcula_preco_por_quantidade` valida:
- `"CALCULE"` no prompt — permanece
- `"nao sabe calcular"` no prompt — permanece

Nenhum teste precisa ser alterado.

---

## Preços do CSV (referência)

| Produto | Com embalagem silk | Embalagem do cliente | Lote mínimo |
|---|---|---|---|
| Café Canastra 250g | R$26,70 | R$25,70 | 100 unidades |
| Café Canastra 500g | R$48,70 | R$47,70 | 100 unidades |
| Microlote 250g | R$29,70 | R$27,70 | 50un (emb cliente) / 100un (emb Canastra) |
