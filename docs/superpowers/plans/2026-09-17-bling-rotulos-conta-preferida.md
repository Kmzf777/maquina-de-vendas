# Rótulos das contas Bling e conta preferida — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Renomear as contas Bling para "Bling Café Canastra (1)" e "Bling Café Rural (2)" e fazer o Café Rural ser a conta pré-selecionada em todos os seletores do CRM, sem tocar na identidade histórica dos registros.

**Architecture:** Duas mudanças independentes que se encontram na tela. No backend, um mapa `ROTULOS_PADRAO` por slug consultado **antes** do env em `account()` — uma linha que cobre o CRM inteiro, porque toda tela renderiza `conta.label` como chega de `GET /api/bling/status`. No frontend, uma constante nova `CONTA_PREFERIDA = "secundaria"`, irmã e não substituta de `CONTA_PADRAO = "default"`, que separa o sentido de *preferência* do sentido de *identidade* — os dois hoje colados no mesmo literal. `contaPadrao()` passa a ser uma escada de quatro degraus, e os dois seletores que semeiam o slug de forma síncrona ganham um efeito de reconciliação.

**Tech Stack:** Python 3.12 + pytest (backend), Next.js 16 App Router + React 19 + TypeScript + vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-09-17-bling-rotulos-conta-preferida-design.md`

---

## Comandos de teste

```bash
# Backend (rodar de dentro de backend/)
cd backend && python -m pytest tests/test_bling_config.py -v

# Frontend (rodar de dentro de frontend/)
cd frontend && npx vitest run src/lib/bling-accounts.test.ts
cd frontend && npx tsc --noEmit       # equivale ao script "type-check" do package.json
```

**Baseline verificado em 2026-09-17, antes de qualquer mudança:**
`test_bling_config.py` → 37 passed. `bling-accounts.test.ts` → 18 passed.

**CORREÇÃO 2026-09-17 (durante a execução).** A versão original deste plano
dizia que os `.test.tsx` "não rodam nesta máquina" e mandava ignorá-los. Isso
estava **errado e era perigoso**, por dois motivos descobertos na Onda A:

1. O `node_modules` estava incompleto (faltavam `jsdom` e `@testing-library/*`,
   ambos **declarados** no `package.json`). É um defeito do ambiente local, não
   uma propriedade do projeto — resolvido com `cd frontend && npm ci`, que é
   exatamente o que o CI faz.
2. `.github/workflows/deploy.yml:49-52` roda `npm run test` como
   **gate bloqueante de deploy** ("qualquer teste vermelho impede o deploy").
   Um `.test.tsx` desatualizado não é dívida silenciosa: trava a subida para
   produção.

E três arquivos de teste de componente **afirmam o comportamento que esta
entrega inverte**. Eles não estavam em task nenhuma do plano original:

| Arquivo | O que afirma | Quebra por causa da |
|---|---|---|
| `components/sales/bling-order-form.test.tsx:109` | `toHaveBeenCalledWith(CONTA_PADRAO)` com as duas contas conectadas | Task 2 |
| `components/config/bling-settings.test.tsx` (~156, ~172, ~192) | espera abrir em "João do CNPJ 1" e depois trocar para `secundaria` | Task 3 |
| `components/leads/lead-bling-section.test.tsx:57` | teste chamado *"comeca na conta DEFAULT"* | Task 5 |

`/produtos` não tem arquivo de teste — nada a corrigir lá.

As Tasks 3 e 5 passam a incluir o conserto do seu próprio teste, e nasce a
**Task 7** para o `bling-order-form.test.tsx`. Depois do `npm ci`, **todos os
comandos de teste desta seção rodam de verdade** — inclusive `npx vitest run`
completo, que é o que o gate de deploy executa.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `backend/app/bling/config.py` | Resolve slug → `BlingAccount`. Ganha o mapa de rótulos. | Modificar |
| `backend/tests/test_bling_config.py` | Suíte da config. Dois testes mudam de alvo, um nasce. | Modificar |
| `frontend/src/lib/bling-accounts.ts` | Lógica pura de seleção de conta. Ganha `CONTA_PREFERIDA` e a escada. | Modificar |
| `frontend/src/lib/bling-accounts.test.ts` | Suíte da lógica pura. | Modificar |
| `frontend/src/components/config/bling-settings.tsx` | `/config`: cards de status + mapa de vendedores. | Modificar (1 linha) |
| `frontend/src/app/(authenticated)/produtos/page.tsx` | Catálogo por conta. | Modificar (semente + efeito) |
| `frontend/src/components/leads/lead-bling-section.tsx` | Painel Bling do modal de lead. | Modificar (semente + efeito) |
| `docs/setup/bling-observacoes-producao.md` | Runbook de produção. Registra a inversão de precedência. | Modificar |

**Não tocar** (spec, seção "Fora de escopo"): `sale-create-modal.tsx`,
`quote-create-modal.tsx`, `bling-order-form.tsx`, `seller-map/route.ts`,
qualquer migration.

---

## Ordem e paralelismo

- **Onda A (paralela):** Task 1 (backend) ‖ Task 2 (frontend lib) — arquivos disjuntos, zero dependência.
- **Onda B (paralela):** Task 3 ‖ Task 4 ‖ Task 5 ‖ Task 7 — arquivos disjuntos, todas dependem do `CONTA_PREFERIDA` exportado na Task 2.
- **Onda C:** Task 6 — documentação e verificação final.

Pré-requisito da Onda B: `cd frontend && npm ci` concluído, senão os testes de
componente das Tasks 3, 5 e 7 não têm como ser verificados.

**Commits:** quem dispara agentes em paralelo deve deixar os agentes **apenas
editarem e rodarem testes**, e fazer os `git commit` sequencialmente entre as
ondas. Dois agentes commitando ao mesmo tempo na mesma working tree disputam o
`index.lock`.

---

### Task 1: Mapa de rótulos no backend

**Files:**
- Modify: `backend/app/bling/config.py` (dataclass `BlingAccount` fica intocada; muda só o corpo de `account()` e nasce uma constante no topo)
- Test: `backend/tests/test_bling_config.py:184-191`

- [ ] **Step 1: Reescrever os dois testes de label e adicionar o terceiro**

Os dois testes atuais quebram por construção — eles afirmam exatamente o
comportamento que esta task inverte. Substitua o bloco inteiro
(`test_label_cai_para_a_propria_key` e `test_label_le_do_env`, linhas 184-191)
por estes quatro testes:

```python
def test_label_cai_para_a_propria_key(monkeypatch):
    # Slug FORA do mapa: e o unico caso em que o fallback cru ainda vale.
    monkeypatch.setenv("BLING_ACCOUNTS", "default,terceira")
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    monkeypatch.delenv("BLING_TERCEIRA_LABEL", raising=False)
    assert cfg.account("terceira").label == "terceira"


def test_label_le_do_env_para_conta_fora_do_mapa(monkeypatch):
    # O escape hatch por env sobrevive para quem ainda precisa dele.
    monkeypatch.setenv("BLING_ACCOUNTS", "default,terceira")
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    monkeypatch.setenv("BLING_TERCEIRA_LABEL", "Canastra CNPJ 3")
    assert cfg.account("terceira").label == "Canastra CNPJ 3"


def test_rotulos_das_duas_contas_conhecidas_vem_do_codigo(duas_contas):
    assert cfg.account("default").label == "Bling Café Canastra (1)"
    assert cfg.account("secundaria").label == "Bling Café Rural (2)"


def test_rotulo_do_codigo_vence_o_env_antigo(duas_contas, monkeypatch):
    # A asserção que protege o objetivo da entrega: BLING_LABEL e
    # BLING_SECUNDARIA_LABEL continuam preenchidas com os nomes velhos no .env
    # da VPS. Sem esta inversao, o mapa seria ignorado em producao e a tela nao
    # mudaria.
    monkeypatch.setenv("BLING_LABEL", "Canastra CNPJ 1")
    monkeypatch.setenv("BLING_SECUNDARIA_LABEL", "Canastra CNPJ 2")
    assert cfg.account("default").label == "Bling Café Canastra (1)"
    assert cfg.account("secundaria").label == "Bling Café Rural (2)"
```

> Os dois primeiros testes não usam a fixture `duas_contas` (que registra
> `default,secundaria`) porque precisam de um roster com o slug `terceira`.
> Eles repetem as três linhas de env da fixture de propósito — `account()`
> levanta `BlingUnknownAccount` para slug fora de `BLING_ACCOUNTS`.

- [ ] **Step 2: Rodar os testes e confirmar que falham**

Run: `cd backend && python -m pytest tests/test_bling_config.py -v -k "label or rotulo"`

Expected: `test_rotulos_das_duas_contas_conhecidas_vem_do_codigo` e
`test_rotulo_do_codigo_vence_o_env_antigo` **FALHAM** com
`AssertionError: assert 'default' == 'Bling Café Canastra (1)'` (ou
`'Canastra CNPJ 1' == ...` no segundo). Os dois primeiros já passam — eles
descrevem o comportamento de slug fora do mapa, que não muda.

- [ ] **Step 3: Adicionar a constante `ROTULOS_PADRAO`**

Em `backend/app/bling/config.py`, logo **abaixo** de `DEFAULT_ACCOUNT = "default"`:

```python
DEFAULT_ACCOUNT = "default"

# Nome de negocio de cada conta, por slug. Consultado ANTES do env de proposito:
# BLING_LABEL e BLING_SECUNDARIA_LABEL ja estao preenchidas na VPS com os nomes
# antigos ("CNPJ 1"/"CNPJ 2"), entao respeitar o env aqui faria este mapa nao ter
# efeito nenhum em producao. Um slug FORA deste mapa continua lendo
# BLING_<CONTA>_LABEL normalmente — o escape hatch sobrevive para a terceira
# conta que ainda nao existe.
ROTULOS_PADRAO = {
    "default": "Bling Café Canastra (1)",
    "secundaria": "Bling Café Rural (2)",
}
```

- [ ] **Step 4: Inverter a precedência em `account()`**

No corpo de `account()`, substitua a linha do `label` (e o comentário de três
linhas acima dela, que descreve a regra antiga) por:

```python
        # Rotulo das contas conhecidas vem do codigo (ver ROTULOS_PADRAO).
        # LABEL nao usa _env_for de proposito: nao faz sentido a conta 2 herdar
        # o rotulo da conta 1 — o rotulo existe justamente para distingui-las.
        label=ROTULOS_PADRAO.get(key) or _env(_suffixed("LABEL", key)) or key,
```

- [ ] **Step 5: Rodar o arquivo inteiro**

Run: `cd backend && python -m pytest tests/test_bling_config.py -v`
Expected: **39 passed** (37 do baseline − 2 substituídos + 4 novos).

- [ ] **Step 6: Rodar a suíte Bling inteira, para pegar quem dependia do rótulo antigo**

Run: `cd backend && python -m pytest tests/ -q -k bling`
Expected: todos passam. Se algum teste fora de `test_bling_config.py` afirmar
um rótulo, ele estava acoplado ao env — corrija para o rótulo novo e diga isso
no relatório.

- [ ] **Step 7: Commit**

```bash
git add backend/app/bling/config.py backend/tests/test_bling_config.py
git commit -m "feat(bling): rotulo das duas contas vem do codigo, nao do env"
```

---

### Task 2: `CONTA_PREFERIDA` e a escada de quatro degraus

**Files:**
- Modify: `frontend/src/lib/bling-accounts.ts:19` (constante) e `:46-51` (função `contaPadrao`)
- Test: `frontend/src/lib/bling-accounts.test.ts:50-64` (bloco `describe("contaPadrao")`)

- [ ] **Step 1: Substituir o bloco `describe("contaPadrao")` inteiro**

O teste atual `"prefere a default quando conectada"` afirma o oposto do que
esta task entrega. Substitua o `describe` inteiro (linhas 50-64) por:

```ts
describe("contaPadrao", () => {
  it("prefere a CONTA_PREFERIDA (Cafe Rural) quando conectada", () => {
    expect(contaPadrao(CONTAS)).toBe("secundaria");
  });

  // O degrau 2 da escada, e a razao de ele existir: com a preferida fora do ar
  // a tela volta para a conta que todo mundo conhece, nao para a primeira da
  // lista por acaso.
  it("cai para a CONTA_PADRAO quando a preferida nao esta conectada", () => {
    const contas = [
      CONTAS[0],
      { ...CONTAS[1], connected: false },
      { account: "terceira", label: "T", configured: true, connected: true },
    ];
    expect(contaPadrao(contas)).toBe("default");
  });

  it("cai para a primeira conectada quando nem a preferida nem a padrao estao", () => {
    const contas = [
      { ...CONTAS[0], connected: false },
      { ...CONTAS[1], connected: false },
      { account: "terceira", label: "T", configured: true, connected: true },
    ];
    expect(contaPadrao(contas)).toBe("terceira");
  });

  it("devolve null sem nenhuma conta conectada", () => {
    expect(contaPadrao([{ ...CONTAS[0], connected: false }])).toBeNull();
  });

  // Trava de identidade: o slug historico nao pode ser arrastado pela mudanca
  // de preferencia. Se este teste quebrar, toda venda antiga sem bling_account
  // passou a ser rotulada como Cafe Rural.
  it("CONTA_PADRAO continua sendo o slug da conta 1", () => {
    expect(CONTA_PADRAO).toBe("default");
    expect(CONTA_PREFERIDA).toBe("secundaria");
  });
});
```

- [ ] **Step 2: Acrescentar os dois nomes ao import do arquivo de teste**

No topo de `frontend/src/lib/bling-accounts.test.ts`, o import vira:

```ts
import {
  CONTA_PADRAO,
  CONTA_PREFERIDA,
  contasDisponiveis,
  precisaSeletor,
  contaPadrao,
  trocaLimpaFormulario,
  interpretarStatus,
} from "./bling-accounts";
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `cd frontend && npx vitest run src/lib/bling-accounts.test.ts`
Expected: **FAIL** na fase de import/transform, com
`"CONTA_PREFERIDA" is not exported by "src/lib/bling-accounts.ts"`.

- [ ] **Step 4: Exportar `CONTA_PREFERIDA`**

Em `frontend/src/lib/bling-accounts.ts`, logo **abaixo** do bloco de
`CONTA_PADRAO` (que fica exatamente como está, comentário incluído):

```ts
/**
 * Slug da conta PREFERIDA ao abrir um seletor. Decisao de negocio — o volume
 * de emissao esta no Cafe Rural — e nao de identidade, por isso mora numa
 * constante propria em vez de deslocar `CONTA_PADRAO`.
 *
 * A distincao e o nucleo do desenho: `CONTA_PADRAO` e o slug gravado em todo
 * registro anterior a segunda conta e o prefixo das env vars sem sufixo, entao
 * move-lo reescreveria a historia (venda emitida no CNPJ 1 passaria a se dizer
 * do Cafe Rural). Trocar ESTA constante nao toca em registro nenhum: muda so
 * qual opcao ja vem marcada, e o vendedor sempre pode escolher outra.
 */
export const CONTA_PREFERIDA = "secundaria";
```

- [ ] **Step 5: Reescrever `contaPadrao` como a escada de quatro degraus**

Substitua a função `contaPadrao` **e o docblock acima dela** por:

```ts
/**
 * Conta pre-selecionada quando o seletor aparece, sempre restrita as
 * CONECTADAS. Escada de quatro degraus:
 *
 *   1. `CONTA_PREFERIDA` (Cafe Rural) — onde o volume de emissao esta hoje
 *   2. `CONTA_PADRAO` (Cafe Canastra) — se a preferida perdeu a autorizacao,
 *      volta para a conta que todo mundo conhece, e nao para uma terceira
 *      qualquer que o BLING_ACCOUNTS tenha listado antes
 *   3. a primeira disponivel
 *   4. `null` — nenhuma conta conectada. O que fazer nesse caso (bloquear?
 *      cair no legado?) e decisao do `blingGate`, nao deste modulo.
 */
export function contaPadrao(contas: ContaBling[]): string | null {
  const disponiveis = contasDisponiveis(contas);
  if (disponiveis.length === 0) return null;
  const escolhida =
    disponiveis.find((c) => c.account === CONTA_PREFERIDA) ??
    disponiveis.find((c) => c.account === CONTA_PADRAO) ??
    disponiveis[0];
  return escolhida.account;
}
```

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `cd frontend && npx vitest run src/lib/bling-accounts.test.ts`
Expected: **PASS**, 20 tests (18 do baseline − 3 do `describe` antigo + 5 novos).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/bling-accounts.ts frontend/src/lib/bling-accounts.test.ts
git commit -m "feat(bling): CONTA_PREFERIDA separa preferencia de identidade"
```

> **Nota para a Onda B:** as Tasks 3, 4 e 5 dependem deste export. Não dispare
> a Onda B antes deste commit existir.

---

### Task 3: `/config` — semente do mapa de vendedores

**Files:**
- Modify: `frontend/src/components/config/bling-settings.tsx:15-19` (import) e `:154`

Esta é a mais simples das três telas: o efeito de reconciliação **já existe**
(linhas 176-187) e já chama `contaPadrao`. Só a semente síncrona muda.

- [ ] **Step 1: Acrescentar `CONTA_PREFERIDA` ao import**

O import de `@/lib/bling-accounts` (linhas 15-19) hoje traz `CONTA_PADRAO`,
`contaPadrao`, `contasDisponiveis`, `precisaSeletor`. Acrescente
`CONTA_PREFERIDA` à lista, mantendo `CONTA_PADRAO` — ele continua sendo usado
nas linhas 124 e 415 deste mesmo arquivo:

```ts
import {
  CONTA_PADRAO,
  CONTA_PREFERIDA,
  contaPadrao,
  contasDisponiveis,
  precisaSeletor,
```

- [ ] **Step 2: Trocar a semente do `contaVendedores`**

Linha 154, hoje:

```ts
  const [contaVendedores, setContaVendedores] = useState<string>(CONTA_PADRAO);
```

vira:

```ts
  // Semente na conta PREFERIDA; o efeito abaixo corrige se ela nao estiver
  // conectada.
  const [contaVendedores, setContaVendedores] = useState<string>(CONTA_PREFERIDA);
```

- [ ] **Step 2b: Consertar os três testes que afirmam o comportamento antigo**

`frontend/src/components/config/bling-settings.test.tsx` tem três testes
(~156, ~172, ~192) que fazem a mesma sequência:

```ts
await waitFor(() => expect(screen.getByText("João do CNPJ 1")).toBeTruthy());
fireEvent.change(screen.getByLabelText("Conta"), { target: { value: "secundaria" } });
await waitFor(() => expect(screen.getByText("João do CNPJ 2")).toBeTruthy());
```

Depois do Step 2 o painel **já abre** em `secundaria`, então a primeira espera
mira a lista errada e o `fireEvent.change` para o mesmo valor não dispara
evento nenhum. Inverta a sequência nos três: espere por `"João do CNPJ 2"`
primeiro, e quando o teste precisar exercitar a TROCA, troque para `"default"`
e espere `"João do CNPJ 1"`.

Cuidado com o terceiro teste (`"salva o vinculo NA CONTA selecionada, nao na
default"`): o nome e a asserção final (`account: "secundaria"`) dependem de a
conta salva **não** ser a default. Como `secundaria` virou a conta de abertura,
esse teste perde o sentido se ficar em `secundaria`. Reescreva-o para trocar
para `"default"` e afirmar `account: "default"` — o ponto do teste é que o
vínculo vai para a conta SELECIONADA, seja ela qual for. Ajuste o nome do teste
junto (`"salva o vinculo NA CONTA selecionada, nao na de abertura"`).

Não mude os rótulos `"Canastra CNPJ 1"`/`"Canastra CNPJ 2"` das fixtures: são
dados locais do teste, não vêm de `ROTULOS_PADRAO`, e trocá-los não prova nada.

- [ ] **Step 3: Rodar o teste do componente e o type-check**

Run: `cd frontend && npx vitest run src/components/config/bling-settings.test.tsx`
Expected: todos passam. (Exige o `npm ci` já concluído.)

Run: `cd frontend && npx tsc --noEmit`
Expected: sem erro.

- [ ] **Step 4: Verificar que `CONTA_PADRAO` continua usado neste arquivo**

Run: `grep -n "CONTA_PADRAO" frontend/src/components/config/bling-settings.tsx`
Expected: 3 ocorrências (import, linha ~124 `account: CONTA_PADRAO`, linha ~415
`conta.account === CONTA_PADRAO`). Se sobrar só o import, o import virou lixo —
mas isso **não** deve acontecer nesta task; se acontecer, algo foi removido por
engano.

- [ ] **Step 5: Commit** (ver nota de commits na seção "Ordem e paralelismo" — quem orquestra commita)

```bash
git add frontend/src/components/config/bling-settings.tsx
git commit -m "feat(bling): /config abre o mapa de vendedores no Cafe Rural"
```

---

### Task 4: `/produtos` — semente + efeito de reconciliação

**Files:**
- Modify: `frontend/src/app/(authenticated)/produtos/page.tsx:11` (import) e `:48` (+ efeito novo logo abaixo)

Diferente da Task 3, aqui **não existe** efeito de reconciliação. Ele é
obrigatório: a tela semeia o slug de forma síncrona e nunca confere se aquela
conta está conectada. Trocar só a semente cria uma armadilha real — com o Café
Rural desconectado, a tela fica presa numa conta indisponível, o catálogo vem
vazio, e o seletor **nem aparece** para escapar (`precisaSeletor` exige duas
contas disponíveis).

- [ ] **Step 1: Trocar o import**

Linha 11, hoje:

```ts
import { CONTA_PADRAO, contasDisponiveis, precisaSeletor } from "@/lib/bling-accounts";
```

vira (note que `CONTA_PADRAO` **sai** — este arquivo não tem outro uso dele — e
`contaPadrao`, a função, **entra**):

```ts
import {
  CONTA_PREFERIDA,
  contaPadrao,
  contasDisponiveis,
  precisaSeletor,
} from "@/lib/bling-accounts";
```

- [ ] **Step 2: Trocar a semente e acrescentar o efeito**

Linha 48, hoje:

```ts
  const [conta, setConta] = useState(CONTA_PADRAO);
```

vira:

```ts
  const [conta, setConta] = useState(CONTA_PREFERIDA);
```

E logo **abaixo** da linha `const [page, setPage] = useState(1);` (linha 49),
acrescente o efeito:

```ts
  // A semente acima e sincrona (a tela pinta antes de `/api/bling/status`
  // responder) e nao tem como saber se a conta preferida esta conectada.
  // Sem esta reconciliacao, o Cafe Rural desconectado deixaria a tela presa
  // num catalogo vazio SEM saida: o seletor so aparece com DUAS contas
  // disponiveis, entao nao haveria como trocar de conta na mao.
  useEffect(() => {
    const disponiveis = contasDisponiveis(blingStatus.accounts);
    if (disponiveis.length === 0) return;                     // ainda carregando
    if (disponiveis.some((c) => c.account === conta)) return; // aposta certa
    const padrao = contaPadrao(blingStatus.accounts);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (padrao) setConta(padrao);
  }, [blingStatus.accounts, conta]);
```

> Recomputa `disponiveis` dentro do efeito em vez de depender da variável
> `contas` do escopo: `contasDisponiveis` devolve um array novo a cada render,
> então usá-lo como dependência faria o efeito rodar em todo render. O corpo é
> idempotente, mas o ruído é evitável — e é o mesmo formato da Task 5.
>
> O `eslint-disable` do `react-hooks/set-state-in-effect` segue o padrão já
> usado neste mesmo arquivo (linhas ~65 e ~70). Se o lint **não** reclamar,
> remova a linha do disable — comentário morto atrapalha.

- [ ] **Step 3: Rodar lint e type-check**

Run: `cd frontend && npx tsc --noEmit && npx eslint "src/app/(authenticated)/produtos/page.tsx"`
Expected: sem erro.

- [ ] **Step 4: Conferir que `CONTA_PADRAO` sumiu do arquivo**

Run: `grep -c "CONTA_PADRAO" "frontend/src/app/(authenticated)/produtos/page.tsx"`
Expected: `0`. Se der diferente de zero, sobrou uso ou import órfão.

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/app/(authenticated)/produtos/page.tsx"
git commit -m "feat(bling): /produtos abre no Cafe Rural, com reconciliacao"
```

---

### Task 5: Painel Bling do lead — semente + efeito de reconciliação

**Files:**
- Modify: `frontend/src/components/leads/lead-bling-section.tsx:19` (import) e `:74-80`

Mesma armadilha da Task 4 e mesmo remédio. Atenção especial: o comentário que
está hoje nas linhas 74-77 **justifica explicitamente** o comportamento antigo
("Comeca na DEFAULT sempre… sem esperar rede nenhuma"). Ele tem que ser
reescrito, não apagado — a razão dele (pintar sem esperar rede) continua
valendo, o que muda é qual slug é semeado e o fato de agora haver correção.

- [ ] **Step 1: Trocar o import**

Linha 19, hoje:

```ts
import { CONTA_PADRAO, contasDisponiveis, precisaSeletor } from "@/lib/bling-accounts";
```

vira (`CONTA_PADRAO` sai — não há outro uso neste arquivo):

```ts
import {
  CONTA_PREFERIDA,
  contaPadrao,
  contasDisponiveis,
  precisaSeletor,
} from "@/lib/bling-accounts";
```

- [ ] **Step 2: Reescrever o bloco da conta**

As linhas 74-80, hoje:

```ts
  // Comeca na DEFAULT sempre (nao em `contaPadrao(...)`): e o que faz esta
  // secao mostrar, sem esperar rede nenhuma, exatamente o que ela sempre
  // mostrou antes da segunda conta existir. Ver outras contas e uma escolha
  // explicita do vendedor no seletor abaixo, nunca automatica.
  const blingStatus = useBlingStatus();
  const [conta, setConta] = useState(CONTA_PADRAO);
  const mostrarSeletorConta = precisaSeletor(blingStatus.accounts);
```

viram:

```ts
  // Semeia a conta PREFERIDA de forma sincrona: esta secao pinta antes de
  // `/api/bling/status` responder, e esperar a rede para so entao decidir a
  // conta deixaria o painel piscando em branco a cada abertura de modal.
  // O efeito abaixo corrige a aposta quando ela estiver errada.
  const blingStatus = useBlingStatus();
  const [conta, setConta] = useState(CONTA_PREFERIDA);
  const mostrarSeletorConta = precisaSeletor(blingStatus.accounts);

  // Sem esta reconciliacao, o Cafe Rural desconectado prenderia o painel numa
  // conta que nao existe — e o seletor abaixo so aparece com DUAS contas
  // disponiveis, entao o vendedor nao teria como sair de la na mao.
  useEffect(() => {
    const disponiveis = contasDisponiveis(blingStatus.accounts);
    if (disponiveis.length === 0) return;                    // ainda carregando
    if (disponiveis.some((c) => c.account === conta)) return; // aposta certa
    const padrao = contaPadrao(blingStatus.accounts);
    if (padrao) setConta(padrao);
  }, [blingStatus.accounts, conta]);
```

- [ ] **Step 2b: Consertar o teste que afirma o comportamento antigo**

`frontend/src/components/leads/lead-bling-section.test.tsx:57` é o teste
`"comeca na conta DEFAULT — nada muda para quem usa o CRM hoje enquanto o
vendedor nao mexe no seletor"`. Ele monta com `DUAS_CONTAS` (as duas
conectadas) e `blingContactIds={{ [CONTA_PADRAO]: 99 }}`, afirmando que a
seção abre mostrando o vínculo da conta default.

Isso é exatamente o que a Task 5 inverte. Reescreva o teste para a preferida:

```ts
  it("comeca na conta PREFERIDA — o vendedor cai direto no CNPJ que mais emite", async () => {
    mockUseBlingStatus.mockReturnValue({ enabled: true, accounts: DUAS_CONTAS, loading: false, error: null });
    // ...mesmo mock de fetch do teste original...
    render(<LeadBlingSection leadId="lead-1" blingContactIds={{ [CONTA_PREFERIDA]: 99 }} onChanged={vi.fn()} />);
    // ...mesma asserção do original, agora contra o vinculo da conta preferida...
  });
```

Mantenha o resto do corpo idêntico ao original — só a conta muda. Acrescente
`CONTA_PREFERIDA` ao import de `@/lib/bling-accounts` na linha 16 (o
`CONTA_PADRAO` continua sendo usado nas fixtures `UMA_CONTA`/`DUAS_CONTAS`, não
o remova).

Confira também o teste `"busca de vinculo manda a conta na querystring"`
(~linha 70): se ele afirma `account=default` na querystring, agora vai receber
`account=secundaria`. Ajuste para a preferida.

Não mude os rótulos das fixtures (`"Canastra CNPJ 1"`/`"Canastra CNPJ 2"`):
são dados locais do teste, passados como props, e não vêm de `ROTULOS_PADRAO`.

- [ ] **Step 3: Rodar o teste do componente, lint e type-check**

Run: `cd frontend && npx vitest run src/components/leads/lead-bling-section.test.tsx`
Expected: todos passam. (Exige o `npm ci` já concluído.)

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/leads/lead-bling-section.tsx`
Expected: sem erro. Se o ESLint reclamar de `react-hooks/set-state-in-effect`,
acrescente `// eslint-disable-next-line react-hooks/set-state-in-effect`
imediatamente acima do `if (padrao) setConta(padrao);` — é o mesmo padrão usado
em `produtos/page.tsx`.

- [ ] **Step 4: Conferir que `useEffect` já estava importado**

Run: `grep -n 'from "react"' frontend/src/components/leads/lead-bling-section.tsx`
Expected: `import { useEffect, useState } from "react";` — já está lá (linha
14), nada a fazer. Se não estiver, acrescente.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/leads/lead-bling-section.tsx
git commit -m "feat(bling): painel do lead abre no Cafe Rural, com reconciliacao"
```

---

### Task 6: Documentar a inversão e verificar tudo

**Files:**
- Modify: `docs/setup/bling-observacoes-producao.md` (seção "Variáveis de ambiente" da segunda conta, ~linha 441)

O risco 3 da spec: `BLING_LABEL` e `BLING_SECUNDARIA_LABEL` continuam no `.env`
da VPS com os nomes antigos, apenas ignoradas. Quem abrir esse arquivo daqui a
seis meses vai encontrar nomes que não batem com a tela. Esta task fecha esse
buraco no runbook.

- [ ] **Step 1: Acrescentar o aviso no runbook**

Em `docs/setup/bling-observacoes-producao.md`, logo **abaixo** do bloco de
código que lista as variáveis (`BLING_ACCOUNTS=...` até
`BLING_SECUNDARIA_ORDER_SITUACAO_ID=...`), acrescente:

```markdown
> ⚠️ **`BLING_LABEL` e `BLING_SECUNDARIA_LABEL` estão ignoradas desde
> 17/09/2026.** O rótulo das duas contas conhecidas passou a vir do código
> (`ROTULOS_PADRAO` em `backend/app/bling/config.py`): "Bling Café Canastra (1)"
> e "Bling Café Rural (2)". Editar essas variáveis na VPS **não muda mais nada
> na tela** — para renomear, mude o mapa e suba. Um slug fora do mapa (uma
> terceira conta) continua lendo `BLING_<CONTA>_LABEL` normalmente.
>
> A conta pré-selecionada em todo seletor do CRM é o **Café Rural**
> (`CONTA_PREFERIDA` em `frontend/src/lib/bling-accounts.ts`). O slug
> `default` continua sendo o Café Canastra e continua sendo o dono de todo
> registro sem `bling_account` — as duas coisas são independentes de
> propósito. Spec: `docs/superpowers/specs/2026-09-17-bling-rotulos-conta-preferida-design.md`.
```

- [ ] **Step 2: Rodar a suíte do backend inteira**

Run: `cd backend && python -m pytest tests/ -q`
Expected: mesma contagem de falhas do baseline (idealmente zero). Compare com
`git stash && python -m pytest tests/ -q` se houver falha, para não assumir
como sua uma quebra pré-existente.

- [ ] **Step 3: Rodar a suíte do frontend INTEIRA — é o gate de deploy**

Run: `cd frontend && npm run test`
Expected: **todos passam**, incluindo os `.test.tsx`. Este é literalmente o
comando de `.github/workflows/deploy.yml:52`, marcado no próprio workflow como
"Gate bloqueante: qualquer teste vermelho impede o deploy". Não substitua por
`npx vitest run src/lib/` — rodar só um subconjunto aqui foi o erro que deixou
três testes desatualizados passarem despercebidos no plano original.

- [ ] **Step 4: Type-check do frontend inteiro**

Run: `cd frontend && npx tsc --noEmit`
Expected: sem erro.

- [ ] **Step 5: Conferir que o "fora de escopo" ficou intacto**

Run:
```bash
git diff origin/master --stat
```

Expected: **exatamente** estes 13 arquivos e nenhum outro —

```
docs/superpowers/specs/2026-09-17-bling-rotulos-conta-preferida-design.md
docs/superpowers/plans/2026-09-17-bling-rotulos-conta-preferida.md
docs/setup/bling-observacoes-producao.md
backend/app/bling/config.py
backend/tests/test_bling_config.py
frontend/src/lib/bling-accounts.ts
frontend/src/lib/bling-accounts.test.ts
frontend/src/components/config/bling-settings.tsx
frontend/src/components/config/bling-settings.test.tsx
frontend/src/app/(authenticated)/produtos/page.tsx
frontend/src/components/leads/lead-bling-section.tsx
frontend/src/components/leads/lead-bling-section.test.tsx
frontend/src/components/sales/bling-order-form.test.tsx
```

Se `sale-create-modal.tsx`, `quote-create-modal.tsx`, **`bling-order-form.tsx`**
(o `.tsx` de código, não o `.test.tsx`), `seller-map/route.ts`,
`frontend/package.json`, `frontend/package-lock.json` ou qualquer migration
aparecer no diff, **algo saiu do escopo** — reverta esse arquivo. O `npm ci`
não deve alterar `package.json` nem `package-lock.json`; se alterou, reverta.

- [ ] **Step 6: Conferir a trava de identidade com os próprios olhos**

Run: `grep -rn 'CONTA_PADRAO' frontend/src/components/sales/sale-create-modal.tsx frontend/src/components/quotes/quote-create-modal.tsx frontend/src/app/api/bling/seller-map/route.ts`

Expected: os fallbacks históricos (`venda.bling_account ?? CONTA_PADRAO`,
`quote?.bling_account ?? CONTA_PADRAO`, `conta ?? CONTA_PADRAO`, e o da rota
seller-map) continuam apontando para `CONTA_PADRAO`, **nunca** para
`CONTA_PREFERIDA`. Este é o degrau que impede a entrega de reescrever a
história.

- [ ] **Step 7: Commit**

```bash
git add docs/setup/bling-observacoes-producao.md
git commit -m "docs(bling): rotulo vem do codigo e o env antigo esta ignorado"
```

---

### Task 7: Teste do formulário de pedido que afirma a conta antiga

**Files:**
- Modify: `frontend/src/components/sales/bling-order-form.test.tsx:109`

Nasceu durante a execução (ver "CORREÇÃO 2026-09-17" no topo). Pertence à Onda
B: depende só da Task 2, que já está commitada. É a contrapartida do
`bling-order-form.tsx` estar em "não tocar" — o **código-fonte** não muda
(ele já delega a decisão a `contaPadrao`), mas o **teste** cristalizou o valor
antigo.

- [ ] **Step 1: Rodar o teste e ver a falha**

Run: `cd frontend && npx vitest run src/components/sales/bling-order-form.test.tsx`
Expected: **FAIL** no teste que contém
`await waitFor(() => expect(aoMudarConta).toHaveBeenCalledWith(CONTA_PADRAO));`,
com `AssertionError` mostrando que foi chamado com `"secundaria"`.

- [ ] **Step 2: Corrigir a asserção**

A fixture `CONTAS` (linhas 29-32) tem as **duas** contas conectadas, então
`contaPadrao` agora devolve `"secundaria"`. Troque a asserção e o comentário
acima dela:

```ts
    // A conta PREFERIDA e comunicada ao pai (ele precisa dela para as PROPRIAS
    // chamadas — POST do pedido, resolvedor de contato). Com as duas contas
    // conectadas, `contaPadrao` escolhe o Cafe Rural.
    await waitFor(() => expect(aoMudarConta).toHaveBeenCalledWith(CONTA_PREFERIDA));
```

Acrescente `CONTA_PREFERIDA` ao import da linha 27. **Não remova**
`CONTA_PADRAO`: ele continua sendo usado na fixture `CONTAS` (linha 30) e na
asserção `expect(screen.queryByText(CONTA_PADRAO)).toBeNull()` (~linha 103),
que prova que o seletor mostra o `label` e nunca o slug cru — essa continua
válida e não deve mudar.

- [ ] **Step 3: Rodar e confirmar verde**

Run: `cd frontend && npx vitest run src/components/sales/bling-order-form.test.tsx`
Expected: PASS, todos.

- [ ] **Step 4: Confirmar que o código-fonte não foi tocado**

Run: `git status --porcelain frontend/src/components/sales/bling-order-form.tsx`
Expected: **saída vazia**. Se esse arquivo aparecer, a task saiu do escopo.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sales/bling-order-form.test.tsx
git commit -m "test(bling): pedido pre-seleciona o Cafe Rural, nao a conta 1"
```

---

## Validação em navegador (depois do push, por quem tem acesso)

Não faz parte das tasks — o backend dev escreve no **banco de produção**, então
só leitura entra aqui. **Criar venda ou orçamento de teste está fora.**

- [ ] `/config` mostra "Bling Café Canastra (1)" e "Bling Café Rural (2)" nos cards de status.
- [ ] `/config` → mapa de vendedores abre com "Bling Café Rural (2)" no seletor.
- [ ] `/produtos` abre com o catálogo do Café Rural.
- [ ] Modal de lead → seção Bling abre na conta Café Rural.
- [ ] Modal de venda (só **abrir**, não salvar) traz Café Rural marcado.
- [ ] Uma venda antiga na `/vendas`, sem `bling_account`, continua rotulada como "Bling Café Canastra (1)".
