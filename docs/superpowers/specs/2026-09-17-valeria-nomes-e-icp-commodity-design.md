# ValerIA — caixa alta de nomes próprios, fim do pedido de nome e ICP de commodity

**Data:** 2026-09-17
**Branch:** `worktree-valeria-humanizacao-nomes`
**Base:** `origin/master` = `1dd0f113`

## Problema

Três defeitos reportados, todos confirmados contra a base de produção (Supabase self-hosted,
janela de 90 dias, medições de 17/09/2026).

### 1. A humanização em minúsculas achata nomes próprios

`base.py:686` abre a seção de estilo com **"MINUSCULAS POR PADRAO … Nunca force maiuscula de
abertura"**. A lista de exceções ("Nomes de pessoas", "marcas", "produtos", "siglas", "cidades")
vem logo abaixo, em `:688`, mas perde para a frase dominante. O modelo achata todo nome próprio.

| Grafia | Ocorrências | % |
|---|---|---|
| Nome dela minúsculo (`valeria` / `valéria`) | 341 | 22% de 1.538 auto-menções |
| Nome do lead minúsculo | 384 | 18,3% de 2.094 menções |

A saudação de abertura é o caso de maior volume: **340 mensagens** com
`"aqui é a valeria, do comercial da café canastra"`, apesar de o prompt escrever corretamente
`"aqui e a Valeria, do comercial da Cafe Canastra"` (`valeria_inbound/secretaria.py:81`).
No mesmo diálogo também caem `joao bras`, `clássico/suave/canela`, `goiás`, `uberlândia`, `sca`.

**Causa raiz:** falha de aderência do modelo a uma regra de prompt — a mesma classe de defeito
que o repositório já trata com guardas determinísticas em `app/agent/adherence.py`.

### 2. Ela ainda pede o nome do lead

8 ocorrências reais em 90 dias (última em 14/08/2026), sempre em `ord_ai` 2-6 (início do
atendimento). Origem: `base.py:1139-1146` — quando `sanitize_display_name()` devolve `None`,
o prompt manda descobrir o nome *"como 'com quem eu estou falando?' ou 'qual seu nome?'"*.

97% dos leads chegam com nome preenchido (formulário da LP ou pushname do WhatsApp), então o
ramo quase não é exercido — mas existe e dispara.

### 3. Leads de café commodity são qualificados, não descartados

| Coorte (90 dias) | Leads | Handoff p/ João | Descarte |
|---|---|---|---|
| Pediram tradicional/commodity | 116 | **82 (70,7%)** | 9 (7,8%) |
| Base geral que conversou | 2.321 | 1.321 (56,9%) | 117 (5,0%) |

Lead de commodity é encaminhado **14 pontos acima da média**. Em nenhum dos 82 handoffs o motivo
registrado menciona ICP.

**Causa raiz:** não existe regra de ICP para commodity nos prompts inbound. A única exclusão de
ICP escrita no repositório é a de auto-produtor, e só no prompt **outbound** de atacado
(`valeria_outbound/atacado.py:244`). Enquanto isso o prompt inbound empurra na direção oposta:

- `valeria_inbound/atacado.py:80` — *"chame encaminhar_humano … sem hesitar. Handoff e vitoria."*
- `valeria_inbound/atacado.py:290` — *"NAO aceite passivamente nem encerre com registrar_sem_interesse_atual (aplique turnaround ativo)."*
- `valeria_inbound/atacado.py:14-18` — circuit breaker: 6+ turnos em atacado ⇒ `encaminhar_humano(motivo="lead qualificado — atacado")`, *"incondicional e sobrepoe qualquer outra regra de fluxo"*.

Caso real (lead Eliatan, 14/09/2026): *"Preciso de café mais barato aqui a concorrência são
muitas"* → dois contornos → `[encaminhar_humano] objecao de preco apos 2 contornos` → cartão
**"NOVO LEAD QUALIFICADO PELA VALÉRIA"** entregue ao João.

**Defeito acoplado:** a regra 7 (`base.py:141`, *"NUNCA DIZER 'CAFE TRADICIONAL'"*) é
inexequível — quando o lead pergunta *"vocês têm tradicional?"* ela precisa nomear a categoria
para responder. Resultado: 64 violações em 57 leads, incluindo
*"a gente não trabalha com café tradicional, só com café especial"* (14/09).

## Decisões do usuário

1. **Commodity:** um reposicionamento; se o lead reafirmar, descarta. Nunca handoff.
2. **Caixa:** cobrir todos os nomes próprios, não só Valéria e o lead.
3. **Pedido de nome:** nunca perguntar de forma proativa.

## Desenho

### Componente 1 — `normalize_proper_nouns()` em `app/agent/adherence.py`

Função pura (sem I/O), no padrão das guardas existentes do módulo: casa sobre o texto
normalizado (NFD + minúsculas, filtrando `Mn`) e substitui no texto **original**, porque a
normalização preserva os índices de caracteres não-combinantes.

```python
def normalize_proper_nouns(text: str, lead_name: str | None = None) -> str
```

Três camadas:

**A. Léxico inequívoco** — capitaliza sempre, por fronteira de palavra:
`valeria`/`valéria` → `Valéria`; `joao bras`/`joão brás` → `João Brás` (e `joao`/`joão` isolado
quando seguido de `bras`/`brás`); `cafe canastra`/`café canastra` → `Café Canastra`;
`canastra` → `Canastra`; `nespresso` → `Nespresso`; `sca` → `SCA`;
`uberlandia`/`uberlândia` → `Uberlândia`; `pratinha` → `Pratinha`;
`serra da canastra` → `Serra da Canastra`.

**B. Produtos com porta de contexto** — `Clássico`, `Suave`, `Canela`, `Microlote`.
Medição em produção (45 dias) mostrou que a capitalização cega erraria muito:

| Palavra | Uso como produto | Uso como adjetivo/ingrediente |
|---|---|---|
| suave | 360 | 15 |
| clássico | 568 | 5 |
| **canela** | **191** | **214** |

Portanto capitaliza **apenas** em contexto de produto:
- precedido de determinante **masculino** (`o`, `do`, `no`, `ao`, `um`, `pelo`, `nosso`) — é o
  sinal que separa **o** Canela (produto) de **a** canela (especiaria);
- ou seguido de formato/preço (`moído`, `moido`, `em grãos`, `250g`, `500g`, `1kg`).

E **nunca** quando precedido de palavra de qualidade: `torra`, `sabor`, `notas`, `nota`,
`aroma`, `toque`, `perfil`, `final`, `estilo`, `jeito`, `mais`, `bem`, `super`, `bastante`.

**C. Nome do lead (dinâmico)** — title-case do primeiro e do último token de `lead_name`,
mínimo 3 letras por token, só como palavra isolada (fronteira de palavra). Cobre também o lead
cujo cadastro está em minúscula (`vanda` → `Vanda`), porque a fonte da capitalização é a regra,
não o banco.

**Limite declarado no código:** cidade genérica (`goiás`, `copacabana`) não é enumerável de
forma determinística e fica por conta do prompt (Componente 2). O léxico cobre só os lugares do
próprio negócio.

**Fail-open:** qualquer exceção mantém o texto original, como nas demais guardas do módulo.

### Componente 2 — prompt de caixa

`base.py:686-693` e `voice_card.py:32-34`: inverter a hierarquia. A exceção de nome próprio
passa a ser regra dura, enunciada **antes**, e a regra de minúsculas passa a ser explicitamente
subordinada a ela ("minúscula em tudo **exceto** nome próprio"). Incluir cidade/estado genérico
no enunciado, já que a guarda determinística não cobre esse caso.

### Componente 3 — parar de pedir o nome

- `base.py:1139-1146` (ramo "sem nome"): trocar *"Descubra naturalmente … 'qual seu nome?'"* por
  proibição explícita de perguntar, seguir sem nome, e chamar `salvar_nome` apenas se o lead
  disser espontaneamente.
- `base.py:351-359` e checklist item 21 (`:1056`): ajustar o texto que hoje pressupõe que ela
  pergunta ("Se voce ja perguntou … UMA vez").
- **Mantido:** `base.py:299` / `:1135` — correção de identidade, em que o **próprio lead** diz
  "não sou o Fulano". É reativo, não proativo, e sem ele ela ficaria presa a um nome errado.

### Componente 4 — ICP de commodity

Nova seção em `valeria_inbound/atacado.py` (espelhada em `valeria_outbound/atacado.py`):

**É sinal de commodity** (perfil fora do ICP):
- pede café tradicional/commodity como o produto que quer comprar;
- quer "o mais barato", "o de menor preço";
- quer bater preço de supermercado ou de marca popular de commodity.

**NÃO é sinal** (segue o atendimento normal):
- pergunta a diferença entre as categorias ("café especial, gourmet ou tradicional?");
- diz que **hoje** vende tradicional e quer ampliar/migrar;
- pede o café mais próximo do tradicional — aí o Clássico atende.

**Ação:** UM reposicionamento ancorado em valor concreto. Se o lead REAFIRMAR que quer
commodity/preço de supermercado →
`registrar_sem_interesse_atual(motivo="lead busca café commodity/tradicional — fora do ICP de café especial")`.
`encaminhar_humano` fica **proibido** nesse caminho.

**Precedência explícita** sobre as três regras que hoje empurram para o handoff: *"Handoff e
vitoria"* (`:80`), turnaround ativo (`:290`) e circuit breaker de 6 turnos (`:14-18`).

O motivo escolhido não contém nenhum sinal de `_ADIAMENTO_MORNO_SIGNALS`, então a guarda 18C
(`tools.py:942`) não aborta o descarte — verificado.

**Regra 7 vira exequível** (`base.py:141`, `voice_card.py:73`): pode nomear a categoria do lead
uma única vez para responder à pergunta dele; nunca descrever café Canastra como tradicional.

## Cobertura no pipeline

`_sanitize_assistant_text` (`orchestrator.py:344`) é o funil de toda saída textual do agente
(7 chamadas) — é lá que a guarda entra, logo após `normalize_orthography`.

A `mensagem_despedida` do handoff **não passa** por esse funil: `tools.py:404`, `:841` e `:1164`
enviam o texto do LLM direto. É a mensagem de maior visibilidade (fecha o atendimento e nomeia o
João), e foi justamente onde o caso Eliatan saiu como *"perfeito, eliatan, o joao bras que te
ajuda"* — com o nome do vendedor em minúscula **e** a palavra "perfeito", que a black-list do
prompt proíbe. A guarda de nomes é aplicada também nesses três pontos.

Corrigir o bypass inteiro das demais guardas nesse caminho está **fora de escopo** deste
trabalho e fica registrado como dívida.

## Testes

Seguem o padrão do repositório (`backend/tests/`, arquivo de auditoria datado):
`test_proper_nouns_2026_09_17.py`, alimentado com as frases reais de produção levantadas nesta
investigação — incluindo os casos ambíguos de "canela" nas duas direções.

## Fora de escopo

- Cidades genéricas na guarda determinística (só no prompt).
- O bypass das demais guardas de aderência no caminho da `mensagem_despedida`.
- Os 14 handoffs por "IA temporariamente indisponível" observados na coorte de commodity.
