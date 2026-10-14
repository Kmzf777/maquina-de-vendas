# Leads duplicados no CRM por formato de telefone: design

**Data:** 2026-10-13
**Cartão:** "Investigar Leads Duplicados no crm" (b747da43), quadro BEEINSIDE CANASTRA CRM
**Repo:** ValerIA (`frontend/` = CRM crm.canastrainteligencia.com, `backend/` = canastra_api)
**Branch:** `agente/b747da43`

## Problema

O Rafael confirmou ("sim") que o problema é o mesmo cliente aparecer 2 ou 3 vezes no CRM porque o telefone foi gravado em formatos diferentes.

O banco de produção foi medido em 13/10, só com SELECT. São 5.639 leads e `leads.phone` é único. Mas quando os números são normalizados (55 + DDD + 9 do celular), aparecem **389 pessoas em 782 leads**: 385 pares e 4 trios. Exemplos:

| Mesma pessoa | Formatos gravados |
|---|---|
| Douglas Schutz | `4999170363` (evolution, 08/05) · `5549999170363` (manual, 15/06) · `554999170363` (manual, 04/09) |
| Francine | `5551981162558` (evolution, 08/05) · `555181162558` (manual, 07/08) |

Origem:
- Em maio entraram ~400 leads do canal `evolution` gravados **sem o 55** (10 ou 11 dígitos).
- Em 15/06 um import "manual" recriou as mesmas pessoas com 55.
- De julho em diante entraram mais alguns por caminhos que não normalizam:
  - `quick-add-lead.tsx` grava só os dígitos, direto no Supabase.
  - `POST /api/leads` e `PATCH /api/leads/[id]` fazem `sanitizePhone`/`replace(\D)` sem pôr 55 nem o 9.
  - `POST /campaigns/{id}/import` no backend grava o que vem do CSV.

Os dois lados têm histórico. Só os leads antigos sem 55 já somam 1.694 mensagens, 409 deals e 304 conversas.

A migração de 15/06 (`20260615_merge_duplicate_9digit_leads.sql`) só tratou o caso 12↔13 dígitos com 55. O caso "sem 55" e as entradas novas ficaram de fora.

## Decisões do Rafael

1. **Mesclagem automática com prévia** (opção A). Antes de aplicar, o Rafael recebe a planilha dos pares. Os grupos com primeiro nome diferente (63) e os trios (4) vão separados para aprovação um a um. Há backup para desfazer.
2. **O lead mais antigo é o que fica** (opção A). Ele preserva a origem do primeiro contato, usada no /trafego e na atribuição. O telefone dele vira o formato canônico. Campos vazios dele são preenchidos com os do duplicado.
3. A prevenção entra junto: todo caminho de entrada normaliza o telefone.

## O que muda

### 1. Script de mesclagem: `scripts/leads/mesclar_duplicados_telefone.py`

Segue o padrão já usado e testado em `scripts/bling/mesclar_leads_duplicados.py`: só stdlib, roda no host da VPS via `psql`, e o modo padrão é dry-run.

- **Chave do grupo:** o telefone canônico, com a regra do `normalizePhoneBR`. Tira os não dígitos e um 0 à esquerda. 10 ou 11 dígitos ganham o 55. Com 12 dígitos começando em 55, o 9 é injetado **só se o 5º dígito for 6, 7, 8 ou 9** (celular). Ficam fora: `bling-*`, BSUID, telefone vazio e números que não chegam a 12 ou 13 dígitos com 55.
- **Sobrevivente:** o lead de menor `created_at`.
- **Mesclagem, uma transação por grupo:**
  - `SELECT ... FOR UPDATE` nos leads do grupo.
  - Move `lead_id` em todas as tabelas com FK para `leads`. A lista é conferida contra o `information_schema` no início; se aparecer tabela não coberta, o script ABORTA. A foto `follow_up_jobs_incidente_20261003` é ignorada, como no script do Bling.
  - Tabelas com UNIQUE envolvendo `lead_id`:
    - `conversations (lead_id, channel_id)`: se os dois têm conversa no mesmo canal, as mensagens do duplicado vão para a conversa do sobrevivente (`messages.lead_id` + `conversation_id`), a conversa vazia é apagada e o par é registrado.
    - `broadcast_leads (broadcast_id, lead_id)`: em colisão, fica a linha do sobrevivente e a do duplicado é registrada no backup antes de sair.
    - `campaign_enrollments` ativos e `follow_up_jobs` João abertos: em colisão, o do duplicado é **cancelado** (status `cancelled`), não apagado, e o par é registrado.
  - `deals`: todos vão para o sobrevivente, nenhum é apagado. Se ficarem 2 deals abertos no mesmo funil, o grupo entra em `deals_repetidos.csv` para o vendedor fechar o repetido.
  - `leads`:
    - Copia `name`, `email`, `cnpj`, `razao_social`, `nome_fantasia`, cidade/UF, `bsuid`, `bling_contact_id` e as colunas de tracking só onde o sobrevivente está vazio.
    - `phone` do sobrevivente = canônico. O duplicado é apagado antes de gravar o canônico, por causa do `leads_phone_key`.
  - Grava `lead_events` tipo `mesclagem` no sobrevivente, com o id e o telefone do duplicado.
- **Saídas** (em `--saida <dir>`):
  - `pares.csv`: grupos automáticos, 2 leads com o mesmo primeiro nome ou com um nome vazio.
  - `revisar.csv`: primeiro nome diferente e trios.
  - `deals_repetidos.csv`, `backup.json` (as linhas inteiras de `leads` e de cada tabela tocada, para desfazer) e `aplicados.csv`.
  - Contagens em JSON.
- **Flags:**
  - `--aplicar --pares <csv revisado>` aplica SÓ as linhas do CSV, recalculando cada grupo.
  - `--excluir <ids>` tira leads da mesclagem.
  - `--limite N` aplica no máximo N grupos.

### 2. Prevenção: um só normalizador nos pontos de entrada

- **Frontend:** `frontend/src/lib/phone.ts` (`normalizePhoneBR`) passa a valer em:
  - `components/quick-add-lead.tsx`, via uma rota de API que normaliza. Hoje o insert é direto no Supabase.
  - `app/api/leads/route.ts` (POST) e `app/api/leads/[id]/route.ts` (PATCH do phone).
  - Telefone que não normaliza retorna 422 com mensagem clara. O import CSV já usa o normalizador.
- **Antes de criar, procurar o lead existente** pelas variantes do número (canônico, sem o 9, sem o 55). Se achar, o POST/quick-add devolve o lead existente em vez de criar outro.
- **Backend:** `campaign/router.py` (import de CSV da campanha) passa a usar `normalize_phone` e a mesma busca por variantes antes do insert. O `get_or_create_lead` do inbound já procura as variantes antigas e não muda.
- O 9 é injetado em 12 dígitos só quando o 5º dígito é 6, 7, 8 ou 9, como no script e no `celular_br` do Bling. O `normalizePhoneBR` do front recebe essa mesma regra. O `normalize_phone` do backend **não muda** nesta entrega (ver "Fora do escopo").

## Como testar em modo teste

Tudo antes de publicar, no worktree `ValerIA-agente-b747da43`:

- **Unidade (TDD):**
  - Python: chave canônica, escolha do sobrevivente, classificação pares/revisar.
  - Jest: `normalizePhoneBR` com fixo/celular e busca por variantes no POST/quick-add.
  - Rodam `pytest` e `npm run test` + `type-check` completos.
- **Mesclagem num Postgres 17 de rascunho na VPS**, como no `test_cs_p1_mesclagem_pg.py`:
  - Container descartável, nunca o `supabase_db`, carregado com `/root/crm-wt/_scratchdb/public_schema.sql`.
  - Seed com os casos reais anonimizados: trio sem 55/12/13, par com conversa no mesmo canal, deals no mesmo funil, colisão de broadcast e de follow-up.
  - Confere contagens antes e depois, que nenhuma mensagem, deal ou venda sumiu, e que o backup restaura.
- **Dry-run contra produção** (só leitura): gera `pares.csv`/`revisar.csv` reais. Os CSVs vão para o Rafael pelo Discord.
- **Print:** tela de criar lead do CRM rodando local (`npm run dev` no worktree, apontando para o Supabase de produção só em leitura). O teste digita um número já existente sem o 55 e mostra que abre o lead existente em vez de criar outro. Se o local não conseguir só ler, o print fica para o teste em produção, com um número de teste.

## Como publicar

1. No branch: `git pull origin master` (merge da master no branch) e `git push origin agente/b747da43:master`, como manda o CLAUDE.md do repo. O GitHub Actions faz o deploy de `crm_crm` (frontend) e `canastra_api`/`canastra_worker` (backend).
2. Conferir `docker service ls` e `docker service logs crm_crm` e `canastra_api`: imagem nova rodando, sem erro.
3. **Mesclagem em produção**, depois de o Rafael devolver os CSVs aprovados:
   - `pg_dump` das tabelas tocadas para `/root/backups/` antes.
   - `--aplicar --pares pares-revisado.csv` primeiro com `--limite 5`. Conferir esses 5 no CRM, depois rodar o resto.
   - O `revisar.csv` só é aplicado nas linhas que o Rafael aprovar.
4. **Voltar atrás:**
   - Código: `git revert` do merge + push, que redeploya.
   - Dados: restaurar a partir do `backup.json` (reinsere os leads apagados e devolve o `lead_id` das linhas movidas) ou do `pg_dump`.

## Como testar em produção

- Conferir os 5 primeiros grupos mesclados no CRM: um lead só, telefone canônico, mensagens/deals/notas de ambos visíveis, evento "mesclagem" na linha do tempo.
- Rodar o dry-run de novo depois de aplicar: deve sobrar só o que ficou em `revisar` sem aprovação.
- Criar um lead pelo quick-add com um **número de teste** em formato sem 55 que já exista (lead de teste criado para isso). Deve abrir o existente. O lead de teste é apagado no fim.
- **Ação com efeito externo:** nenhuma. A mesclagem não manda mensagem a cliente, não mexe no Bling, não cancela venda e não dispara conversão para a Meta. Ela só reaponta linhas internas e cancela follow-ups/inscrições **duplicados** do mesmo cliente (o do sobrevivente continua).

## Fora do escopo

- Corrigir o `normalize_phone` do backend, que hoje injeta 9 em telefone fixo: há 303 leads `55DD9[2-5]…` e só 3 pares de fato duplicados. Mexer nisso muda a identidade do inbound de WhatsApp e merece cartão próprio. Esses 3 pares vão para o `revisar.csv`.
- Os 149 leads `bling-*` (já cobertos pelo script do Bling de 06/10).
- Botão "Mesclar" manual no CRM.
- Duplicados por nome/CNPJ com telefones diferentes.
- Grupos com DDD diferente e mesmos 8 finais (ex.: `5519984143627` × `5511984143627`): são pessoas diferentes e não são mescladas.
