# Rótulos das contas Bling e conta preferida na pré-seleção

Data: 2026-09-17
Branch: `feat/bling-rotulos-conta-preferida`
Antecedente: `docs/superpowers/specs/2026-09-13-bling-segunda-conta-design.md`

## Problema

Os dois CNPJs aparecem no CRM como **"CNPJ 1"** e **"CNPJ 2"** — nomes que
descrevem a ordem em que as contas foram criadas, não o negócio que cada uma
atende. Quem emite um pedido precisa traduzir mentalmente o número para a
empresa antes de escolher, e escolher errado só se descobre depois, no painel
do Bling.

Além disso, o volume de emissão hoje está no **Café Rural**, mas o seletor
sempre abre no Café Canastra — a conta que existe desde antes da segunda. Todo
pedido começa com uma troca manual de conta.

## Decisão

1. Os rótulos passam a ser **"Bling Café Canastra (1)"** e **"Bling Café Rural (2)"**,
   definidos no código.
2. O **Café Rural vira a conta pré-selecionada** em todo seletor de conta do CRM.
3. A **identidade** das contas não muda: o slug `default` continua sendo o Café
   Canastra, dono de todo registro histórico sem `bling_account`.

O ponto 3 é o que mantém o resto honesto, e merece o destaque: a palavra
"default" carrega dois significados que hoje estão colados no mesmo literal.

| Sentido | Onde vive | Nesta entrega |
|---|---|---|
| **Identidade** — slug da conta 1, gravado em vendas/contatos antigos, e prefixo das env vars sem sufixo | `venda.bling_account ?? CONTA_PADRAO`, `account()` do backend | **imutável** |
| **Preferência** — qual conta já vem marcada ao abrir um seletor | `contaPadrao()`, `useState(CONTA_PADRAO)` | passa a ser o Café Rural |

Separá-los em duas constantes é o núcleo do desenho. Colapsar os dois faria
toda venda anterior à segunda conta ser rotulada como Café Rural — dado
histórico mentindo sobre onde o pedido foi emitido.

## Escopo

### 1. Rótulos — `backend/app/bling/config.py`

```python
ROTULOS_PADRAO = {
    "default":    "Bling Café Canastra (1)",
    "secundaria": "Bling Café Rural (2)",
}
```

E em `account()`, a precedência **inverte** para as contas conhecidas:

```python
label = ROTULOS_PADRAO.get(key) or _env(_suffixed("LABEL", key)) or key
```

Uma linha cobre o CRM inteiro: toda tela renderiza `conta.label` como chega de
`GET /api/bling/status`, nenhuma delas constrói o nome por conta própria.

**Por que o código vence o env.** `BLING_LABEL` e `BLING_SECUNDARIA_LABEL` já
estão preenchidas no `.env` da VPS com os nomes antigos — é por isso que a tela
mostra "CNPJ 1"/"CNPJ 2" hoje, em vez do fallback cru (`"default"`/`"secundaria"`).
Com a precedência original o mapa novo seria ignorado em produção e a entrega
não teria efeito visível nenhum. Invertendo, o push basta: nada precisa ser
editado na VPS, e nada quebra se as variáveis antigas ficarem lá.

Um terceiro CNPJ futuro, cujo slug não está no mapa, continua lendo
`BLING_<CONTA>_LABEL` do env exatamente como antes — o escape hatch sobrevive
para quem ainda precisa dele.

### 2. Conta preferida — `frontend/src/lib/bling-accounts.ts`

Uma constante nova, irmã e não substituta da existente:

```ts
/** Slug de IDENTIDADE: a conta que existia antes da segunda, dona de todo
 *  registro sem bling_account e das env vars sem sufixo. NUNCA muda. */
export const CONTA_PADRAO = "default";

/** Slug PREFERIDO ao abrir um seletor. Decisão de negócio (o volume de
 *  emissão está no Café Rural), não de identidade — por isso é uma constante
 *  própria, e trocá-la não reescreve registro nenhum. */
export const CONTA_PREFERIDA = "secundaria";
```

`contaPadrao()` vira uma escada de quatro degraus, sempre restrita às contas
**conectadas**:

1. Café Rural (`CONTA_PREFERIDA`), se disponível
2. Café Canastra (`CONTA_PADRAO`), se disponível
3. a primeira conta disponível
4. `null`, quando nenhuma conta está conectada

O degrau 2 não é redundante: ele é o que faz a tela voltar para a conta que
todo mundo conhece se o Café Rural perder a autorização, em vez de cair numa
terceira conta arbitrária pela ordem do `BLING_ACCOUNTS`.

### 3. Os cinco seletores

| Tela | Pré-seleção hoje | Mudança |
|---|---|---|
| Modal de venda — `sales/bling-order-form.tsx:206` | `contaPadrao(contas)` | nenhuma: herda da escada |
| `/orcamento`, novo — mesmo `BlingOrderForm` | `contaPadrao(contas)` | nenhuma: herda da escada |
| `/config`, mapa de vendedores — `config/bling-settings.tsx:154` | `useState(CONTA_PADRAO)` + efeito que já chama `contaPadrao` | semente vira `CONTA_PREFERIDA` |
| `/produtos` — `app/(authenticated)/produtos/page.tsx:48` | `useState(CONTA_PADRAO)`, literal cru | semente + **efeito de reconciliação** |
| Painel Bling do lead — `leads/lead-bling-section.tsx:79` | `useState(CONTA_PADRAO)`, literal cru | semente + **efeito de reconciliação** |

Os dois primeiros saem de graça porque a seleção já é centralizada: ambos os
modais guardam `conta` como `null` e deixam o `BlingOrderForm` resolver via
`contaPadrao()`, propagando por `onChange`.

**O efeito de reconciliação não é enfeite.** `/produtos` e o painel do lead
semeiam o slug de forma síncrona e nunca conferem se aquela conta está
conectada. Trocar só a semente para `secundaria` cria uma armadilha real: se o
Café Rural estiver desconectado, a tela fica presa numa conta indisponível — e
o seletor **nem aparece** para escapar, porque `precisaSeletor` exige duas
contas disponíveis. O resultado seria catálogo vazio e painel de lead vazio,
sem saída visível. O efeito resolve isso caindo para uma conta disponível assim
que o status carrega, no mesmo padrão já em uso em `bling-settings.tsx:180`.

## Fora de escopo — e por quê

| Não muda | Razão |
|---|---|
| `venda.bling_account ?? CONTA_PADRAO` (`sale-create-modal.tsx:66`) | venda sem conta gravada nasceu no CNPJ 1; é o valor que um backfill usaria |
| `quote?.bling_account ?? CONTA_PADRAO` (`quote-create-modal.tsx:92`) | idem, para orçamentos anteriores à migration |
| `conta ?? CONTA_PADRAO` nos dois `BlingContactResolver` | caminho de zero contas conectadas; tem que casar com o default do backend |
| `seller-map/route.ts:47` | idem |
| `account()` sem argumento no backend | jobs, sync, webhooks e backfill continuam em `default` |
| Migration | nenhuma. Nenhuma linha de banco é lida ou reescrita |
| Slug `secundaria` | renomeá-lo obrigaria a reescrever `bling_account` em vendas, pedidos, contatos e produtos |

## Testes

**`backend/tests/test_bling_config.py`** — dois testes quebram por construção,
e é correto que quebrem:

- `test_label_cai_para_a_propria_key` espera `"secundaria"`; passa a valer para
  um slug **fora** do mapa.
- `test_label_le_do_env` espera o env vencer; passa a valer para um slug fora
  do mapa.
- **Novo:** o mapa vence o env nas duas contas conhecidas — a asserção que
  protege o objetivo desta entrega de uma regressão silenciosa na VPS.

**`frontend/src/lib/bling-accounts.test.ts`** — a escada de quatro degraus,
com ênfase no degrau 2: Café Rural desconectado tem que cair no Café Canastra,
não na primeira conta da lista.

**`frontend/src/app/(authenticated)/produtos/page.tsx` e
`leads/lead-bling-section.tsx`** — a lógica de reconciliação é testada em
`bling-accounts.test.ts` (é `contaPadrao` que decide); os componentes só a
consomem. Os `.test.tsx` deste repositório **não rodam nesta máquina**:
`jsdom` e `@testing-library` estão ausentes do `node_modules`. É uma limitação
conhecida do ambiente, não desta entrega.

## Riscos

1. **Rótulo aparece antes da pré-seleção.** Em `/config` as contas são
   listadas mesmo desconectadas, então os nomes novos aparecem lá assim que o
   backend sobe — independentemente de qualquer conta estar conectada.
2. **Validação em navegador toca produção.** O backend dev escreve no banco de
   produção. Conferir os seletores é leitura (catálogo, status, contatos);
   **criar venda ou orçamento de teste não é**, e fica fora da validação.
3. **Env antigo permanece na VPS.** Por desenho: `BLING_LABEL` e
   `BLING_SECUNDARIA_LABEL` ficam onde estão, apenas ignoradas para esses dois
   slugs. Quem ler o `.env` no futuro vai encontrar nomes que não batem com a
   tela — mitigado documentando a inversão em
   `docs/setup/bling-observacoes-producao.md`.

## Critério de pronto

- `/config` mostra "Bling Café Canastra (1)" e "Bling Café Rural (2)".
- Abrir o modal de venda, `/orcamento`, `/produtos` e o painel Bling de um lead
  já traz o Café Rural marcado.
- Uma venda antiga sem `bling_account` continua rotulada como Café Canastra.
- Suíte do backend e `bling-accounts.test.ts` verdes.
