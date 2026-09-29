# ValerIA de Botões — atendimento inbound 100% determinístico

**Data:** 2026-09-29
**Branch:** `feat/valeria-botoes` (nascida de `origin/master`)
**Artefatos de desenho:** [telas](https://claude.ai/artifact/J3t1jxSQRhHCfMHLSm7zdG) · [fluxo técnico](https://claude.ai/artifact/CG2Pss7xPQcHW55C9L6Upc)

---

## 1. Problema

A ValerIA LLM atende bem quem conversa, e perde quem não conversa. Medições já no repo:

- **48,6%** dos leads do anúncio ATACADO ficam presos em `pending` — morrem na triagem.
- **69,5%** dos leads nunca viram preço nem foto.
- Pergunta de **estado** tem 33,5% de resposta e 74% de positivos; pergunta de **compromisso**, 8,6% (`button_flow/flows.py`, medido em ~1.300 envios).

E um custo novo: **desde 01/10/2026 a Meta cobra por mensagem enviada inclusive dentro da janela de 24h.** O prompt atual é obrigado a picar a resposta em bolhas (`humanizer/splitter.py:5`, `MAX_BUBBLES = 3`; "um produto por mensagem separada" é regra escrita) e `enviar_fotos("atacado")` manda o catálogo inteiro — 6 arquivos em `photos/atacado/` são 6 mensagens.

## 2. Objetivo

Um atendimento inbound **sem nenhuma chamada de LLM**, da primeira mensagem do lead até o botão
*"gostaria de ser encaminhado ao vendedor?"*, cobrindo os 4 setores, fechando o score objetivo
por clique, e com as mensagens e rótulos **editáveis em tela** por quem não mexe em código.

Não-objetivo: substituir a ValerIA LLM. Ela continua existindo como perfil `kind='llm'` e segue
atendendo qualquer canal que aponte para ela.

---

## 3. Decisões tomadas (e o que elas fecham)

| Decisão | Alternativa recusada | Por quê |
|---|---|---|
| **Zero IA**, inclusive no texto livre | Classificador LLM na camada 2 | Pedido explícito. O `classifier.py` fica intocado e desligado neste fluxo. |
| **Estrutura no código, conteúdo no banco** | Canvas que cria/apaga/religa nós | `node_registry.py` documenta o custo do contrário: o builder de cadências "foi construído e NUNCA foi usado: 16 campanhas, 0 ativas, 0 matrículas na história", e toda falha tinha a mesma raiz — a tela grava uma chave e o motor lê outra. A aba Esteiras foi apagada por ser "um segundo editor sobre as mesmas tabelas". |
| **Valida ao salvar**, sem rascunho/publicar | Portão de publicação com N travas | Com a estrutura no código a superfície de erro é só texto. O único erro que emudece a ValerIA é rótulo > 20 caracteres ou mensagem vazia — guarda no `PUT`, não em cerimônia. |
| **Casamento por id**, com histórico de rótulos | Casamento por rótulo | Editar "Cafeteria" → "Sou cafeteria" não pode matar quem já recebeu a tela antiga. `meta_parser.py:161` já entrega o **id** no `payload`. Espelha o `rotulos_extras` que `flows.py` criou para esse exato problema. |
| **Liga/desliga por canal dentro do modal** | Seletor em `/canais` | O aviso do canal compartilhado (§7) precisa estar onde a troca acontece. |
| **Foto + preço + botões numa mensagem** | Foto, preço e pergunta separados | A mensagem interativa da Meta aceita header de imagem. Corta 2 mensagens faturadas por lead no ramo mais caro. |

---

## 4. Arquitetura

```
inbound  →  buffer/processor.py
                │  gate: is_button_flow_conversation() + flow_id do perfil
                ▼
         button_flow/valeria_runner.py        (I/O: banco, Meta, efeitos)
                │
                ├─ valeria_registry.py        (ESTRUTURA — dado puro, sem I/O)
                ├─ valeria_content.py         (CONTEÚDO — overrides do banco)
                └─ valeria_engine.py          (DECISÃO — função pura)
                        │
                        ▼
                   Decisao(mensagem, efeitos, proximo_no)
```

O motor é um **intérprete do registry**: acha o nó, casa o clique com um botão declarado,
devolve o destino declarado. Porque a estrutura é dado, a decisão não é uma matriz de `if` —
são ~150 linhas genéricas, não as ~500 que uma matriz nó × clique de 15 nós exigiria.

### 4.1 `button_flow/valeria_registry.py` (novo)

Espelha o papel de `campaigns/node_registry.py`: o contrato único entre a tela e o motor.
Dado puro, sem I/O, sem importar o motor (senão fecha ciclo).

```python
FLOW_ID = "valeria_botoes_v1"

@dataclass(frozen=True)
class Botao:
    id: str              # contrato estável. o rótulo muda, o id não.
    rotulo: str          # DEFAULT. a tela sobrescreve.
    destino: str         # id do nó de destino. NÃO editável na tela.
    grava: tuple = ()    # ex: (("segment", "cafeteria"),) — campos do score

@dataclass(frozen=True)
class No:
    id: str
    rotulo_interno: str      # "N1 · Segmento" — só tela e log
    tela: str                # "botoes" | "lista" | "foto_botoes" | "texto"
    corpo: str               # DEFAULT do texto. a tela sobrescreve.
    botoes: tuple[Botao, ...]
    editaveis: tuple[str, ...] = ("corpo", "rotulos")
    foto: str | None = None  # caminho em photos/, quando tela == "foto_botoes"
    ramo: str                # "entrada" | "atacado" | "private_label" | "consumo" | "exportacao"
```

**17 nós de conversa + 6 terminais = 23**, agrupados em 5 ramos. Contagem exata: `N0` (1),
`N1`–`N5` + `N5b` (6), `P1`–`P4` + `P4b` (5), `C1` (1), `E1`–`E4` (4) = 17.

> **Corrigido em 29/09/2026, na execução.** Esta seção dizia 15 + 5 e a conta estava errada
> duas vezes: omitia `N5b`/`P4b` — que a própria §5 exige como destino de "Ver outras
> opções" — e omitia o terminal `T_OPTOUT`, que a §6 descreve mas a tabela de terminais não
> listava. Os dois furos têm a mesma causa: `N5b`, `P4b` e `T_OPTOUT` estão **fora do
> caminho principal**, então a contagem feita seguindo o caminho felizes não os viu. Os
> terminais são 6: `T_HANDOFF`, `T_HANDOFF_ARTHUR`, `T_ADIAR`, `T_HUMANO`, `T_FIM`,
> `T_OPTOUT`. As contagens de MENSAGEM por ramo da §5 seguem corretas, porque elas contam o
> caminho principal.

**Limites declarados no módulo, porque são limites da Meta e não preferências:**
`LIMITE_ROTULO_BOTAO = 20`, `LIMITE_TITULO_LISTA = 24`, `LIMITE_DESC_LISTA = 72`,
`MAX_BOTOES = 3`, `MAX_LINHAS_LISTA = 10`.

**Teste espelho do `test_node_registry.py`:** cruza o registry com o motor. Todo `destino`
precisa ser um nó existente ou um terminal declarado; todo nó precisa ser alcançável da
entrada; nenhum nó de `tela == "botoes"` pode ter mais de 3 botões. Isso é o que impede
fluxo órfão de entrar por refactor.

### 4.2 `valeria_flow_content` (tabela nova)

```sql
create table valeria_flow_content (
  id          uuid primary key default gen_random_uuid(),
  flow_id     text not null,
  node_id     text not null,
  corpo       text,                      -- null = usa o default do registry
  rotulos     jsonb,                     -- {botao_id: "rótulo"} — chaves ausentes usam o default
  rotulos_antigos jsonb default '[]',     -- histórico, para clique de tela antiga resolver
  updated_at  timestamptz default now(),
  updated_by  uuid references auth.users(id),
  unique (flow_id, node_id)
);
```

**Linha ausente = default do registry.** O fluxo roda com a tabela vazia. Isso não é
conveniência: migration pendente é um modo de falha recorrente neste repo (várias memórias
de projeto registram migration não aplicada), e aqui ele não pode emudecer a ValerIA.
`valeria_content.carregar(flow_id)` devolve `{}` em qualquer erro e loga — fail-open.

### 4.3 `valeria_engine.py` (novo, função pura)

Reusa de `button_flow/engine.py`: `Clique`, `Texto`, `Decisao`, `Mensagem`, `Efeitos`,
`normalizar`. **Não estende `decidir()`**: aquela função tem a matriz da recuperação embutida
(`NO_INTERESSE`, `NO_PRAZO`, trilhas), e enfiar um segundo fluxo ali é o acoplamento que o
próprio repo já pagou.

```python
def decidir(no_atual: str, evento: Evento, estado: dict, nos: dict, terminais: dict) -> Decisao
```

Ordem de avaliação, e ela importa:

1. **Opt-out por lista fechada de strings** (§6). Antes de tudo.
2. **Clique** → casa `payload` com um `Botao.id` do nó atual; se não casar por id, tenta os
   `rotulos_antigos`; grava o que o botão declara em `grava`; vai para `destino`.
3. **Texto livre** → nudge (§6).

### 4.4 `whatsapp/meta.py`

- **`send_interactive_list`** (novo). `N0` tem 4 opções e `E1` tem 6; hoje só existe o caminho
  de 1 a 3 botões (`meta.py:326` levanta acima de 3).
- **`send_interactive_buttons` ganha `image_url` opcional** → header de imagem. É o que funde
  foto + preço + botões numa mensagem só.

### 4.5 `webhook/meta_parser.py` — correção obrigatória

`meta_parser.py:164` rebaixa `list_reply` para `parsed_type = "text"`, com o comentário
*"Listas estão fora do escopo do bot de botões — segue como texto"*. Com `N0` e `E1` sendo
listas, clique em opção chegaria ao motor **como texto livre e dispararia nudge em vez de
avançar** — o fluxo morreria na entrada. Passa a ser:

```python
elif interactive_type == "list_reply":
    reply = interactive.get("list_reply", {})
    text = reply.get("title", "")
    parsed_type = "button"
    metadata_dict = {"payload": reply.get("id") or text, "title": text}
```

Isso é compatível com a recuperação: `e_clique_de_botao` (`runner.py:120`) prova o clique pela
presença de `payload`, não pelo `message_type`.

---

## 5. O fluxo

Entrada comum, 4 ramos que não se cruzam, cada um terminando no botão de encaminhamento.
Contagem = mensagens faturadas por lead.

### Entrada
**`N0` · setor** — `tela: lista`, 4 linhas com descrição
> oi! aqui é a Valéria, do comercial da Café Canastra ☕ / pra eu já te levar pro que importa e não te encher de coisa que não tem a ver com você, me diz: o café é pra qual caso?

| linha | destino |
|---|---|
| Pro meu negócio · *revenda, cafeteria, restaurante, hotel* | `N1` |
| Com a minha marca · *café embalado com a sua logo* | `P1` |
| Pra consumo próprio · *em casa ou de presente* | `C1` |
| Pra exportação · *mercado externo* | `E1` |

Lista e não botão por dois motivos: 4 opções não cabem em 3 botões, e a linha de lista aceita
descrição — o botão não.

### Ramo A · Atacado → João Brás · **8 mensagens** · fecha o score

| Nó | Corpo | Botões | Grava |
|---|---|---|---|
| `N1` segmento | que tipo de negócio você tem? | `Cafeteria` / `Loja ou empório` / `Outro tipo` | `segment` = cafeteria(2) / emporio(1) / other(0) |
| `N2` volume | quanto café você usa por mês, mais ou menos? | `Até 30 kg por mês` / `30 a 100 kg` / `Mais de 100 kg` | `monthly_volume_kg` = 30(1) / 65(0) / 150(0) |
| `N3` fornecedor | e hoje, como tá o seu fornecimento de café? | `Quero trocar` / `Quero um segundo` / `Ainda não vendo café` | `supplier_reason` = replace(2) / second_supplier(0) / start_specialty_coffee(0) |
| `N4` prazo | última coisa: pra quando você precisa? | `Próximos 15 dias` / `Este mês ou o outro` / `Ainda sem data` | `purchase_timing` = within_15_days(1) / days_16_30(0) / no_timeline(0) |
| `N5` entrega | `tela: foto_botoes` — foto + preço + a pergunta de encaminhamento | `Sim, quero falar` / `Ver outras opções` / `Não agora` | `purchase_intent` = clear(2) / — / unclear(0) |

**Qual produto o `N5` mostra — e por que não depende do segmento.** O nó declara o produto no
registry (`N5` → Clássico 250g; `N5b` → Suave 250g), e o `N5b` é o destino de
`Ver outras opções`. **Não** existe escolha de produto em tempo de execução a partir do
segmento: isso seria uma regra implícita que a tela não mostra e o motor teria que adivinhar —
a classe exata de divergência que `node_registry.py` documenta. Quem quiser mudar o produto
mostrado muda o registry, não os dados.

**`Ver outras opções` vai para `N5b` e o `N5b` não tem esse botão** — é assim que "uma vez só"
é garantido pela estrutura, sem contador nenhum no estado. O `N5b` oferece
`Sim, quero falar` / `Não agora`, e nada mais. Um contador seria estado a mais para o teste
cobrir e para o operador entender; a topologia resolve de graça.

**Preço sai do catálogo em tempo de envio, nunca do texto.** O corpo editável na tela traz um
marcador (`{preco}`), resolvido pelo runner contra `products` no instante do envio, e a regra de
`atacado.py` continua valendo — qualificador obrigatório ("gira em torno de") com o valor exato
em centavos. Se o produto declarado não casar com SKU ativo, **o runner não cota**: manda o
corpo sem a linha de preço, como `flows.py` já faz com `MSG_QUENTE_SEM_PRECO`. Cotar de memória
foi o que perdeu as 500 unidades da Ritz.

### Ramo B · Private Label → João Brás · **7 mensagens** · 45% dos leads

| Nó | Corpo | Botões |
|---|---|---|
| `P1` marca | você já tem uma marca criada ou tá pensando em lançar do zero? | `Já tenho a marca` → `P2` / `Quero criar do zero` → `P2` / `Já tenho os grãos` → **handoff direto** |
| `P2` lote | quantos pacotes você pensa por lote? | `Até 100 pacotes` / `100 a 500` / `Mais de 500` |
| `P3` prazo | pra quando você quer lançar? | `Próximos 30 dias` / `Em 2 ou 3 meses` / `Ainda sem data` |
| `P4` entrega | `foto_botoes` — embalagem + a pergunta | `Sim, quero falar` / `Ver outra opção` / `Não agora` |

`Já tenho os grãos` é atalho porque é serviço de torra e envase, não projeto de marca — espelha
o fluxo de "Graos de Terceiros" que `private_label.py` já trata como exceção do circuit breaker.

**`P4` não traz número de preço.** O valor do private label muda por lote e não há SKU fixo;
cotar de memória é o erro que já custou as 500 unidades da Ritz (documentado em `flows.py`).
O corpo diz que o valor sai do catálogo conforme o lote.

### Ramo C · Consumo → loja online · **2 mensagens**

**`C1`** — link e cupom **na mesma mensagem** (hoje são 3 bolhas por regra atômica do prompt):
> nossa linha completa tá na loja online, e vou te deixar um cupom de 10% de desconto pra usar lá 🎟️ / 🔗 loja.cafecanastra.com / cupom: **ESPECIAL10** / qualquer dúvida sobre os cafés, me chama aqui.

`Quero em quantidade` → `N1` (vira atacado) · `Tenho uma dúvida` → `T_HUMANO`
Sem clique: encerra. **Sem descarte, `opt_out` continua false** — espelha a regra
"Consumo não é encerramento definitivo" de `consumo.py`.

### Ramo D · Exportação → Arthur · **7 mensagens**

`E1` destino (`lista`, 6 mercados) → `E2` estrutura (`Pelo meu CNPJ` / `Vocês exportam` /
`Ainda não sei`) → `E3` objetivo (`Comprar e revender` / `Ser representante`) → `E4`
encaminhamento (`Sim, quero falar` / `Não agora`).

As três perguntas são exatamente as três informações que `exportacao.py` coleta hoje.

### Terminais

| Terminal | Efeito |
|---|---|
| `T_HANDOFF` | `encaminhar_humano(vendedor="João Brás")` + cartão de contato (**só se o canal não for o do próprio João** — a regra `canal_do_vendedor` de `engine.py:317`) · tag · score gravado · `ai_enabled=false` |
| `T_HANDOFF_ARTHUR` | idem, `vendedor="Arthur"` |
| `T_ADIAR` | reusa `flows.PRAZOS` (`Em 30/60/90 dias`) → `agendar_retorno`, tag, encerra. **Não descarta.** Medido: 4 de 9 "ainda tenho estoque" voltaram e um fechou R$ 5.500. |
| `T_HUMANO` | `ai_enabled=false` + tag + fila. 0 mensagens. |
| `T_FIM` | encerra sem descarte. 0 mensagens. |

### Custo

| Ramo | Hoje (estimativa de composição) | Botões (exato) |
|---|---|---|
| Atacado | ~22 (triagem 6 · dor 4 · **6 fotos** + 1 · 3 preços · handoff 2) | **8** |
| Private label | ~19 (triagem 6 · pílulas 5 · **4 fotos** · 2 · 2) | **7** |
| Consumo | ~10 | **2** |
| Exportação | ~16 | **7** |
| Pior caso | — | **+3** (nudges) |

---

## 6. Trava anti-spam

Sem IA, texto livre não é interpretado — é respondido com o mesmo nó.

```
texto 1 → reenvia o MESMO nó   (nudge 1)   +1 msg
texto 2 → reenvia o MESMO nó   (nudge 2)   +1 msg
texto 3 → reenvia o MESMO nó   (nudge 3)   +1 msg
texto 4 → BLOCK
```

- **`nudges: int` no `flow_state`**, teto 3. Hoje `engine.py:400` lê `nudged` como booleano e
  entrega ao humano no primeiro texto. O campo novo é do fluxo da ValerIA; o `nudged` da
  recuperação fica como está.
- **Contador por atendimento, não por nó.** Por nó, 15 nós dariam 45 nudges — o desperdício
  máximo passaria de 3 para 45 mensagens.
- **`BLOCK` = `_ENTREGAR_AO_HUMANO`** (`engine.py:297`): silencia a IA, marca a tag, entra na
  fila. **Não é blacklist.** Quem digita 3 vezes é quem quer falar; descartar esse lead é a
  perda de 26% que a auditoria do funil mediu.
- Corpo do nudge: `pra eu te passar o valor certo, é só tocar numa das opções 👇` + os mesmos
  botões. Editável na tela como qualquer outro corpo.

### Opt-out sem IA — o degrau antes do contador

Sem modelo, ninguém detecta "pare de me mandar mensagem" em texto livre, e a Meta exige honrar
esse pedido. Então o primeiro degrau é uma **lista fechada de strings**, conferida com o
`normalizar()` que já existe (`engine.py:113`): `pare`, `parar`, `sair`, `me tira`,
`descadastrar`, `remover`, `não quero mais`. Casamento por igualdade normalizada, não substring
— "não quero trocar de fornecedor" não pode virar opt-out.

Casou → `registrar_optout` imediato, **sem gastar nudge**.

---

## 7. O perfil no CRM e a troca do número

### Como fica

`agent_profiles` já tem a coluna `kind` (`'llm' | 'button_flow'`, migration
`20260820_button_flow_agent.sql`). A ValerIA de botões é **uma linha nova**:

| Perfil | `kind` | `flow_id` | Quem atende |
|---|---|---|---|
| Valéria (atual) | `llm` | — | `valeria_inbound/*` + orchestrator |
| Recuperação | `button_flow` | `recuperacao_v1` | `flows.py` |
| **Valéria Botões** | `button_flow` | `valeria_botoes_v1` | `valeria_registry.py` + conteúdo |

### Coluna nova: `agent_profiles.flow_id`

`kind='button_flow'` hoje só sabe de um fluxo — o `runner` assume a recuperação. Com dois, o
perfil precisa dizer qual. **Não reaproveitar `prompt_key`**: nome com dois significados é
exatamente a classe de bug que `node_registry.py` documenta. `flow_id` nulo = `recuperacao_v1`,
para compatibilidade com o perfil que já existe.

### Precedência da troca (`runner.py:105`, inalterada)

1. **`conversations.agent_profile_id`** — ganha. É o que o disparo grava.
2. **`channels.agent_profile_id`** — o default do número.

### As três armadilhas, e o que o desenho faz com cada uma

**1. Valéria e João compartilham o mesmo perfil.** `runner.py:96`: *"o canal do João
(`a3a607b1`) já aponta para o MESMO `agent_profile_id` do canal da ValerIA (`674beb13`,
verificado em produção 09/09)"*. Editar o `kind` do perfil atual viraria o número do João em bot
junto. → **O modal nunca edita perfil existente.** O botão "Ativar" *cria* um perfil novo e
aponta só o canal escolhido. E a aba mostra o aviso quando o canal selecionado compartilha
perfil com outro canal.

**2. Uma env var liga os dois fluxos.** `is_button_flow_conversation` abre com
`if not config.enabled()`, e `config.enabled()` lê `RECUPERACAO_ENABLED`. Ligar a ValerIA por
essa chave **armaria a Recuperação junto** — que está desligada e tem 3 bloqueantes pendentes.
→ **`config.enabled()` passa a receber o `flow_id`**: `enabled("valeria_botoes_v1")` lê
`VALERIA_BOTOES_ENABLED`, `enabled("recuperacao_v1")` continua lendo `RECUPERACAO_ENABLED`.
Ambos default **off**.

**3. Cache de 5 minutos.** `_KIND_TTL_SEGUNDOS = 300`. Trocar o perfil leva até 5 min pra valer.
→ O "Ativar" chama `limpar_cache_de_perfis()` (já existe, `runner.py:70`) e o modal diz que a
troca vale na hora.

---

## 8. O modal em `/campanhas`

Botão no header ao lado de "Score da Valéria" (`page.tsx:196`), mesmo padrão do
`ValeriaScoreModal`. Componente `ValeriaFlowModal`.

### Aba 1 · Fluxo (o editor)

Três colunas:

```
┌─ ramos ─────┬─ nós do ramo ──┬─ editor + preview ──────────┐
│ ▸ Entrada   │  N1 · Segmento │  mensagem                   │
│ ▾ Atacado   │  N2 · Volume   │  ┌───────────────────────┐  │
│   Marca     │  N3 · Forneced.│  │ que tipo de negócio…  │  │
│   Consumo   │  N4 · Prazo    │  └───────────────────────┘  │
│   Exportação│  N5 · Entrega  │  botão 1 [Cafeteria    ] →N2│
│ ▸ Terminais │                │  botão 2 [Loja ou empó.] →N2│
│             │                │  botão 3 [Outro tipo   ] →N2│
│             │                │  ─────────────────────────  │
│             │                │  PREVIEW  (bolha real)      │
└─────────────┴────────────────┴─────────────────────────────┘
```

- **Preview de WhatsApp ao vivo** ao lado do editor, reusando o CSS das telas aprovadas: edita o
  rótulo, vê a bolha mudar. É o que torna o modal usável por quem não lê código.
- O destino de cada botão é **exibido e não editável** (`→ N2`), para o editor entender o efeito
  sem poder quebrar o grafo.
- **Contador de caracteres** por rótulo, com o limite da Meta visível (20). Salvar bloqueado
  acima disso — a guarda que impede a ValerIA de emudecer.
- Botão "Restaurar o texto original" por nó: apaga o override e volta ao default do registry.

### Aba 2 · Onde está ativo

```
Valéria · 5534xxxxxxx      atendimento: [ Botões ▾ ]
  ⚠ este perfil também atende o número do João — "Ativar"
    cria um perfil novo e aponta só este canal

João · 553491461669        atendimento: [ LLM ▾ ]

[ Ativar a Valéria de botões neste canal ]
```

O "Ativar" faz, numa transação: cria o perfil `kind='button_flow'`,
`flow_id='valeria_botoes_v1'` → `PATCH /api/channels/{id}` com o id novo →
`limpar_cache_de_perfis()`.

### Rotas

| Rota | O que faz |
|---|---|
| `GET /api/valeria-flow` | registry + conteúdo **já mesclado** — a tela nunca mescla, para não haver duas versões da regra de default |
| `PUT /api/valeria-flow/{node_id}` | grava `corpo` e `rotulos`; valida limites; move o rótulo anterior para `rotulos_antigos` |
| `DELETE /api/valeria-flow/{node_id}` | apaga o override (restaura o default) |
| `GET /api/valeria-flow/channels` | canais + perfil atual + flag de perfil compartilhado |
| `POST /api/valeria-flow/activate` | cria perfil, aponta canal, limpa cache |

---

## 9. Mudanças, arquivo por arquivo

| Arquivo | Mudança | Risco |
|---|---|---|
| `button_flow/valeria_registry.py` | **novo** — 15 nós + 5 terminais, dado puro | baixo |
| `button_flow/valeria_engine.py` | **novo** — intérprete do registry, função pura | baixo |
| `button_flow/valeria_content.py` | **novo** — carrega overrides, fail-open | baixo |
| `button_flow/valeria_runner.py` | **novo** — I/O, efeitos, envio | médio |
| `button_flow/config.py` | `enabled()` passa a receber `flow_id` | **alto** — mexe no gate da recuperação |
| `button_flow/runner.py` | `is_button_flow_conversation` devolve o `flow_id`, não só bool | **alto** — mesmo gate |
| `whatsapp/meta.py` | `send_interactive_list`; `image_url` no `send_interactive_buttons` | baixo |
| `webhook/meta_parser.py` | `list_reply` → `parsed_type="button"` com o id | médio — toca o parser de produção |
| `buffer/processor.py` | roteia para o runner da ValerIA quando o `flow_id` casar | **alto** — caminho de todo inbound |
| `campaigns/router.py` | 5 rotas novas de `/api/valeria-flow` | baixo |
| `frontend/.../valeria-flow-modal.tsx` | **novo** — o modal | baixo |
| `frontend/.../campanhas/page.tsx` | botão no header + estado do modal | baixo |
| `frontend/src/app/api/valeria-flow/*` | proxies das rotas | baixo |

**Os três `alto` são o mesmo risco:** o gate de inbound. Mitigação: `VALERIA_BOTOES_ENABLED`
default off, e `is_button_flow_conversation` mantém o **fail-open** que já tem — qualquer erro
devolve "não é fluxo de botões" e o inbound segue o caminho normal. Fail-closed sequestraria
conversa humana num erro de leitura.

## 10. Migration

`supabase/migrations/20260929_valeria_botoes.sql`

1. `create table valeria_flow_content` (§4.2) + RLS: leitura para autenticado, escrita para admin.
2. `alter table agent_profiles add column flow_id text` — nulo = `recuperacao_v1`.
3. Tags novas: `Botões: Qualificado`, `Botões: Adiado`, `Botões: Atendimento humano`,
   `Botões: Opt-out`. Semeadas como as de `flows.py` — **por nome exato**, porque
   `add_tags_to_lead` resolve por nome e devolve em silêncio se não achar.

**A migration não é pré-requisito para o código subir.** Sem ela: `valeria_flow_content` não
existe → `carregar()` falha → fail-open → o fluxo roda com os defaults do registry. E `flow_id`
ausente → o perfil novo não pode ser criado, então o "Ativar" falha com mensagem clara em vez
de ativar errado.

## 11. Testes

- `test_valeria_registry.py` — **o teste que segura o desenho**: todo `destino` existe; todo nó
  é alcançável da entrada; nenhum nó `botoes` passa de 3; todo rótulo default cabe em 20
  caracteres; todo `grava` usa campo e valor válidos de `lead_score.model.CRITERIA_FIELDS` e dos
  enums de `qualificar_lead`.
- `test_valeria_engine.py` — matriz nó × evento **sem nenhum mock**, como `engine.py` já
  permite: clique válido, clique de rótulo antigo, texto livre 1/2/3/4, opt-out em cada nó,
  `Ver outras opções` duas vezes (a segunda não pode voltar).
- `test_valeria_content.py` — override aplicado; linha ausente cai no default; erro de banco cai
  no default; limite de caracteres rejeitado no `PUT`.
- `test_meta_parser.py` — `list_reply` produz `parsed_type="button"` com o id; `button_reply`
  segue igual (regressão da recuperação).
- `test_config.py` — `enabled("valeria_botoes_v1")` e `enabled("recuperacao_v1")` são
  independentes; ambos off por default.
- Frontend: `valeria-flow-modal.test.tsx` — contador de caracteres bloqueia salvar; preview
  reflete a edição; aviso de perfil compartilhado aparece.
  **Nota:** `@testing-library` e `jsdom` estão ausentes do `node_modules` deste repo (registrado
  em duas memórias de projeto) — os `.test.tsx` não rodam sem instalar antes.

## 12. Fora de escopo

- Substituir a ValerIA LLM. Ela continua como perfil `llm`.
- Editar a **estrutura** do fluxo em tela (criar/apagar/religar nós) — §3.
- O `classifier.py` (camada 2 de LLM). Fica intocado e não é chamado.
- Orçamento em US$/dia ou livro-caixa de custo por mensagem. A trava pedida é o teto de 3
  nudges; contabilidade de custo é projeto próprio.
- Evolution API (obsoleto por CLAUDE.md §6).
