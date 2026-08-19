# Terminar a integração Bling — instruções para o Claude da VPS

> **Cole este documento inteiro no Claude Code rodando na VPS.**
> Ele é o briefing completo: o que já existe, o que falta, e o que não pode ser reaproveitado.

---

## Sua missão

Terminar a integração CRM ↔ Bling deste repositório. O **código está pronto e testado**; o que falta é tudo que só pode ser feito com acesso real ao Bling e ao Supabase de produção: criar o aplicativo, fazer o fluxo OAuth funcionar de ponta a ponta, aplicar o schema, configurar os webhooks e validar com uma venda de verdade.

Ao terminar, **commite tudo no GitHub** (instruções no final).

---

## Regra número um: a autenticação é NOVA, do zero

Existe na VPS um projeto chamado **`agente-bling`** que já conversa com o Bling. **Use-o como referência de como a API se comporta na prática, mas não reaproveite credencial nenhuma dele.**

Nós vamos usar:
- **outro aplicativo** dentro do Bling (novo cadastro, na Central de Extensões);
- **outro `client_id` / `client_secret`**;
- **outro conjunto de tokens**.

Portanto o fluxo OAuth precisa ser refeito inteiro para esta integração. Não copie `access_token`, `refresh_token`, `client_id` nem `client_secret` do `agente-bling` — os tokens são vinculados ao aplicativo que os emitiu e não funcionam fora dele. Copiar credencial entre aplicativos é a forma mais rápida de queimar as duas integrações ao mesmo tempo.

### O que vale olhar no `agente-bling`

Vá ler o projeto antes de começar, mas com objetivo específico. O que interessa lá é **comportamento observado da API em produção**, não código para copiar:

- Como o cadastro do aplicativo foi feito no painel do Bling (quais escopos, qual visibilidade, qual URL de redirecionamento) — para você repetir o processo, não os valores.
- Qual o formato real da URL de um pedido no painel do Bling (precisamos disso, ver passo 8 abaixo — não está documentado no OpenAPI deles).
- Se eles esbarraram em algum limite, bloqueio de IP, ou comportamento da API que a documentação não descreve.
- Como resolveram a renovação de token na prática e com que frequência ela falha.

**O que NÃO copiar:** a arquitetura. Esta integração tem desenho próprio e mais restrito — token-bucket central, JWT obrigatório, tokens no Postgres, fila de retentativa com chave de idempotência. Está tudo explicado na seção "Armadilhas" mais abaixo, e cada peça existe por um motivo que custou caro descobrir.

---

## O que já existe neste repositório

Branch: **`master`** (a integração foi mergeada). Módulos:

```
backend/app/bling/
  config.py            flags e constantes (API_BASE, limites)
  errors.py            hierarquia de erros; a tupla TRANSIENT decide o que é retentável
  ratelimit.py         token-bucket Redis, 3 req/s + teto diário, script Lua único
  auth.py              OAuth: authorize, troca de code, refresh serializado por lock
  client.py            BlingClient — TODA chamada ao Bling passa por aqui
  products.py          espelho do catálogo
  sync.py              espelho de contatos, formas de pagamento, vendedores
  contacts.py          resolução de identidade lead ↔ contato (anti-duplicação)
  orders.py            monta e cria o pedido; projeta em sales
  jobs.py              outbox: fila de retentativa com chave de idempotência
  webhook_router.py    POST /webhook/bling — valida HMAC e devolve 200 rápido
  webhook_processor.py processa os eventos fora do request
  backfill.py          importação retomável de 12 meses
  router.py            endpoints /api/bling/*
```

Frontend: `frontend/src/lib/bling.ts`, `bling-order-state.ts`, `documento.ts`, `sale-display.ts`; componentes em `frontend/src/components/sales/` e `frontend/src/components/config/bling-settings.tsx`; proxies em `frontend/src/app/api/bling/`.

**Documentos de referência (leia os dois antes de mexer):**
- `docs/superpowers/specs/2026-08-18-crm-bling-integracao-design.md` — o desenho e o porquê de cada decisão.
- `docs/superpowers/plans/2026-08-18-crm-bling-integracao.md` — o plano de 17 tasks, com o checklist de go-live no fim.

**Estado dos testes quando isto foi escrito:** backend 3.193 passed / 3 skipped; frontend 339 passed. Se você quebrar algo, vai aparecer.

**Importante:** nada disso foi validado contra o Bling real. Todos os testes usam dublês. Você é a primeira pessoa a rodar isso contra a API de verdade.

---

## O SQL — está pronto, falta aplicar

O arquivo é **`supabase/migrations/20260818_bling_integration.sql`**. Ele cria:

- `bling_credentials` — tokens OAuth (RLS ligado, **sem** policy de leitura para `authenticated`, porque guarda `refresh_token`)
- `bling_products`, `bling_contacts`, `bling_payment_methods`, `bling_sellers`, `bling_seller_map`, `bling_sync_state` — os espelhos
- `leads.bling_contact_id` com índice UNIQUE parcial + o seed a partir de `metadata->>'id_bling'`
- 9 colunas novas em `sales` + `sale_items`
- `bling_webhook_events` (idempotência) e `bling_jobs` (outbox)

### ⚠️ Antes de aplicar, rode esta query

O índice UNIQUE é criado **antes** do `UPDATE` que semeia os 1.208 leads da reativação. Se dois leads tiverem o mesmo `metadata->>'id_bling'`, o `UPDATE` viola a unicidade e **a migration inteira aborta** — o runner executa o arquivo como uma query só.

```sql
SELECT metadata->>'id_bling' AS id_bling, count(*)
  FROM leads
 WHERE metadata->>'id_bling' ~ '^[0-9]+$'
 GROUP BY 1 HAVING count(*) > 1;
```

**Vazio** → aplique sem medo.
**Com linhas** → decida qual lead fica com o vínculo antes de rodar. Não force; um vínculo errado aqui significa nota fiscal no CNPJ errado depois.

---

## Passo a passo

### 1. Criar o aplicativo no Bling

Central de Extensões → Área do Integrador → Criar aplicativo. Visibilidade **privada** (opera na própria conta, não passa por homologação).

**Escopos necessários:** contatos, produtos, pedidos de venda, formas de pagamento, vendedores.

> Os escopos precisam existir **antes** de você configurar o webhook. Sem o escopo correspondente, o recurso `order` **nem aparece** na aba de Webhooks do aplicativo. Se você tentar configurar o webhook primeiro, vai achar que é bug do Bling.

**URL de redirecionamento:** `https://api.canastrainteligencia.com/api/bling/oauth/callback`
Ela precisa ser idêntica, caractere por caractere, à variável `BLING_REDIRECT_URI`.

### 2. Preencher o `.env` de produção

```
BLING_ENABLED=true
BLING_CLIENT_ID=<do aplicativo novo>
BLING_CLIENT_SECRET=<do aplicativo novo>
BLING_REDIRECT_URI=https://api.canastrainteligencia.com/api/bling/oauth/callback
BLING_STORE_ID=<id da loja, opcional>
BLING_ORDER_SITUACAO_ID=<situação em que o pedido nasce, opcional>
BLING_LEAD_DEFAULT_STAGE=<stage dos leads criados pelo webhook>
```

`BLING_ENABLED` é `false` por default — a integração está inerte em produção até você ligar. Isso é proposital: dá para deployar o código antes de ter as credenciais.

Para descobrir `BLING_STORE_ID` e `BLING_ORDER_SITUACAO_ID`, use `GET /api/bling/status` depois de conectar, ou consulte direto a API (`GET /situacoes/modulos`).

### 3. Aplicar a migration

Depois da query de duplicados do passo anterior. Use o caminho que o projeto já usa para migrations no Supabase.

### 4. Conectar o OAuth

Acesse `/config` no CRM (aba Bling, admin-only) → "Conectar ao Bling". O fluxo:

1. O backend gera um `state` aleatório e guarda no Redis com TTL de 10 min.
2. Você autoriza no Bling.
3. O Bling redireciona para `/api/bling/oauth/callback`, o backend valida o `state` e troca o code.

> O `authorization_code` do Bling expira em **1 minuto**. Se você demorar entre autorizar e o callback chegar, a troca falha — é só refazer, não é bug.

Confirme com `GET /api/bling/status`: deve vir `connected: true` e uma data de expiração.

### 5. Sync completo

`POST /api/bling/sync?full=true` (ou o botão "Sincronizar agora" em `/config`).

Isso popula os quatro espelhos. Confira as contagens que voltam contra o que você vê no painel do Bling. Se a contagem de contatos vier muito menor que o esperado, o filtro `criterio` está errado — o default da API é "últimos incluídos", não "todos".

### 6. Configurar os webhooks

No aplicativo → aba Webhooks:

- **Recurso `order`**, ações created/updated/deleted, versão `v1`
- **Recurso `product`**, mesmas ações

URL: `https://api.canastrainteligencia.com/webhook/bling`

> O Bling exige resposta **2xx em até 5 segundos**. Passou disso, ele retenta por 3 dias e depois **desabilita a configuração sozinho** — e a integração para em silêncio até alguém reabilitar na mão. Nosso receiver foi feito para isso: ele valida a assinatura, grava o evento e devolve 200; o processamento pesado roda no worker. Se você mexer nele, não coloque I/O com o Bling dentro do request.

Teste: crie um pedido qualquer no Bling e veja se ele aparece em `/painel-vendas`.

### 7. Mapear vendedores

Em `/config` → Bling → mapeamento. Liga cada usuário do CRM (por e-mail) ao vendedor correspondente no Bling. Sem vínculo, o pedido sobe sem vendedor — não bloqueia a venda, mas a comissão fica órfã.

### 8. Confirmar o deep-link do pedido

O formato da URL de um pedido no painel do Bling **não está no OpenAPI deles**. Abra um pedido real, copie o padrão da URL, e ajuste a constante:

```
frontend/src/lib/sale-display.ts → BLING_ORDER_URL_TEMPLATE
```

É o único lugar do código que precisa mudar. **O `agente-bling` provavelmente já tem esse formato** — vale checar lá antes de ir ao painel.

### 9. Teste E2E com venda real

Registre uma venda de **valor baixo** por um cliente de teste, pelo modal do CRM. Verifique, em ordem:

1. O pedido apareceu no Bling com os itens e as parcelas certas.
2. A venda apareceu em `/painel-vendas` com o número do pedido.
3. O deal foi para "Fechado Ganho" no funil **correto**.
4. Alterando a situação do pedido no Bling, o CRM reflete (via webhook).
5. Cancelando o pedido no Bling, a venda vira "Cancelada" no CRM e **não some**.

Depois teste o caminho de erro: registre uma venda para um lead **sem** CPF/CNPJ. Deve devolver 409 com os candidatos, ou pedir o documento — nunca criar contato duplicado.

### 10. Backfill, por último

`POST /api/bling/backfill` importa 12 meses de pedidos. Só rode **depois** de tudo acima funcionar.

É longo (~2 chamadas por pedido, a 3 req/s dá ~1,5 pedido/segundo) e **síncrono** — a requisição HTTP pode estourar timeout de gateway antes de terminar. Isso é esperado: o job continua rodando no servidor. Ele é retomável, então se cair, rodar de novo continua da última janela concluída, não do zero. Acompanhe pelos logs e por `bling_sync_state`.

---

## Armadilhas da API do Bling

Cada uma destas custou caro para descobrir. O código já lida com todas — mas se você for mexer, precisa saber por que a peça existe.

**O limite é por CONTA, não por endpoint nem por processo.** 3 requisições por segundo, 120.000 por dia. O modal de venda, o job de sync e o processamento de webhook dividem o mesmo orçamento. Por isso existe um token-bucket central em Redis (`ratelimit.py`) e **todas** as chamadas passam pelo `BlingClient`. Se você adicionar código que chama o Bling por fora, vai roubar vaga dos outros e derrubar a integração.

**Bloqueio de IP.** 300 erros em 10 segundos, ou 600 requisições em 10 segundos → 10 minutos bloqueado. E **20 chamadas ao `/oauth/token` em 60 segundos → 60 minutos bloqueado**. É por isso que a renovação de token é serializada por lock distribuído: sem isso, vários workers renovando ao mesmo tempo derrubam tudo por uma hora.

**Token opaco está descontinuado.** O header `enable-jwt: 1` é obrigatório no `/oauth/token` **e em todas as chamadas seguintes**. Sem ele você recebe o formato antigo, que vai parar de funcionar numa data que o Bling ainda não anunciou.

**O `refresh_token` dura 30 dias e os tokens moram no Postgres, não no Redis.** Este projeto já teve um `FLUSHALL` no Redis (07/06/2026). Perder o `refresh_token` obriga a refazer o fluxo OAuth manualmente no navegador. Redis aqui é cache; a verdade está em `bling_credentials`.

**Não existe webhook de contato.** Os recursos disponíveis são `order`, `product`, `stock`, `virtual_stock`, `product_supplier`, `invoice`, `consumer_invoice`. Contatos exigem polling — é o que o sync diário faz.

**A entrega de webhook não é ordenada e pode repetir.** Um `order.updated` antigo pode chegar depois de um mais novo. O processador compara `event_date` com o que já foi aplicado e descarta o atrasado; a idempotência vem do `event_id` ser chave primária.

**O payload do webhook de pedido não traz os itens.** Por isso o processador faz `GET /pedidos/vendas/{id}`. E é exatamente esse I/O que não pode estar dentro do request de 5 segundos.

**Filtro de período maior que 1 ano devolve 400.** Por isso o backfill trabalha em janelas de 30 dias.

**O telefone do Bling vem em formato local, sem código do país.** `(51) 99269-6163` de um lado, `5551992696163` do outro. A função `normalize_phone` do CRM **não** prefixa o `55`. Ver `_to_e164_br` em `sync.py`, e a limitação documentada lá: o casamento por telefone só é confiável para celular; fixo fica no espelho como informativo.

**CPF/CNPJ é a chave, telefone não é.** O telefone do lead costuma ser o do comprador (uma pessoa); o contato do Bling é a empresa. Só o documento vincula automaticamente, e só quando o match é único. Telefone e e-mail apenas *sugerem*, e exigem confirmação humana. Se você afrouxar isso, a integração vai duplicar cadastro no ERP.

**PostgREST corta resposta em 1000 linhas por default.** Uma consulta sem filtro sobre `bling_products` truncava silenciosamente e a descrição do produto ia para o ERP como o literal `"Item"`. Sempre filtre por id.

---

## Limitação conhecida

`sales.status` aceita `pendente_bling`, e a tabela de `/painel-vendas` sabe exibi-lo, **mas o backend nunca escreve esse valor**. Quando o Bling está indisponível, o router enfileira e devolve `202` sem criar linha em `sales` — a venda nasce quando o job conclui, já com o `bling_order_id`. O `202` avisa o vendedor na hora. Está documentado na spec; não é bug, é caminho morto.

---

## Ao terminar: commite no GitHub

O fluxo deste repositório **não usa Pull Requests**. É:

```bash
git add <arquivos específicos>          # nunca -A nem .
git commit -m "..."
git pull origin master
git push origin <sua-branch>:master
```

**O push para `master` dispara deploy de produção via GitHub Actions.** Confirme com o Rafael antes de dar o push final.

Commite também:
- qualquer ajuste que você tiver feito em `BLING_ORDER_URL_TEMPLATE`;
- correções que surgirem do contato com a API real;
- **um registro do que você observou** — atualize este documento ou crie um `docs/setup/bling-observacoes-producao.md` com o que a API fez de diferente do esperado. A próxima pessoa vai precisar.

**Não commite** `.env`, tokens, `client_secret`, nem nada que tenha vindo do `agente-bling`.

---

## Se travar

Ordem de diagnóstico:

1. `GET /api/bling/status` — está conectado? O token expirou?
2. Logs do backend com prefixo `[BLING`.
3. Tabela `bling_webhook_events` — tem evento em `pending` acumulando? Em `failed`?
4. Tabela `bling_jobs` — tem job em `failed`? O `last_error` diz o quê?
5. Se for erro 4xx do Bling, a mensagem original vem no corpo (`type`, `message`, `description`) e é repassada até a UI. Leia ela antes de supor.

E se algo no código não fizer sentido, o **porquê** está na spec — cada decisão tem a consequência que a motivou escrita ao lado.
