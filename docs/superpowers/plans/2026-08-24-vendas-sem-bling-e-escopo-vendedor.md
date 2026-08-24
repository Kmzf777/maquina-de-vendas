# Venda sem Bling + painel escopado por vendedor — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir registrar venda no CRM sem criar pedido no Bling, e fazer `/painel-vendas` mostrar ao vendedor só as vendas dele mais as importadas do ERP.

**Architecture:** Toda regra nova mora em função pura testável em `frontend/src/lib/` (`bling-gate.ts`, `sales-scope.ts`); rotas e componentes apenas chamam essas funções. O escopo é imposto no servidor porque as rotas de venda hoje usam service role e não checam sessão. Nada nesta entrega chama a API do Bling — nem escrita nem leitura.

**Tech Stack:** Next.js App Router (server routes), React client components, Supabase JS (PostgREST), vitest, SQL puro para a migration.

**Spec:** `docs/superpowers/specs/2026-08-24-vendas-sem-bling-e-escopo-vendedor-design.md`

**Comandos base** (rodar sempre de `frontend/`):
- Teste único: `npx vitest run src/lib/<arquivo>.test.ts`
- Suíte inteira: `npm test`
- Tipos: `npm run type-check`

---

## Restrição que vale para todas as tasks

Nenhuma task pode chamar `POST /contatos`, `POST /pedidos/vendas` ou
`PUT /pedidos/vendas/{id}`. Se alguma implementação parecer precisar disso, pare e
reporte — a spec proíbe qualquer alteração no Bling.

---

## Task 1: `skipBling` no gate do modal

**Files:**
- Modify: `frontend/src/lib/bling-gate.ts`
- Test: `frontend/src/lib/bling-gate.test.ts`

- [ ] **Step 1: Escrever os testes que falham**

Adicione ao final do `describe("blingGate", ...)` em `frontend/src/lib/bling-gate.test.ts`:

```ts
  // O caso que da nome a mudanca: com skipBling, falhar ao consultar o status
  // NAO pode bloquear — a venda nem vai para o Bling, entao a conexao e
  // irrelevante. Antes desta mudanca o modal travava por completo aqui.
  it("skipBling destrava mesmo quando o status falhou", () => {
    const g = blingGate({ loading: false, error: "timeout", enabled: null, isEditing: false, skipBling: true });
    expect(g.mode).toBe("legacy");
    expect(g.canSubmit).toBe(true);
  });

  it("skipBling vence o modo bling", () => {
    const g = blingGate({ loading: false, error: null, enabled: true, isEditing: false, skipBling: true });
    expect(g.mode).toBe("legacy");
    expect(g.canSubmit).toBe(true);
  });

  it("skipBling nao espera o status carregar", () => {
    const g = blingGate({ loading: true, error: null, enabled: null, isEditing: false, skipBling: true });
    expect(g.mode).toBe("legacy");
    expect(g.canSubmit).toBe(true);
  });

  it("sem skipBling, nada muda", () => {
    const g = blingGate({ loading: false, error: null, enabled: true, isEditing: false, skipBling: false });
    expect(g.mode).toBe("bling");
  });
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `npx vitest run src/lib/bling-gate.test.ts`
Expected: FAIL — erro de tipo em `skipBling` (propriedade não existe em `BlingGateInput`) e os três primeiros casos devolvendo `error`/`bling`/`loading` em vez de `legacy`.

- [ ] **Step 3: Implementar**

Em `frontend/src/lib/bling-gate.ts`, adicione o campo à interface e o curto-circuito. Substitua o bloco `BlingGateInput` e a função por:

```ts
export interface BlingGateInput {
  loading: boolean;
  error: string | null;
  enabled: boolean | null;
  isEditing: boolean;
  /**
   * O vendedor marcou "Registrar sem enviar ao Bling". Curto-circuita TUDO,
   * inclusive `error`: se a venda nao vai para o ERP, nao ha o que confirmar.
   * Avaliar isto depois de `error` manteria o modal travado exatamente na
   * situacao em que a escapatoria e mais util.
   */
  skipBling?: boolean;
}

export function blingGate({ loading, error, enabled, skipBling }: BlingGateInput): BlingGate {
  if (skipBling) return { mode: "legacy", canSubmit: true };
  if (loading) return { mode: "loading", canSubmit: false };

  if (error) {
    return {
      mode: "error",
      canSubmit: false,
      message:
        "Nao foi possivel confirmar a conexao com o Bling. " +
        "Registrar agora criaria uma venda fora do ERP, entao o envio esta bloqueado. " +
        "Para registrar assim mesmo, marque \"Registrar sem enviar ao Bling\".",
    };
  }

  return enabled ? { mode: "bling", canSubmit: true } : { mode: "legacy", canSubmit: true };
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `npx vitest run src/lib/bling-gate.test.ts`
Expected: PASS — todos os casos, incluindo os 6 que já existiam.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/bling-gate.ts frontend/src/lib/bling-gate.test.ts
git commit -m "feat(vendas): skipBling no gate, curto-circuitando ate o estado de erro"
```

---

## Task 2: Checkbox "Registrar sem enviar ao Bling" no modal

**Files:**
- Modify: `frontend/src/components/sales/sale-create-modal.tsx`

Não há teste automatizado aqui: o componente tem 900+ linhas e a suíte do projeto
não testa componentes (42 arquivos de teste, todos sobre funções puras em `lib/`).
A regra que importa já está coberta na Task 1. A verificação é manual, no Step 4.

- [ ] **Step 1: Adicionar o estado e o gate "sem skip"**

Em `frontend/src/components/sales/sale-create-modal.tsx`, logo após a linha
`const blingStatus = useBlingStatus();` (hoje na linha 107), o bloco do gate passa a ser:

```tsx
  const [skipBling, setSkipBling] = useState(false);
  const gate = blingGate({
    loading: blingStatus.loading,
    error: blingStatus.error,
    enabled: blingEnabled ?? blingStatus.enabled,
    isEditing,
    skipBling,
  });
  // Gate hipotetico ignorando a escolha do vendedor: e ele que diz se a
  // escapatoria faz sentido nesta tela. Sem isto, marcar a caixa faria o proprio
  // `gate` virar "legacy" e a caixa sumiria da tela ao ser marcada.
  const gateSemSkip = blingGate({
    loading: blingStatus.loading,
    error: blingStatus.error,
    enabled: blingEnabled ?? blingStatus.enabled,
    isEditing,
    skipBling: false,
  });
```

**Atenção:** o bloco que existe hoje já monta `gate` com esses campos, sem
`skipBling`. Substitua-o inteiro pelo trecho acima; não crie um segundo `gate`.

- [ ] **Step 2: Derivar quando a caixa aparece**

Logo abaixo de `const blingEditable = ...` (hoje linha 120), adicione:

```tsx
  // A escapatoria so faz sentido quando o Bling estaria no caminho: modo bling
  // (o vendedor teria que montar o pedido) ou erro (o modal estaria travado).
  const podeEscaparDoBling =
    blingEditable && (gateSemSkip.mode === "bling" || gateSemSkip.mode === "error");
```

- [ ] **Step 3: Renderizar a caixa**

Imediatamente antes do bloco `{gate.mode === "loading" && blingEditable ? (`
(hoje linha 701), insira:

```tsx
          {podeEscaparDoBling && (
            <label className="flex items-start gap-2 px-1 py-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={skipBling}
                onChange={(e) => setSkipBling(e.target.checked)}
                className="mt-[3px] h-[14px] w-[14px] accent-[#111111]"
              />
              <span className="text-[13px] leading-[1.4] text-[#111111]">
                Registrar sem enviar ao Bling
                <span className="block text-[12px] text-[#7b7b78]">
                  Use para pedidos que já foram lançados na outra empresa. A venda
                  entra no CRM e nenhum pedido é criado no Bling.
                </span>
              </span>
            </label>
          )}
```

- [ ] **Step 4: Verificar na tela**

Run: `npm run type-check`
Expected: sem erros.

Depois, com o app rodando, abra `/painel-vendas` → "Registrar Venda" e confirme:
1. Com o Bling conectado, a caixa aparece e o formulário mostra o catálogo.
2. Marcando a caixa, o formulário troca para "Produto / Serviço" e "Valor (R$)".
3. Desmarcando, volta para o catálogo. A caixa **não** some ao ser marcada.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sales/sale-create-modal.tsx
git commit -m "feat(vendas): checkbox registrar sem enviar ao Bling"
```

---

## Task 3: `POST /api/sales` grava `origin = 'manual'`

**Files:**
- Modify: `frontend/src/app/api/sales/route.ts`

Hoje a rota não define `origin` e a coluna cai no `DEFAULT 'crm'`
(`supabase/migrations/20260818_bling_integration.sql:146`), que significa "criada
no CRM **e** virou pedido no Bling" — o oposto do que a escapatória faz.

- [ ] **Step 1: Corrigir o insert**

Em `frontend/src/app/api/sales/route.ts`, no `.insert({...})` do `POST` (hoje
linha ~100), adicione a linha `origin` logo após `notes`:

```ts
    .insert({
      lead_id: body.lead_id,
      sold_at: body.sold_at || new Date().toISOString(),
      value: Number(body.value),
      product: body.product.trim(),
      sold_by: body.sold_by || null,
      deal_id: dealId,
      conversation_id: body.conversation_id || null,
      notes: body.notes?.trim() || null,
      // Explicito de proposito: o DEFAULT da coluna e 'crm', que significa
      // "criada no CRM E virou pedido no Bling". Esta rota e o caminho SEM
      // pedido no ERP, entao 'manual' e o valor correto.
      origin: "manual",
    })
```

- [ ] **Step 2: Verificar tipos**

Run: `npm run type-check`
Expected: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/sales/route.ts
git commit -m "fix(vendas): POST /api/sales grava origin=manual, nao o default crm"
```

---

## Task 4: Selo "Fora do Bling" na tabela

**Files:**
- Modify: `frontend/src/lib/sale-display.ts`
- Modify: `frontend/src/components/sales/sales-table.tsx`
- Test: `frontend/src/lib/sale-display.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

Adicione em `frontend/src/lib/sale-display.test.ts`, dentro do describe existente:

```ts
  it("fora do Bling e definido pela ausencia de pedido, nao pelo origin", () => {
    expect(foraDoBling({ ...base, origin: "manual", bling_order_id: null })).toBe(true);
    expect(foraDoBling({ ...base, origin: "crm", bling_order_id: null })).toBe(true);
    expect(foraDoBling({ ...base, origin: "bling", bling_order_id: 5991 })).toBe(false);
    expect(foraDoBling({ ...base, origin: "crm", bling_order_id: 5991 })).toBe(false);
  });
```

E acrescente `foraDoBling` ao import de `@/lib/sale-display` no topo do arquivo.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `npx vitest run src/lib/sale-display.test.ts`
Expected: FAIL — `foraDoBling is not a function` / erro de import.

- [ ] **Step 3: Implementar**

Adicione ao final de `frontend/src/lib/sale-display.ts`:

```ts
/**
 * A venda esta fora do Bling? O discriminador e a AUSENCIA de pedido, nao o
 * `origin`: `bling_order_id IS NULL` e a unica condicao verdadeira para os tres
 * casos que estao de fato fora do ERP (venda anterior a integracao, venda da
 * escapatoria, venda legada) e falsa para os que estao dentro.
 */
export function foraDoBling(sale: Pick<Sale, "bling_order_id">): boolean {
  return !sale.bling_order_id;
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `npx vitest run src/lib/sale-display.test.ts`
Expected: PASS.

- [ ] **Step 5: Usar na tabela**

Em `frontend/src/components/sales/sales-table.tsx`, troque o import da linha 6 por:

```tsx
import { blingOrderUrl, foraDoBling, orderLabel, saleStatus, type StatusTone } from "@/lib/sale-display";
```

E substitua o `—` da célula de pedido (hoje linhas 94-95):

```tsx
                  {!pedido ? (
                    foraDoBling(sale) ? (
                      <span
                        className="text-[11px] text-[#7b7b78] border border-[#dedbd6] rounded-[3px] px-[6px] py-[2px]"
                        title="Venda registrada no CRM sem pedido no Bling"
                      >
                        Fora do Bling
                      </span>
                    ) : (
                      <span className="text-[#7b7b78]">—</span>
                    )
                  ) : pedidoUrl ? (
```

- [ ] **Step 6: Verificar e commitar**

Run: `npm run type-check`
Expected: sem erros.

```bash
git add frontend/src/lib/sale-display.ts frontend/src/lib/sale-display.test.ts frontend/src/components/sales/sales-table.tsx
git commit -m "feat(vendas): selo Fora do Bling na tabela"
```

---

## Task 5: Função pura do escopo de vendas

**Files:**
- Create: `frontend/src/lib/sales/sales-scope.ts`
- Test: `frontend/src/lib/sales/sales-scope.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

Crie `frontend/src/lib/sales/sales-scope.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { salesScopeFilter, podeVerVenda } from "@/lib/sales/sales-scope";

const admin = { userId: "u1", email: "comercial@cafecanastra.com", role: "admin" };
const vendedor = { userId: "u2", email: "joao@cafecanastra.com", role: "vendedor" };

describe("salesScopeFilter", () => {
  it("admin nao tem escopo", () => {
    expect(salesScopeFilter(admin, true)).toBeNull();
  });

  it("flag desligada devolve o comportamento global", () => {
    expect(salesScopeFilter(vendedor, false)).toBeNull();
  });

  it("vendedor ve as dele mais as do Bling", () => {
    expect(salesScopeFilter(vendedor, true)).toBe(
      "sold_by.ilike.joao@cafecanastra.com,origin.eq.bling"
    );
  });

  // ilike e o que torna a comparacao insensivel a maiusculas. O seed grava
  // "Comercial2@cafecanastra.com" com C maiusculo; se a comparacao fosse `eq`,
  // uma diferenca de grafia casaria zero linhas e o painel abriria vazio.
  it("usa ilike, nao eq", () => {
    expect(salesScopeFilter({ ...vendedor, email: "Joao@Cafecanastra.com" }, true)).toBe(
      "sold_by.ilike.Joao@Cafecanastra.com,origin.eq.bling"
    );
  });

  // Fail-closed: sem e-mail nao da para montar escopo, e devolver null (=sem
  // escopo) abriria tudo. O chamador precisa tratar isso como 401.
  it("vendedor sem e-mail e recusado, nao liberado", () => {
    expect(() => salesScopeFilter({ ...vendedor, email: "" }, true)).toThrow();
  });

  // Virgula quebraria a sintaxe do `or` do PostgREST e poderia injetar um termo
  // extra no filtro. E-mail valido nao tem virgula; se tiver, recusamos.
  it("e-mail com virgula e recusado", () => {
    expect(() => salesScopeFilter({ ...vendedor, email: "a,b@x.com" }, true)).toThrow();
  });
});

describe("podeVerVenda", () => {
  it("admin ve qualquer venda", () => {
    expect(podeVerVenda({ sold_by: "outro@x.com", origin: "manual" }, admin, true)).toBe(true);
  });

  it("vendedor ve a propria", () => {
    expect(podeVerVenda({ sold_by: "JOAO@cafecanastra.com", origin: "manual" }, vendedor, true)).toBe(true);
  });

  it("vendedor ve as do Bling", () => {
    expect(podeVerVenda({ sold_by: null, origin: "bling" }, vendedor, true)).toBe(true);
  });

  it("vendedor nao ve a de outro", () => {
    expect(podeVerVenda({ sold_by: "outro@x.com", origin: "manual" }, vendedor, true)).toBe(false);
  });

  it("vendedor nao ve venda do CRM sem dono", () => {
    expect(podeVerVenda({ sold_by: null, origin: "manual" }, vendedor, true)).toBe(false);
  });

  it("flag desligada libera tudo", () => {
    expect(podeVerVenda({ sold_by: "outro@x.com", origin: "manual" }, vendedor, false)).toBe(true);
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `npx vitest run src/lib/sales/sales-scope.test.ts`
Expected: FAIL — `Failed to resolve import "@/lib/sales/sales-scope"`.

- [ ] **Step 3: Implementar**

Crie `frontend/src/lib/sales/sales-scope.ts`:

```ts
/**
 * Quem enxerga quais vendas em /painel-vendas.
 *
 * Funcao pura e separada da rota porque a regra tem duas consequencias que
 * precisam de teste: a comparacao de e-mail e insensivel a maiusculas (o seed
 * grava "Comercial2@..." com C maiusculo, e `eq` casaria zero linhas), e um
 * e-mail ausente ou com virgula LEVANTA em vez de devolver "sem escopo" —
 * devolver null ali abriria a base inteira por acidente.
 */
export interface SalesScopeUser {
  userId: string;
  email: string | undefined;
  role: string | undefined;
}

export class SalesScopeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SalesScopeError";
  }
}

function emailValido(email: string | undefined): string {
  const limpo = (email ?? "").trim();
  if (!limpo) throw new SalesScopeError("usuario sem e-mail: escopo de vendas indeterminado");
  // A virgula separa termos no `or` do PostgREST. E-mail nao tem virgula; se
  // tiver, recusamos em vez de montar um filtro com um termo a mais.
  if (limpo.includes(",")) throw new SalesScopeError("e-mail invalido para escopo de vendas");
  return limpo;
}

function semEscopo(user: SalesScopeUser, enabled: boolean): boolean {
  return !enabled || user.role === "admin";
}

/**
 * Filtro `or` do PostgREST, ou `null` quando nao ha escopo (admin ou flag
 * desligada). O vendedor ve as vendas dele MAIS as importadas do ERP, que nao
 * tem dono e sao o material de conferencia dele.
 */
export function salesScopeFilter(user: SalesScopeUser, enabled: boolean): string | null {
  if (semEscopo(user, enabled)) return null;
  return `sold_by.ilike.${emailValido(user.email)},origin.eq.bling`;
}

/** Mesma regra, aplicada a uma linha ja carregada (rota /api/sales/[id]). */
export function podeVerVenda(
  sale: { sold_by: string | null; origin: string | null },
  user: SalesScopeUser,
  enabled: boolean,
): boolean {
  if (semEscopo(user, enabled)) return true;
  const email = emailValido(user.email).toLowerCase();
  if (sale.origin === "bling") return true;
  return (sale.sold_by ?? "").toLowerCase() === email;
}

/** Le a chave de rollback. Ligada por padrao: so "0"/"false" desligam. */
export function scopeAtivo(): boolean {
  const raw = (process.env.SALES_SCOPE_BY_SELLER ?? "").trim().toLowerCase();
  return raw !== "0" && raw !== "false";
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `npx vitest run src/lib/sales/sales-scope.test.ts`
Expected: PASS — 12 testes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/sales/sales-scope.ts frontend/src/lib/sales/sales-scope.test.ts
git commit -m "feat(vendas): funcao pura do escopo de vendas por vendedor"
```

---

## Task 6: Aplicar o escopo em `GET /api/sales`

**Files:**
- Modify: `frontend/src/app/api/sales/route.ts`

- [ ] **Step 1: Importar e resolver o usuário**

No topo de `frontend/src/app/api/sales/route.ts`, junto dos imports existentes:

```ts
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { salesScopeFilter, scopeAtivo, SalesScopeError } from "@/lib/sales/sales-scope";
```

- [ ] **Step 2: Aplicar no `GET`**

Logo após `const supabase = await getServiceSupabase();` dentro do `GET`, insira:

```ts
  // Escopo imposto no servidor. A rota usa service role (ignora RLS) e ate hoje
  // nao checava sessao: o `sold_by` da query string era conveniencia, nao
  // seguranca. Fail-closed — sem identidade, 401.
  let escopo: string | null = null;
  if (scopeAtivo()) {
    try {
      const user = await getCurrentUser();
      escopo = salesScopeFilter(
        { userId: user.userId, email: user.email, role: user.role },
        true,
      );
    } catch (err) {
      const msg = err instanceof SalesScopeError ? err.message : "Não autenticado";
      return NextResponse.json({ error: msg }, { status: 401 });
    }
  }
```

E logo depois da linha `if (soldBy) query = query.eq("sold_by", soldBy);`, adicione:

```ts
  // Depois dos filtros da URL, nunca antes: o escopo restringe, e nenhum
  // parametro do cliente pode alarga-lo.
  if (escopo) query = query.or(escopo);
```

- [ ] **Step 3: Ajustar `getCurrentUser` para devolver o e-mail**

`getCurrentUser` hoje devolve só `{ userId, role }`. Em
`frontend/src/lib/supabase/pipeline-access.ts`, adicione `email` à interface e ao
retorno:

```ts
export interface CurrentUser {
  userId: string;
  // Opcional de proposito: `pipeline-access.test.ts` e outros chamadores
  // constroem CurrentUser a mao. Campo obrigatorio quebraria esses literais sem
  // ganho nenhum — quem precisa do e-mail e so o escopo de vendas, e ele ja
  // trata ausencia levantando SalesScopeError.
  email?: string;
  role: string | undefined;
}
```

e dentro de `getCurrentUser`, troque o `return` por:

```ts
    return {
      userId,
      email: data.user?.email,
      role: data.user?.app_metadata?.role as string | undefined,
    };
```

- [ ] **Step 4: Verificar**

Run: `npm run type-check`
Expected: sem erros. Se algum chamador de `getCurrentUser` quebrar, é porque
construía o objeto à mão — adicione `email: undefined` nesses pontos.

Run: `npm test`
Expected: PASS — incluindo `pipeline-access.test.ts`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/sales/route.ts frontend/src/lib/supabase/pipeline-access.ts
git commit -m "feat(vendas): escopo por vendedor em GET /api/sales"
```

---

## Task 7: Aplicar o escopo em `GET /api/sales/metrics`

**Files:**
- Modify: `frontend/src/app/api/sales/metrics/route.ts`

Sem isso o KPI do topo discorda da lista logo abaixo.

- [ ] **Step 1: Aplicar**

No topo do arquivo, adicione os mesmos imports da Task 6:

```ts
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { salesScopeFilter, scopeAtivo, SalesScopeError } from "@/lib/sales/sales-scope";
```

Logo após `const supabase = await getServiceSupabase();`:

```ts
  let escopo: string | null = null;
  if (scopeAtivo()) {
    try {
      const user = await getCurrentUser();
      escopo = salesScopeFilter(
        { userId: user.userId, email: user.email, role: user.role },
        true,
      );
    } catch (err) {
      const msg = err instanceof SalesScopeError ? err.message : "Não autenticado";
      return NextResponse.json({ error: msg }, { status: 401 });
    }
  }
```

E logo antes de `const { data: periodSales, error } = await periodQuery;`:

```ts
  if (escopo) periodQuery = periodQuery.or(escopo);
```

**Nota deliberada:** a RPC `get_avg_repurchase_cycle_days` continua global — ela
agrega no banco e não aceita escopo. O ciclo médio de recompra é métrica da
operação, não do vendedor. Não tente escopá-la nesta task.

- [ ] **Step 2: Verificar**

Run: `npm run type-check`
Expected: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/sales/metrics/route.ts
git commit -m "feat(vendas): escopo por vendedor nas metricas de venda"
```

---

## Task 8: Aplicar o escopo em `/api/sales/[id]`

**Files:**
- Modify: `frontend/src/app/api/sales/[id]/route.ts`

Sem esta task o escopo é cosmético: `/painel-vendas?sale_id=` é deep-link e
qualquer id abriria qualquer venda.

- [ ] **Step 1: Criar o helper local de guarda**

No topo de `frontend/src/app/api/sales/[id]/route.ts`, adicione os imports e um
helper reutilizado pelos três verbos:

```ts
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { podeVerVenda, scopeAtivo, SalesScopeError } from "@/lib/sales/sales-scope";

type Guarda = { ok: true } | { ok: false; resposta: NextResponse };

/**
 * Venda fora do escopo responde 404, nao 403: 403 confirmaria que ela existe.
 */
async function guardaDeVenda(supabase: Awaited<ReturnType<typeof getServiceSupabase>>, id: string): Promise<Guarda> {
  if (!scopeAtivo()) return { ok: true };

  const { data: linha, error } = await supabase
    .from("sales")
    .select("sold_by, origin")
    .eq("id", id)
    .maybeSingle();
  if (error) {
    return { ok: false, resposta: NextResponse.json({ error: error.message }, { status: 500 }) };
  }
  if (!linha) {
    return { ok: false, resposta: NextResponse.json({ error: "Venda não encontrada." }, { status: 404 }) };
  }

  try {
    const user = await getCurrentUser();
    const pode = podeVerVenda(linha, { userId: user.userId, email: user.email, role: user.role }, true);
    if (!pode) {
      return { ok: false, resposta: NextResponse.json({ error: "Venda não encontrada." }, { status: 404 }) };
    }
    return { ok: true };
  } catch (err) {
    const msg = err instanceof SalesScopeError ? err.message : "Não autenticado";
    return { ok: false, resposta: NextResponse.json({ error: msg }, { status: 401 }) };
  }
}
```

- [ ] **Step 2: Chamar nos três verbos**

Em `GET`, `PATCH` e `DELETE`, logo após a linha
`const supabase = await getServiceSupabase();`, insira:

```ts
  const guarda = await guardaDeVenda(supabase, id);
  if (!guarda.ok) return guarda.resposta;
```

Nos três verbos a guarda tem que rodar **antes** da operação: antes do `.select()`
no `GET`, antes do `.update()` no `PATCH` e antes do `.delete()` no `DELETE`.
Colocá-la logo após o `getServiceSupabase()` garante isso nos três sem exigir
atenção caso a caso.

No `PATCH`, note que `const body = await request.json();` vem antes do
`getServiceSupabase()` no arquivo atual — deixe como está e ponha a guarda depois
do `getServiceSupabase()`, como nos outros dois. Ler o corpo antes de recusar é
inofensivo: nada foi escrito.

- [ ] **Step 3: Verificar**

Run: `npm run type-check`
Expected: sem erros.

Run: `npm test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/app/api/sales/[id]/route.ts"
git commit -m "feat(vendas): escopo por vendedor no deep-link e na edicao de venda"
```

---

## Task 9: Hook `useCurrentUser` e os quatro chamadores do modal

**Files:**
- Create: `frontend/src/hooks/use-current-user.ts`
- Modify: `frontend/src/components/conversas/contact-detail.tsx`
- Modify: `frontend/src/app/(authenticated)/painel-vendas/page.tsx`
- Modify: `frontend/src/components/deals/deal-detail-sidebar.tsx`
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx`

Sem esta task, venda registrada por três das quatro telas grava `sold_by = NULL`,
e "vejo o que é meu" continua mentindo.

- [ ] **Step 1: Criar o hook**

Crie `frontend/src/hooks/use-current-user.ts`, no molde de `use-bling-status.ts`:

```ts
"use client";

import { useState, useEffect } from "react";

/**
 * E-mail do usuario logado, com cache em memoria compartilhado.
 *
 * Existe porque quatro telas abrem o modal de venda e cada uma repetiria a
 * chamada de sessao. Ate 24/08/2026 so `contact-detail` buscava esse e-mail, e
 * as outras tres registravam venda sem vendedor.
 */
let cache: string | null = null;
let inflight: Promise<string> | null = null;

async function fetchEmail(): Promise<string> {
  if (cache !== null) return cache;
  if (!inflight) {
    inflight = import("@/lib/supabase/client")
      .then(({ createClient }) => createClient().auth.getSession())
      .then(({ data: { session } }) => {
        cache = session?.user?.email ?? "";
        return cache;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function useCurrentUserEmail(): string {
  const [email, setEmail] = useState<string>(cache ?? "");

  useEffect(() => {
    if (cache !== null) return;
    let vivo = true;
    fetchEmail().then((e) => vivo && setEmail(e));
    return () => {
      vivo = false;
    };
  }, []);

  return email;
}
```

- [ ] **Step 2: `contact-detail.tsx` passa a usar o hook**

Remova o estado e o `useEffect` locais (hoje linha 69 e linhas 94-100) e troque por
uma chamada ao hook. Adicione o import:

```tsx
import { useCurrentUserEmail } from "@/hooks/use-current-user";
```

Substitua a linha `const [currentUserEmail, setCurrentUserEmail] = useState<string>("");` por:

```tsx
  const currentUserEmail = useCurrentUserEmail();
```

E apague este bloco inteiro (hoje linhas 94-100):

```tsx
  useEffect(() => {
    import("@/lib/supabase/client").then(({ createClient }) => {
      createClient().auth.getSession().then(({ data: { session } }) => {
        setCurrentUserEmail(session?.user?.email ?? "");
      });
    });
  }, []);
```

- [ ] **Step 3: `painel-vendas/page.tsx` passa a prop**

Adicione o import `import { useCurrentUserEmail } from "@/hooks/use-current-user";`,
declare `const currentUserEmail = useCurrentUserEmail();` junto dos outros hooks do
componente, e adicione a prop ao `<SaleCreateModal>` (hoje linha 113):

```tsx
        <SaleCreateModal
          pickLead={!editingSale}
          editingSale={editingSale}
          currentUserEmail={currentUserEmail}
          onClose={() => { setShowCreate(false); setEditingSale(null); }}
          onSaved={() => { refetch(); setShowCreate(false); setEditingSale(null); }}
        />
```

- [ ] **Step 4: `deal-detail-sidebar.tsx` passa a prop**

Mesmo import e mesma declaração; a prop entra no `<SaleCreateModal>` (hoje linha 257):

```tsx
        <SaleCreateModal
          leadId={deal.lead_id}
          lockedDealId={deal.id}
          lockedDealTitle={deal.title}
          currentUserEmail={currentUserEmail}
          onClose={() => setShowFinalizeSale(false)}
          onSaved={() => setShowFinalizeSale(false)}
        />
```

- [ ] **Step 5: `lead-detail-modal.tsx` passa a prop**

Mesmo import e mesma declaração; a prop entra no `<SaleCreateModal>` (hoje linha 668):

```tsx
          <SaleCreateModal
            leadId={lead.id}
            currentUserEmail={currentUserEmail}
            onClose={() => setShowCreateSale(false)}
            onSaved={() => {
              setShowCreateSale(false);
              fetchLeadDeals();
```

(mantenha o resto do `onSaved` como está)

- [ ] **Step 6: Verificar que nenhum chamador ficou de fora**

Run: `grep -rn "SaleCreateModal" frontend/src --include=*.tsx | grep -v "sale-create-modal.tsx"`
Expected: exatamente 4 linhas de import + 4 de uso, e cada uso com `currentUserEmail`.

Run: `npm run type-check`
Expected: sem erros.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/use-current-user.ts frontend/src/components/conversas/contact-detail.tsx "frontend/src/app/(authenticated)/painel-vendas/page.tsx" frontend/src/components/deals/deal-detail-sidebar.tsx frontend/src/components/leads/lead-detail-modal.tsx
git commit -m "fix(vendas): os quatro chamadores do modal passam o usuario logado"
```

---

## Task 10: Migration de normalização do `sold_by`

**Files:**
- Create: `supabase/migrations/20260824_sales_sold_by_normalizacao.sql`

**NÃO aplicar em produção nesta task.** O plano só cria o arquivo; aplicar é
decisão do usuário, depois do deploy.

- [ ] **Step 1: Criar a migration**

Crie `supabase/migrations/20260824_sales_sold_by_normalizacao.sql`:

```sql
-- Normaliza o vendedor das vendas registradas no CRM.
--
-- Contexto (medido em producao em 24/08/2026): das 91 vendas com origin='manual',
-- 63 estao sem `sold_by` porque tres das quatro telas que abrem o modal nao
-- passavam o usuario logado. As 28 preenchidas sao todas de joao@cafecanastra.com.
-- Sem esta normalizacao, o escopo por vendedor esconderia as 63 do proprio joao.
--
-- Confirmado pelo usuario: foi ele quem vendeu todas.

ALTER TABLE sales ADD COLUMN IF NOT EXISTS sold_by_source   text;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS sold_by_anterior text;

-- Guarda: um e-mail errado carimbaria 91 vendas para um usuario inexistente e o
-- painel abriria vazio, sem erro em lugar nenhum.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM auth.users WHERE lower(email) = 'joao@cafecanastra.com'
  ) THEN
    RAISE EXCEPTION 'joao@cafecanastra.com nao existe em auth.users';
  END IF;
END $$;

UPDATE sales
   SET sold_by_anterior = sold_by,
       sold_by          = 'joao@cafecanastra.com',
       sold_by_source   = 'normalizacao_joao'
 WHERE origin = 'manual'
   AND (sold_by IS NULL OR lower(sold_by) <> 'joao@cafecanastra.com')
   -- Idempotencia: rodar duas vezes nao sobrescreve `sold_by_anterior` com o
   -- valor ja normalizado, o que destruiria a capacidade de desfazer.
   AND sold_by_source IS NULL
   -- Delimita ao passado. Sem isto, esta migration e uma arma carregada apontada
   -- para o futuro: no dia em que existir um segundo vendedor, uma reexecucao
   -- transferiria as vendas dele para o joao sem nada avisar.
   AND created_at < '2026-08-24';

-- ROLLBACK (nao executar; guardado aqui de proposito):
--   UPDATE sales
--      SET sold_by = sold_by_anterior, sold_by_anterior = NULL, sold_by_source = NULL
--    WHERE sold_by_source = 'normalizacao_joao';
```

- [ ] **Step 2: Conferir a sintaxe sem aplicar**

Run: `grep -c "" supabase/migrations/20260824_sales_sold_by_normalizacao.sql`
Expected: o arquivo existe e tem conteúdo.

Não rode a migration. Não a aplique via `/pg/query`. O usuário decide quando.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260824_sales_sold_by_normalizacao.sql
git commit -m "feat(vendas): migration de normalizacao do sold_by (nao aplicada)"
```

---

## Task 11: Verificação final

**Files:** nenhum.

- [ ] **Step 1: Suíte inteira**

Run (de `frontend/`): `npm test`
Expected: PASS, sem testes pulados. Anote o total de testes.

- [ ] **Step 2: Tipos**

Run: `npm run type-check`
Expected: sem saída (sucesso).

- [ ] **Step 3: Lint**

Run: `npm run lint`
Expected: sem erros novos.

- [ ] **Step 4: Confirmar que nada chama o Bling**

Run: `git diff master --stat -- backend/`
Expected: **nenhum arquivo** — esta entrega não toca o backend Python, portanto
não chega perto de `POST /contatos`, `POST /pedidos/vendas` nem
`PUT /pedidos/vendas/{id}`.

- [ ] **Step 5: Relatar**

Reporte ao usuário: total de testes, o que foi verificado, e as duas pendências
que ficam com ele — aplicar a migration e decidir o push para `master` (que
dispara deploy de produção).

---

## Pendências que NÃO são desta entrega

- **Aplicar a migration** no Supabase. Enquanto não for aplicada, as 63 vendas
  antigas ficam invisíveis para o joao no painel escopado.
- **`SALES_SCOPE_BY_SELLER`** não precisa ser configurada: a ausência da variável
  significa "ligada". Definir como `0` ou `false` reverte o escopo sem deploy.
- **Deduplicação de 242 leads e ~10 vendas** — projeto separado, com spec própria.
- **Push para `master`** — dispara deploy de produção, e depende de autorização
  explícita do usuário (CLAUDE.md, regra 1).
