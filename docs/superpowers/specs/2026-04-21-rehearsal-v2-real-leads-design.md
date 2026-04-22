# Rehearsal V2 — Personas Derivadas de Leads Reais

**Data:** 2026-04-21
**Branch alvo:** `fix/conversas-display-bugs` (atual)
**Status:** Design aprovado, pronto para plano de implementação

---

## Contexto

O sistema de rehearsal atual (A1-A5) foi construído sobre suposições do que um lead "típico" faz. O resultado foi 5/5 passando nos hard checks, mas com `bot_score` médio baixo (2-3 em vários) e sinal pouco acionável.

Recebemos 5 conversas reais da Valéria antiga com leads (`.conversasreais/`). Elas são a primeira fonte de verdade que temos sobre como leads de fato se comportam. Os arquétipos A1-A5 não correspondem a nenhum desses leads reais:

- A1 (cafeteria BH atacado), A3 (multi-intent), A4 (já tenho fornecedor), A5 (exportação Lisboa) — nenhum aparece nos reais.
- A2 (private-label) bate superficialmente, mas a persona é rasa.

## Objetivo

Substituir A1-A5 por **R1-R5**, uma persona por conversa real, mantendo o runner, o mock provider, o Gemini actor e o logger inalterados. Acrescentar uma camada de verificação **anti-alucinação** (proibições regex contra bot messages) ao critério de passa/falha.

**Fora de escopo:**
- Modo replay literal (alimentar transcripts reais verbatim na bot).
- Multi-sessão (retornos após horas/dias).
- Fragmentação de mensagens (1-N mensagens por turno do actor).
- Migração de `google-generativeai` para `google-genai`.
- Alterações no prompt da Valéria (serão consequência dos resultados do rehearsal V2, não parte deste spec).

---

## Arquitetura

### Arquivos que mudam

| Arquivo | Mudança |
|---|---|
| `backend/scripts/rehearsal/archetypes.py` | **Reescrito.** Remove A1-A5, adiciona R1-R5. |
| `backend/scripts/rehearsal/verifier.py` | **Estendido.** Executa `forbids` junto com `hard_checks`. |

### Arquivos que NÃO mudam

- `backend/scripts/rehearsal_runner.py`
- `backend/scripts/rehearsal/gemini_actor.py`
- `backend/scripts/rehearsal/supabase_io.py`
- `backend/scripts/rehearsal/logger.py`
- `backend/app/whatsapp/mock_provider.py`
- `backend/app/whatsapp/registry.py`

### Nova factory de hard check

Para R1, que aceita `atacado` **ou** `private_label` como final legítimo, é necessária uma factory nova em `archetypes.py`:

```python
def reached_any_stage(stages: list[str]):
    def check(run_data: dict) -> tuple[bool, str]:
        visited = run_data.get("stages_visited", set())
        hit = [s for s in stages if s in visited]
        if hit:
            return True, f"stage {hit[0]} alcancado (entre {stages})"
        return False, f"nenhum dos stages {stages} alcancado (visitados: {visited})"
    check.__name__ = f"reached_any_{'_'.join(stages)}"
    return check
```

### Modelo de dados

`Archetype` ganha um campo `forbids`:

```python
@dataclass
class Archetype:
    id: str
    slug: str
    persona_prompt: str
    first_message: str
    hard_checks: list[Callable[[dict], tuple[bool, str]]] = field(default_factory=list)
    forbids: list[Callable[[dict], tuple[bool, str]]] = field(default_factory=list)  # NOVO
```

Cada `forbids` é uma função que retorna `(True, "ok")` quando não houve violação e `(False, "[VIOLATION:LABEL] ...")` quando a bot violou. A assinatura é idêntica aos `hard_checks` para reuso no runner.

### Critério de passa/falha

Um run **passa** se e somente se:
1. Todos os `hard_checks` retornarem `True`, E
2. Todos os `forbids` retornarem `True` (nenhuma violação).

Qualquer `False` em qualquer lista reprova o run, e a label da falha aparece na saída do logger.

### Execução dos forbids

Os forbids são aplicados **apenas** em mensagens com `role="assistant"` (bot). Nunca no transcript do actor. A verificação é feita no mesmo ponto onde os hard_checks rodam hoje, ao final da conversa.

---

## As 5 personas

Cada persona foi extraída de uma conversa real. Mantidos: tom, objeções centrais, perguntas características, momento de aceitar handoff. Descartados: detalhes identificáveis (telefones, nomes exatos quando irrelevantes — mantemos nomes porque o actor precisa de identidade).

### R1 — Aldo (representante comercial explorando portfólio)

**Origem:** `+55 13 98851-3644.txt`

**Perfil:** Representante comercial da área de suplementos nutricionais. Atende lojas especializadas, de produtos naturais, empórios e farmácias. Quer incluir café premium de alto giro no portfólio. Está entre revenda (distribuição) da marca Canastra e marca própria.

**First message:** `"oi, sou representante comercial, atendo lojas especializadas e naturais, queria incluir um cafe premium no portfolio. voces trabalham com distribuicao?"`

**Comportamento da persona:**
- Mensagens médias (1-3 frases), analítico.
- Pergunta sobre modelo: distribuição via representantes ou venda direta.
- Pergunta sobre markup de revenda.
- Transita entre atacado e private_label durante a conversa.
- Aceita supervisor quando tem clareza do modelo.

**Hard checks:**
- `reached_any_stage(["atacado", "private_label"])` — qualquer caminho legítimo.
- `has_tool_call("encaminhar_humano")`.
- `min_turns(5)`.

**Forbids:** universais (ver abaixo).

---

### R2 — Maria Emília (marca do zero, cauteloso-empática)

**Origem:** `+55 14 99125-2628.txt`

**Perfil:** Bancária em Botucatu/SP, ex-dona de cafeteria. Quer começar algo novo: criar marca de café do zero com duas opções (tradicional + gourmet). Ama café.

**First message (fragmentação real, consolidada numa mensagem):** `"boa tarde, meu nome é Maria Emilia, falo de Botucatu SP. gostaria de fazer minha marca de cafe, ja tive cafeteria e amo cafe. queria comecar com dois tipos: um tradicional e um gourmet. pode me passar todas as informacoes?"`

**Comportamento da persona:**
- Pergunta se valores incluem frete.
- Pergunta se o preço é igual para tradicional e gourmet.
- Pergunta por onde outros clientes vendem (Mercado Livre? marketplaces?).
- Preocupada com preço final apertado ao consumidor — calcula mentalmente enquanto conversa.
- Pede pra comprar avulso antes de fechar private label.
- Pergunta preço final que a Canastra pratica.

**Hard checks:**
- `reached_stage("private_label")`.
- `has_tool_call("enviar_fotos") OR has_tool_call("enviar_foto_produto")`.
- `min_turns(6)`.

**Forbids:** universais.

---

### R3 — Eduardo (private label com grãos próprios)

**Origem:** `+55 21 99163-3103.txt`

**Perfil:** RJ, tem uma marca em "base" (ainda não operando). Tem grãos especiais que ele selecionou e quer que a Canastra apenas **torre e embale** com o branding dele. Pragmático, cobra concretude.

**First message:** `"quero torrar e embalar o cafe com a minha marca, ja tenho os graos selecionados"`

**Comportamento da persona:**
- Cobra orçamento concreto antes de aceitar avançar.
- Pergunta se precisa entregar os grãos + pagar pelo serviço (duplo custo).
- Se frustra com fluxo abstrato ("não recebi nenhum orçamento até então").
- Aceita supervisor apenas após ver preços e entender o modelo.

**Hard checks:**
- `reached_stage("private_label")`.
- `has_tool_call("encaminhar_humano")`.
- `min_turns(4)`.

**Forbids:** universais.

---

### R4 — Josiely (exploradora contemplativa multi-tema)

**Origem:** `+55 27 99785-6480.txt`

**Perfil:** ES, interessada em criar marca de café do zero. Foco em "valor e qualidade". Exploradora — pergunta vários detalhes técnicos antes de decidir.

**First message:** `"oi, estou querendo conhecer como funciona a criacao da propria marca"`

**Comportamento da persona:**
- Pergunta o que é silk (técnica específica).
- Pergunta se aumentando a demanda o preço diminui.
- Pergunta sobre frete em cenário hipotético.
- Pede amostra.
- Em algum ponto pode dizer "vou analisar e retorno" — mas dentro do mesmo run (não multi-sessão).

**Hard checks:**
- `reached_stage("private_label")`.
- `has_tool_call("enviar_fotos") OR has_tool_call("enviar_foto_produto")`.
- `has_tool_call("encaminhar_humano")`.
- `min_turns(8)`.

**Forbids:** universais.

---

### R5 — Sabrina (lojista com objeção forte de amostra)

**Origem:** `+55 51 9647-7786.txt`

**Perfil:** RS/Charqueadas, lojista de chimarrão. Clientes pedem café. Quer criar marca própria, mas primeiro quer experimentar. Insiste na objeção de amostra mesmo após resposta negativa.

**First message:** `"sou lojista, minha loja é especializada em chimarrão no RS. pessoal me pede muito cafe. gostaria de experimentar antes de fechar, o ideal seria com a minha marca"`

**Comportamento da persona:**
- Pede amostra já no 2º-3º turno.
- Insiste mesmo após a bot explicar que não há amostras grátis no private label.
- Pergunta onde encontra próximo de Charqueadas/RS (ponto de venda físico).
- Aceita supervisor quando a objeção for **endereçada** (oferta de compra avulsa, site, ou encaminhamento para supervisor com a dúvida anotada).

**Hard checks:**
- `reached_stage("private_label")`.
- `has_tool_call("encaminhar_humano")`.
- `transcript_matches(r"(avulsa|avulso|loja\.cafecanastra|supervisor|experimentar|comprar uma unidade)", "endereçou objeção de amostra")`.
- `min_turns(5)`.

**Forbids:** universais + **específica** (ver abaixo: `forbids_ponto_venda_fisico`).

---

## Proibições anti-alucinação (forbids)

### Universais (aplicadas a todas as personas R1-R5)

Implementadas como factories em `verifier.py`:

```python
FORBID_PIX = forbids_regex(
    r"\bpix\b|chave\s+pix|copia\s+e\s+cola|qr[\s-]?code",
    label="PIX",
    description="bot mencionou PIX (pagamento é responsabilidade do comercial humano)"
)

FORBID_PRECO_TOTAL_COM_FRETE = forbids_regex(
    r"(investimento\s+inicial|fica\s+em\s+torno\s+de|custo\s+final|total\s+de).{0,30}R\$\s*\d",
    label="PRECO_FRETE",
    description="bot prometeu preço final com frete — só supervisor faz orçamento fechado"
)

FORBID_PRAZO = forbids_regex(
    r"\b(prazo\s+de|chega\s+em|entrego\s+em|em\s+ate)\s*\d+\s*(dias?\s+ute?i?s?|dias?|horas?)",
    label="PRAZO",
    description="bot prometeu prazo de entrega — depende do frete e supervisor"
)

FORBID_DESCONTO = forbids_regex(
    r"(posso\s+fazer\s+por|libero\s+por|sai\s+por\s+R\$|desconto\s+de\s+\d+\s*%|promocao|condicao\s+especial)",
    label="DESCONTO",
    description="bot ofereceu desconto improvisado — condições são fechadas pelo comercial"
)

FORBID_PAPEL_CONTRADICAO = forbids_regex(
    r"(passa(ndo|rei)?|vou\s+passar|encaminho)\s+(voce\s+)?(pro|para\s+o|ao)\s+comercial\b",
    label="PAPEL",
    description="bot disse 'passar pro comercial' sendo ela mesma do comercial — deve dizer 'pro supervisor' ou 'pro João Bras'"
)

UNIVERSAL_FORBIDS = [
    FORBID_PIX,
    FORBID_PRECO_TOTAL_COM_FRETE,
    FORBID_PRAZO,
    FORBID_DESCONTO,
    FORBID_PAPEL_CONTRADICAO,
]
```

### Específicas

**R5 (Sabrina):**
```python
FORBID_PONTO_VENDA_FISICO = forbids_regex(
    r"(temos\s+(ponto|loja)\s+(em|no|na)|voce\s+encontra\s+em|disponivel\s+em)\s+(charqueadas|rs|rio\s+grande|porto\s+alegre)",
    label="PONTO_VENDA_RS",
    description="bot inventou ponto de venda físico no RS — Canastra só tem venda direta"
)
```

### Implementação da factory `forbids_regex`

```python
import re

def forbids_regex(pattern: str, label: str, description: str):
    """Check fails if pattern matches in any BOT message (role='assistant')."""
    compiled = re.compile(pattern, re.IGNORECASE)

    def check(run_data: dict) -> tuple[bool, str]:
        messages = run_data.get("messages", [])
        for m in messages:
            if m.get("role") != "assistant":
                continue
            content = m.get("content", "")
            match = compiled.search(content)
            if match:
                snippet = content[max(0, match.start()-20):match.end()+20]
                return False, f"[VIOLATION:{label}] {description} — trecho: '{snippet}'"
        return True, f"{label}: sem violação"

    check.__name__ = f"forbid_{label.lower()}"
    return check
```

---

## Fluxo de execução

Idêntico ao atual, com uma mudança mínima no `rehearsal_runner.py` ou `verifier.py` (a escolher no plano): após rodar `hard_checks`, rodar `forbids` e agregar resultados. O transcript final do run lista:

```
Hard checks:
  [PASS] reached_private_label: stage private_label alcancado
  [PASS] has_encaminhar_humano: encaminhar_humano presente nos eventos
  [PASS] min_6_turns: 7 turnos (>= 6)

Forbids:
  [PASS] PIX: sem violação
  [FAIL] PRECO_FRETE: bot prometeu preço final com frete — trecho: '...investimento inicial fica por volta de R$ 2.540...'
  [PASS] PRAZO: sem violação
  [PASS] DESCONTO: sem violação
  [PASS] PAPEL: sem violação

Resultado: FAILED (1 violação anti-alucinação)
```

---

## Rollout e validação

1. **Smoke test 1 — Garantir que forbids são detectáveis:**
   Rodar um run artificial onde um forbid **deve** falhar. Ex: temporariamente adicionar uma mensagem forçada de bot com "fica em torno de R$ 2.500 com frete" e confirmar que o relatório marca `FAIL PRECO_FRETE`.

2. **Smoke test 2 — R5 isolada:**
   `REHEARSAL_ONLY=R5 python3 -m scripts.rehearsal_runner`. Essa é a persona mais objetora. Confirmar que ela realmente insiste em amostra e que a bot tem chance real de falhar ou passar.

3. **Run completo:**
   `python3 -m scripts.rehearsal_runner` contra todas R1-R5. Baseline esperada: **provavelmente algumas falhas**, especialmente em `PRECO_FRETE` (vi a Valéria antiga fazer esse bug com Maria Emília — nada garante que a atual não faça também) e `PAPEL` (bug observado na sessão passada com A1).

4. **Interpretação dos resultados:**
   - Se a Valéria atual passar tudo, ótimo — o prompt já cobre os casos.
   - Se falhar em forbids, **não é falha do spec** — é sinal de que o prompt da Valéria precisa de ajuste. Cada violação vira um item para o próximo ciclo (não coberto neste spec).

---

## Critérios de aceitação

O spec é considerado implementado com sucesso quando:

- [ ] `archetypes.py` contém somente R1-R5 (nenhum traço de A1-A5).
- [ ] `reached_any_stage` está disponível como factory em `archetypes.py`.
- [ ] Cada persona R1-R5 tem `hard_checks` e `forbids` preenchidos conforme definido acima.
- [ ] `verifier.py` expõe `forbids_regex(...)`, `UNIVERSAL_FORBIDS`, e roda forbids no ciclo de verificação.
- [ ] O logger no output do run mostra uma seção "Forbids:" com PASS/FAIL por proibição.
- [ ] Smoke test 1 (forbid artificialmente violado) dispara FAIL corretamente.
- [ ] Smoke test 2 (R5) roda sem crash e produz um relatório.
- [ ] Run completo R1-R5 executa sem crash (independente de pass/fail do conteúdo).

Qualidade das respostas da Valéria (bot_score alto) **não é critério de aceitação deste spec** — é outputs que vão alimentar o próximo ciclo de ajuste de prompts.

---

## Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Regex de forbids dão falsos positivos (ex: bot diz "não trabalhamos com PIX" e bate no FORBID_PIX). | Regex são propostos como v1 — ajustar no implementação revisando transcripts reais. Documentar cada falso positivo no plano. |
| Personas ficam muito rígidas e o Gemini actor não consegue improvisar respostas naturais. | Persona prompt só define tom/comportamento/objeções; actor tem liberdade pra improvisar dentro desses limites (como hoje). |
| R5 entra em loop sem nunca resolver a objeção de amostra. | `max_turns=20` corta o loop. O hard check `transcript_matches` com alternativas (avulsa OR supervisor OR experimentar) aceita múltiplas formas de resolver. |
| Rehearsal fica lento (5 runs com ~20 turnos cada, Gemini 2.5 Pro). | Sem mudança — mesmo custo operacional de hoje. |

---

## Decisões registradas

Durante a brainstorming, estas decisões foram tomadas (todas validadas pelo usuário):

| Decisão | Escolha |
|---|---|
| Propósito | Substituir personas (A), mantendo runner. Não é replay literal, não é híbrido. |
| Quantidade | 5 personas, uma por conversa real (alta fidelidade). |
| Hard checks | Operacionais + anti-alucinação (B). |
| Fragmentação | Turn-based 1-1 como hoje (A). |
| Proibições universais | A (PIX), B (preço+frete), C (prazo), E (desconto), H (papel). |
| Proibição específica R5 | D (ponto de venda físico) — sugestão do agente, aprovada. |
| Preservação dos antigos | Substituir in-place; git log serve de histórico. |
