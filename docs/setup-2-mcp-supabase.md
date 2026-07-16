# Setup: 2 MCPs do Supabase (2 contas) no mesmo projeto

Este projeto usa **dois servidores MCP do Supabase simultaneamente**, cada um apontando
para uma **conta/organização diferente**:

- `supabase-homolog` → ambiente de homologação
- `supabase-prod` → ambiente de produção

Ambos usam o mesmo pacote oficial (`@supabase/mcp-server-supabase`), rodado via `npx`.
A separação é feita **por Personal Access Token (PAT)** — cada servidor recebe um token
diferente, e é o token que define qual conta/organização o MCP enxerga.

---

## 1. Pré-requisitos

- **Node.js + npx** instalados (testado com Node v24 / npx 11). Confirme:
  ```
  node -v
  npx -v
  ```
- O pacote NÃO precisa ser instalado manualmente — o `-y` do `npx` baixa e roda na hora.

---

## 2. Como funciona a configuração

A config fica em um arquivo **`.mcp.json` na raiz do projeto** (escopo de projeto do
Claude Code). Estrutura:

```json
{
  "mcpServers": {
    "supabase-homolog": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "@supabase/mcp-server-supabase", "--access-token", "SEU_TOKEN_HOMOLOG"]
    },
    "supabase-prod": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "@supabase/mcp-server-supabase", "--access-token", "SEU_TOKEN_PROD"]
    }
  }
}
```

Pontos-chave:

- **Dois blocos independentes** dentro de `mcpServers`, com nomes distintos
  (`supabase-homolog` e `supabase-prod`). O nome é livre — é só o rótulo que aparece
  no `/mcp`.
- **O que separa as contas é o `--access-token`.** Cada bloco recebe um PAT de uma conta
  diferente. Não há mágica além disso — mesmo pacote, tokens diferentes.
- **`"command": "cmd"` + `"/c"` é específico de Windows.** Isso faz o Windows resolver o
  `npx` corretamente. Em **Linux/macOS**, troque para:
  ```json
  {
    "command": "npx",
    "args": ["-y", "@supabase/mcp-server-supabase", "--access-token", "SEU_TOKEN"]
  }
  ```

---

## 3. Passo a passo para replicar na sua máquina

1. **Gere um Personal Access Token para CADA conta Supabase:**
   - Entre em https://supabase.com/dashboard/account/tokens **logado na conta de homolog**
     → "Generate new token" → copie.
   - Faça logout / troque para a **conta de produção** e repita para gerar o segundo token.
   - (Se as duas orgs estiverem sob o mesmo login, basta gerar dois tokens; o que importa
     é que cada token dê acesso à org/projeto certo.)

2. **Crie o arquivo `.mcp.json` na raiz do projeto** com o conteúdo da seção 2, colocando
   cada token no bloco correspondente.
   - ⚠️ `.mcp.json` está no **`.gitignore`** — ele **não vem no clone**. Por isso cada dev
     precisa criar o seu localmente. Isso é proposital: os tokens são pessoais/secretos e
     **não devem ser commitados**.

3. **Reinicie o Claude Code** (ou recarregue os MCPs) no diretório do projeto.

4. **Valide** com o comando `/mcp`. Deve aparecer:
   ```
   supabase-homolog · connected · 29 tools
   supabase-prod    · connected · 29 tools
   ```

---

## 4. Como usar depois de conectado

- As ferramentas ficam prefixadas pelo nome do servidor, ex.:
  `supabase-homolog__execute_sql`, `supabase-prod__list_tables`, etc.
- **Sempre confira o prefixo antes de rodar comandos destrutivos** — é fácil rodar em
  `prod` achando que é `homolog`. Prefira homolog para testes.
- Se quiser restringir cada servidor a um único projeto (em vez de enxergar a org toda),
  o pacote aceita a flag `--project-ref <ref>`. Também há `--read-only` para travar
  escrita. Ex.:
  ```
  ...@supabase/mcp-server-supabase --project-ref abcd1234 --read-only --access-token SEU_TOKEN
  ```

---

## 5. Segurança

- **Nunca commite o `.mcp.json`** com tokens reais. Ele já está no `.gitignore` deste repo.
- Tokens são equivalentes a credenciais da conta — trate como senha. Se vazar, revogue no
  dashboard (mesma tela de tokens) e gere outro.
- Para o ambiente de produção, considere usar `--read-only` no bloco `supabase-prod`,
  liberando escrita só quando necessário.
