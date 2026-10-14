# Endereço colocado no CRM vai para o Bling — design

Cartão: "End. colocados no CRM não vão para o Bling" (b3788533). Origem: reclamação de vendedor.

## Problema

O vendedor coloca o endereço do cliente no CRM e ele não aparece no cadastro do contato no Bling.
A investigação do código (2026-10-14) mostrou três furos:

1. O campo "Endereco" da ficha do lead (`leads.endereco`, texto livre) nunca é enviado ao Bling.
2. O formulário de cadastro de contato do modal de venda/orçamento (`bling-contact-resolver.tsx`)
   só recebe nome e telefone do lead como padrão; o endereço vem vazio.
3. Em `contacts.create_contact`, se o documento já existe no Bling, o CRM só vincula o lead e
   **descarta** o endereço digitado. Não existe nenhuma atualização (`PUT /contatos`) de contato.

Além disso, o endereço do lead é uma linha livre (1.203 de 5.657 leads preenchidos, a maioria só com
o nome da rua), enquanto o Bling exige campos separados.

## Decisões (com o Rafael)

- Escopo B: editar o endereço na ficha do lead atualiza o contato vinculado no Bling; o modal de
  venda/orçamento vem com o endereço do lead e também atualiza o contato que já existia.
- Endereço estruturado na ficha: CEP, rua, número, complemento, bairro, cidade, UF; CEP preenche o
  resto automaticamente.
- CRM ganha: ao salvar, o endereço do CRM sobrescreve o endereço do contato no Bling. Só o bloco de
  endereço muda; nome, documento, telefone etc. ficam como estão no Bling.
- Lead vinculado nas duas contas (default e secundaria): atualiza as duas.
- Só envia endereço **completo**: CEP (8 dígitos), rua, número, cidade e UF. Incompleto fica só no
  CRM e a tela avisa.

## O que muda

### Banco (Supabase, migração aditiva)
`supabase/migrations/20261014_leads_endereco_estruturado.sql`:
`ALTER TABLE leads ADD COLUMN IF NOT EXISTS` `cep`, `logradouro`, `numero`, `complemento`, `bairro`,
`municipio`, `uf` (todos `text`, nulos). `leads.endereco` continua existindo (legado) e passa a ser
regravado com a forma formatada ("Rua X, 123 - Bairro - Cidade/UF CEP") sempre que os campos novos
são salvos, para as telas que já leem `endereco` continuarem funcionando.

### Frontend (Next.js, `frontend/`)
- `lib/lead-address.ts` (novo, puro e testado): normalizar CEP/UF, `isAddressComplete`,
  `formatAddress` (para `leads.endereco`), `toBlingAddress` (para `{geral:{...}}`), e mapear a
  resposta do ViaCEP.
- `components/leads/lead-detail-modal.tsx`: o campo único "Endereco" vira o bloco de campos
  estruturados. Ao completar 8 dígitos de CEP, consulta `https://viacep.com.br/ws/<cep>/json/` no
  navegador e preenche rua, bairro, cidade, UF (sem sobrescrever o que o vendedor já digitou à mão
  depois; CEP inexistente/erro de rede = só não preenche). Se os campos novos estão vazios e
  `endereco` legado tem texto, mostra o texto antigo como referência abaixo do bloco.
  Depois de salvar: mostra "Endereço atualizado no Bling", "Endereço incompleto — não enviado ao
  Bling" ou "Falha ao atualizar no Bling: <motivo>" (o salvamento no CRM nunca é desfeito por falha
  no Bling).
- `app/api/leads/[id]/route.ts` (PATCH): aceita os campos novos, regrava `endereco` formatado; se
  algum campo de endereço mudou e o endereço está completo, chama o backend
  `POST /api/bling/contacts/address` com `{lead_id}` e devolve o resultado por conta na resposta.
- `sales/sale-create-modal.tsx` e `quotes/quote-create-modal.tsx`: os `defaults` do
  `BlingContactResolver` passam a incluir cep/logradouro/numero/bairro/municipio/uf (e documento/e-mail
  quando o lead tiver) vindos do lead.
- `lib/bling-contact-form.ts`: inclui `complemento` no formulário e no payload.
- Tipos `Lead` em `lib/types.ts` ganham os campos novos.

### Backend (FastAPI, `backend/`)
- `app/bling/contacts.py`: nova `update_contact_address(client, contact_id, geral, account)`:
  `GET /contatos/{id}` → troca só `endereco.geral` → `PUT /contatos/{id}` com o objeto completo
  (o PUT do Bling v3 substitui o cadastro inteiro, por isso o GET antes) → atualiza o espelho
  `bling_contacts.endereco`.
- `sync_lead_address(lead_id)`: lê os campos do lead; se incompleto devolve `incomplete`; senão,
  para cada vínculo em `lead_bling_contacts` (todas as contas) chama `update_contact_address` com o
  `BlingClient` da conta; resultado por conta (`updated` / `error` + mensagem). Sem vínculo =
  `not_linked`.
- `create_contact`: no ramo "contato já existia", se `dados.endereco` veio completo, chama
  `update_contact_address` (corrige o furo 3). Contato novo continua igual.
- `app/bling/router.py`: `POST /api/bling/contacts/address` (`{lead_id}`) → `sync_lead_address`.
  Erros do Bling viram 502 com mensagem; nunca 500 opaco.
- Ao criar contato pelo modal com endereço, o lead também recebe os campos estruturados se estiverem
  vazios (o CRM aprende o endereço digitado na venda).

## Como testar em modo teste
No worktree `ValerIA-agente-b3788533`, branch `agente/b3788533`, sem gravar nada no Bling nem no banco
de produção:
- Backend: `pytest` com `BlingClient` dublê — `update_contact_address` faz GET+PUT preservando o resto
  do cadastro e trocando só o endereço; `sync_lead_address` cobre incompleto, sem vínculo, duas
  contas, falha numa conta não impede a outra; `create_contact` no ramo "já existia" atualiza o
  endereço; o endpoint devolve 502 em erro do Bling. Suíte inteira do backend verde.
- Frontend: `vitest` para `lead-address.ts`, payload com complemento, PATCH chamando o backend só
  quando o endereço mudou e está completo, defaults do modal. `npm run type-check`, `npm run test`,
  `npm run build` verdes.
- Print: frontend rodando local no worktree, ficha de um lead com o bloco de endereço novo
  (preenchimento por CEP visível) e o modal de venda com o endereço preenchido — sem clicar em salvar.

## Como publicar
1. Migração aditiva no Supabase de produção: `psql` no container `supabase_db` com o arquivo novo
   (só `ADD COLUMN IF NOT EXISTS`; não apaga nada).
2. `git pull origin master` no branch, merge de `agente/b3788533` em `master`, `git push origin master`.
   O GitHub Actions (`deploy.yml`) roda testes e atualiza `crm_crm` (frontend) e
   `canastra_api`/`canastra_worker` (backend).
3. Conferir o run do Actions, `docker service ls` e `docker service logs canastra_api` / `crm_crm`.
- Voltar atrás: `git revert` do merge + push (redeploy automático). As colunas novas ficam (nulas e
  inofensivas); nenhum dado é apagado.

## Como testar em produção
Ação real com efeito externo, autorizada pelo Rafael: alterar o endereço do contato de teste
**16569186007 (conta secundaria), vinculado ao lead "Teste Teste"**. Nenhum pedido, NF, mensagem a
cliente ou cobrança.
1. Ler e guardar o endereço atual do contato no Bling (`GET /contatos/16569186007`).
2. Na ficha do "Teste Teste", preencher endereço completo por CEP e salvar; ver a mensagem
   "Endereço atualizado no Bling".
3. `GET` de novo: endereço novo no Bling, nome/documento/telefone inalterados; espelho
   `bling_contacts` atualizado; logs sem erro.
4. Print da ficha.
5. Restaurar o endereço original (pela ficha ou GET+PUT com o valor guardado) e conferir com GET.

## Fora do escopo
- Trazer endereço do Bling para o CRM (Bling → CRM) e converter os 1.203 endereços em texto livre
  para os campos novos.
- Endereço de entrega no pedido de venda (`transporte`/etiqueta).
- BeeInside (dashboard) e Agente Bling.
- Editar outros dados do contato no Bling (nome, telefone, e-mail).
