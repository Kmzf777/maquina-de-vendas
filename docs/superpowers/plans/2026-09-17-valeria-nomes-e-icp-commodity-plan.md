# Plano — caixa alta de nomes próprios, fim do pedido de nome e ICP de commodity

Spec: `docs/superpowers/specs/2026-09-17-valeria-nomes-e-icp-commodity-design.md`
Branch: `worktree-valeria-humanizacao-nomes` (base `origin/master` = `1dd0f113`)

Quatro tarefas. 1 → 2 é sequencial (2 depende da função criada em 1). 3 e 4 são independentes
entre si e das demais (só tocam prompts + testes de prompt).

---

## Task 1 — `normalize_proper_nouns()` em `adherence.py` (TDD)

Criar a função pura em `backend/app/agent/adherence.py`, seguindo o padrão das guardas já
existentes no módulo (bloco numerado com comentário de auditoria, função pura, sem I/O).

```python
def normalize_proper_nouns(text: str, lead_name: str | None = None) -> str
```

Técnica: casar sobre o texto normalizado (`_normalize`, já existe no módulo) e substituir no
texto **original** — NFD + filtro de `Mn` preserva os índices de caracteres não-combinantes,
como já fazem `strip_prohibited_phrases` e `strip_consecutive_vocative_name`.

**Camada A — léxico inequívoco** (sempre capitaliza, fronteira de palavra):

| entrada (qualquer caixa/acento) | saída |
|---|---|
| `valeria`, `valéria` | `Valéria` |
| `joao bras`, `joão brás`, `joao brás`, `joão bras` | `João Brás` |
| `cafe canastra`, `café canastra` | `Café Canastra` |
| `canastra` (isolado, fora de "Serra da Canastra"/"Café Canastra") | `Canastra` |
| `nespresso` | `Nespresso` |
| `sca` | `SCA` |
| `uberlandia`, `uberlândia` | `Uberlândia` |
| `pratinha` | `Pratinha` |
| `serra da canastra` | `Serra da Canastra` |

Entradas mais longas têm precedência sobre as curtas (`serra da canastra` e `cafe canastra`
antes de `canastra`; `joao bras` antes de qualquer tratamento de `joao`).

**Camada B — produtos com porta de contexto:** `Clássico`, `Suave`, `Canela`, `Microlote`.

Capitaliza SOMENTE se:
- precedido de determinante masculino: `o`, `do`, `no`, `ao`, `um`, `pelo`, `nosso`; **ou**
- seguido de formato/preço: `moído`, `moido`, `em grãos`, `em graos`, `250g`, `500g`, `1kg`.

NUNCA capitaliza se precedido de: `torra`, `sabor`, `notas`, `nota`, `aroma`, `toque`,
`perfil`, `final`, `estilo`, `jeito`, `mais`, `bem`, `super`, `bastante`.
A regra de "nunca" tem precedência sobre a de "capitaliza".

**Camada C — nome do lead:** title-case do primeiro e do último token de `lead_name`, mínimo
3 caracteres por token, só como palavra isolada. Aplica mesmo se o cadastro estiver em
minúscula (`vanda` → `Vanda`). Se `lead_name` for `None`/vazio, a camada não roda.

**Não fazer:** cidades genéricas (`goiás`, `copacabana`). Registrar esse limite em comentário
na função — fica por conta do prompt.

**Fail-open:** qualquer exceção devolve o texto original.

### Testes (TDD — escreva-os primeiro, veja-os falhar)

Arquivo novo: `backend/tests/test_proper_nouns_2026_09_17.py`. Casos obrigatórios, todos
extraídos de produção:

Camada A:
- `"aqui é a valeria, do comercial da café canastra"` → `"aqui é a Valéria, do comercial da Café Canastra"`
- `"perfeito, eliatan, o joao bras que te ajuda"` (com `lead_name="Eliatan"`) → `"perfeito, Eliatan, o João Brás que te ajuda"`
- `"nosso café tem 84 pontos sca"` → `"... 84 pontos SCA"`
- `"cultivado na serra da canastra"` → `"... na Serra da Canastra"`
- `"centro de distribuição em uberlândia"` → `"... em Uberlândia"`
- idempotência: aplicar a função duas vezes dá o mesmo resultado
- texto já correto não é alterado (retorno idêntico)

Camada B — capitaliza:
- `"o suave moído 250g gira em torno de R$28,70"` → `"o Suave moído 250g ..."`
- `"o clássico é o nosso café com torra mais escura"` → `"o Clássico é o nosso café ..."` (o `o` inicial capitaliza; `torra mais escura` não é afetado)
- `"o canela é o nosso café com canela natural"` → `"o Canela é o nosso café com canela natural"` — **capitaliza o primeiro, preserva o segundo**

Camada B — NÃO capitaliza:
- `"esse café tem uma torra suave"` → inalterado
- `"notas de canela e caramelo"` → inalterado
- `"com canela natural"` → inalterado
- `"a adição natural da canela"` → inalterado (`da` é feminino, não entra na lista masculina)
- `"um sabor mais clássico"` → inalterado

Camada C:
- `lead_name="vanda"`, texto `"funciona assim, vanda"` → `"funciona assim, Vanda"`
- `lead_name="Jorge Eliseu"`, texto `"boa, jorge eliseu, que bom te ver"` → `"boa, Jorge Eliseu, ..."`
- `lead_name="Ana"` (3 letras) → aplica
- `lead_name="Jo"` (2 letras) → NÃO aplica
- `lead_name=None` → camada C não roda, camadas A e B seguem funcionando
- nome do lead que colide com palavra comum não deve quebrar o texto: `lead_name="Rosa"`, texto `"a rosa dos ventos"` → aceitável capitalizar; documente o comportamento escolhido em comentário

Rode a suíte inteira do backend ao final e reporte o número de testes.

---

## Task 2 — Ligar a guarda no pipeline de saída

Depende da Task 1.

**2a — `orchestrator.py`:** aplicar `normalize_proper_nouns` dentro de
`_sanitize_assistant_text` (`backend/app/agent/orchestrator.py:344`), logo **após**
`normalize_orthography` (hoje a última etapa, linha ~407). Esse é o funil de toda saída textual
do agente.

A assinatura atual é:

```python
def _sanitize_assistant_text(text: str, conversation_id: str, stage: str | None, source: str) -> str
```

Acrescente um parâmetro opcional `lead_name: str | None = None` ao final, para não quebrar as
7 chamadas existentes (linhas ~1239, 1310, 1455, 1481, 1486, 1528, 1619). Passe o nome do lead
nas chamadas onde a variável `lead` já está em escopo — a linha 1647 mostra o padrão
(`lead.get("name")`, usado por `strip_consecutive_vocative_name`). Onde `lead` não estiver em
escopo, deixe o default.

Logue no padrão do módulo quando a guarda alterar o texto (veja `[ORTHO GUARD]`, linha ~409):
`[PROPER NOUN GUARD]`, nível `debug`.

**2b — `tools.py`:** a `mensagem_despedida` do handoff não passa pelo funil acima — os três
pontos que enviam o texto do LLM direto são `backend/app/agent/tools.py:404`, `:841` e `:1164`
(variável `despedida`). Aplique `normalize_proper_nouns` ao valor de `despedida` nos três, com
o nome do lead quando disponível no escopo.

Essa é a mensagem que fecha o atendimento e nomeia o João — foi onde saiu
`"perfeito, eliatan, o joao bras que te ajuda"`.

**Fora de escopo:** corrigir o bypass das *demais* guardas de aderência nesse caminho. Só a
guarda de nomes entra aqui.

### Testes

Acrescente a `backend/tests/test_proper_nouns_2026_09_17.py` (ou arquivo irmão):
- `_sanitize_assistant_text` capitaliza os nomes do léxico (chamada direta, função testável)
- `_sanitize_assistant_text` com `lead_name` capitaliza o nome do lead
- `_sanitize_assistant_text` sem `lead_name` não quebra
- a ordem importa: a saída continua com acentuação de `normalize_orthography` aplicada
  (ex.: `"o cafe suave moido"` → `"o café Suave moído"`)

Rode a suíte inteira e reporte o número de testes.

---

## Task 3 — Prompt: caixa alta de nome próprio + parar de pedir o nome

Só prompts e testes de prompt. Não toca código de runtime.

**3a — hierarquia da caixa.** Em `backend/app/agent/prompts/base.py:686-693` (seção `## Estilo`)
a primeira linha é hoje:

```
- MINUSCULAS POR PADRAO. O primeiro caractere da bolha/frase NAO precisa ser maiusculo — esse e o padrao visual do WhatsApp humano. Nunca force maiuscula de abertura.
```

e a lista de exceções vem depois, em `- EXCECOES COM MAIUSCULA (obrigatorio — apenas nestes casos):`.

Inverta a hierarquia: enuncie **primeiro** que todo nome próprio é escrito com inicial
maiúscula (regra dura, inegociável), e só então que o resto do texto vai em minúscula,
explicitamente subordinado à regra anterior. Mantenha os exemplos concretos que já existem e
acrescente o caso de maior volume em produção — a própria saudação de abertura:

- CORRETO: `"aqui é a Valéria, do comercial da Café Canastra"`
- ERRADO: `"aqui é a valeria, do comercial da café canastra"`

Mantenha cidade/estado genérico no enunciado (a guarda determinística não cobre esse caso, só
o prompt cobre).

Aplique a mesma inversão em `backend/app/agent/prompts/voice_card.py:32-34`.

**3b — nunca pedir o nome.** Em `backend/app/agent/prompts/base.py:1139-1146`, o ramo "sem
nome" de `build_context_block` diz hoje:

```python
"Voce NAO sabe o nome do lead. Nao invente ou assuma. "
"Descubra naturalmente durante a conversa, como 'com quem eu estou falando?' ou 'qual seu nome?'. "
"Use a ferramenta salvar_nome assim que descobrir. "
```

Troque por: proibição explícita de **perguntar** o nome (o lead já preencheu formulário; pedir
de novo é atrito), instrução de seguir a conversa normalmente sem nome, e chamar `salvar_nome`
apenas se o lead disser o nome espontaneamente.

Ajuste também os textos que pressupõem que ela pergunta:
- `base.py:351-359` (*"Se voce ja perguntou 'com quem eu to falando?' / 'qual seu nome?' UMA vez…"*)
- checklist item 21, `base.py:1056` (*"Ja perguntei o nome do lead antes e ele nao respondeu?…"*)

**MANTENHA intacto** o ramo de correção de identidade — `base.py:299` e `base.py:1135`
(*"se o lead indicar que nao e a pessoa deste nome … pergunte de forma natural"*). Ali quem
levanta o assunto é o próprio lead; é reativo, não proativo, e sem isso ela fica presa a um
nome errado.

### Testes

Padrão do repositório: veja `backend/tests/test_base_prompt.py`. Acrescente testes que
verificam o **conteúdo do prompt gerado** (não o comportamento do LLM):
- `build_context_block(lead_name=None, ...)` NÃO contém `"qual seu nome"` nem `"com quem eu estou falando"`
- `build_context_block(lead_name=None, ...)` contém a proibição de perguntar
- `build_context_block(lead_name="Maria", ...)` continua contendo o ramo de correção de identidade
- o prompt base enuncia a regra de nome próprio ANTES da regra de minúsculas (compare índices de `.find()`)

Rode a suíte inteira e reporte o número de testes.

---

## Task 4 — Prompt: ICP de commodity + regra 7 exequível

Só prompts e testes de prompt. Independente da Task 3.

**4a — nova seção de ICP** em `backend/app/agent/prompts/valeria_inbound/atacado.py`,
espelhada em `backend/app/agent/prompts/valeria_outbound/atacado.py`. Use como modelo de
redação a seção de auto-produtor que já existe no outbound (`valeria_outbound/atacado.py:244-250`)
— é o único precedente de exclusão de ICP no repositório e define o tom.

Conteúdo:

**É sinal de commodity (fora do ICP):**
- pede café tradicional/commodity como o produto que quer comprar;
- quer "o mais barato", "o de menor preço";
- quer bater preço de supermercado ou de marca popular de commodity.

**NÃO é sinal (segue o atendimento normal):**
- pergunta a diferença entre as categorias ("café especial, gourmet ou tradicional?");
- diz que **hoje** vende tradicional e quer ampliar/migrar;
- pede o café mais próximo do tradicional — aí o Clássico atende.

**Ação:** UM reposicionamento ancorado em valor concreto (café especial vs commodity). Se o
lead REAFIRMAR que quer commodity/preço de supermercado, chame
`registrar_sem_interesse_atual(motivo="lead busca café commodity/tradicional — fora do ICP de café especial")`.
`encaminhar_humano` é **PROIBIDO** nesse caminho.

**Precedência explícita** — declare que esta regra sobrepõe as três que hoje empurram para o
handoff, nomeando-as:
- `## Objecao de preco — maximo 2 tentativas` / *"Handoff e vitoria"* (linha ~80)
- o turnaround ativo que proíbe `registrar_sem_interesse_atual` (linha ~290)
- o `## Circuit breaker` de 6 turnos (linhas ~14-18)

**4b — regra 7 exequível.** Em `backend/app/agent/prompts/base.py:141` a regra é hoje:

```
7. NUNCA DIZER "CAFE TRADICIONAL" — nossos cafes sao especiais.
```

Como está, é inexequível: quando o lead pergunta *"vocês têm tradicional?"*, ela precisa nomear
a categoria para responder — daí 64 violações em 57 leads nos últimos 90 dias. Reescreva para:
pode nomear a categoria do lead **uma única vez** para responder à pergunta dele; nunca
descrever café Canastra como tradicional. Aplique a mesma correção em
`backend/app/agent/prompts/voice_card.py:73`.

### Testes

- o prompt inbound de atacado contém a seção de ICP de commodity
- o prompt inbound de atacado nomeia `registrar_sem_interesse_atual` na seção de commodity
- o prompt inbound de atacado declara a precedência sobre o circuit breaker
- o prompt outbound de atacado contém a seção espelhada
- a regra 7 não é mais uma proibição absoluta (não contém `NUNCA DIZER "CAFE TRADICIONAL"`)

Rode a suíte inteira e reporte o número de testes.
