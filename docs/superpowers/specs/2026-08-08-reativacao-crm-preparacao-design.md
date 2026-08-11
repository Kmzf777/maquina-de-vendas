# Preparação da campanha de reativação no CRM — design

**Data:** 2026-08-08
**Branch:** `feat/reativacao-crm-preparacao`
**Origem dos requisitos:** sessão de grilling em 2026-08-08 (8 decisões registradas na seção "Decisões")

---

## Problema

A base de clientes da Canastra tem 1.020 contatos parados há mais de 36 meses e
R$ 1,8 milhão de receita histórica inativa. Uma campanha de reativação por WhatsApp
depende de três coisas que hoje não existem:

1. **Os leads não existem no CRM.** Dos 276 alvos selecionados a partir do Bling,
   apenas 40 têm registro em `leads`. O disparo (`broadcast_leads`) referencia
   `lead_id`, então 236 contatos são inalcançáveis pelo fluxo atual.
2. **O vendedor não tem contexto.** Quem responder ao disparo cai na caixa do João
   sem que ele saiba quem é, quanto a pessoa já comprou, o que comprava ou há quanto
   tempo parou.
3. **Há 51 pedidos de opt-out não registrados.** Cinquenta e um contatos disseram
   "não tenho interesse" / "parar mensagens" em disparos anteriores e continuam com
   `leads.opt_out = false`, elegíveis para receber mensagem de novo.

Um disparo anterior (`rabubens`, UTILITY, 606 leads) usou o texto *"oi seu pedido ja
está sendo preparado"* para gente que nunca fez pedido, e clientes responderam
"eu nao fiz pedido" / "eu acho foi erro 🤣". O custo de errar aqui é a saúde do número
(hoje GREEN), não apenas a conversão da campanha.

## Escopo

Preparar os dados no CRM para que a campanha possa ser disparada **manualmente pela
interface**, com contexto suficiente para o vendedor conduzir a conversa.

### Fora de escopo

- **Executar o disparo.** Nenhum registro em `broadcasts` ou `broadcast_leads` é criado.
- Criar ou submeter template na Meta.
- Alterar canais, personas ou qualquer código do backend/frontend.
- Configurar backup recorrente do banco (problema real, aberto desde jul/2026, mas
  fora deste escopo por decisão do usuário).

## Universo de dados

Fonte: `DB Leads/DISPARO-segunda-2026-08-10.csv` (276 linhas), derivado de
`CANASTRA-LEADS-MASTER-2026-08-08.csv`, que por sua vez vem da extração completa do
Bling em 2026-08-08 (5.856 pedidos, 2.771 contatos) enriquecida com CNAE/porte da
Receita via BrasilAPI.

| Grupo | Qtd | Tratamento |
|---|---|---|
| Já existem em `leads` (match exato de telefone) | 40 | update conservador |
| A criar | 236 | insert completo |
| **Total com lead + nota de briefing** | **276** | |
| Removidos da lista de disparo (mantêm lead + nota) | 4 | ver "Exclusões" |
| **Lista final de disparo** | **272** | |
| Opt-outs a marcar (`opt_out = true`) | 51 | update |
| Duplicata lógica a resolver | 1 | normalizar telefone |

## Restrições do ambiente

Fatos verificados no banco de produção (Supabase self-hosted na VPS
`173.249.15.11`, container `supabase_db`) em 2026-08-08:

- `leads.phone` é **NOT NULL** e tem índice **UNIQUE** (`leads_phone_key`).
- Defaults: `stage='pending'`, `status='imported'`, `channel='evolution'`,
  `metadata='{}'`, `human_control=false`.
- Formatos de telefone conviventes: 1.715 registros com 13 dígitos (E.164 sem `+`),
  212 com 10, 191 com 11, 23 com 12. A unicidade é da string exata, então
  `11981154002` e `5511981154002` coexistem como registros distintos.
- Trigger `trg_update_entered_stage_at` dispara **apenas em UPDATE**.
- FKs de `messages`, `lead_notes`, `lead_tags`, `deals`, `lead_events` e outras
  usam `ON DELETE CASCADE` — rollback por delete é limpo.
- `archive_mode = off`, nenhum dump, nenhum cron de backup. Banco: 106 MB.
- Canal `NUMERO JOÃO` (`553491461669`, `phone_number_id=1049315514934778`) tem
  `mode='human'`; `_broadcast_ai_enabled()` em `backend/app/broadcast/worker.py:379`
  força `ai_enabled=false` para canal `human`, então a IA não intercepta respostas.
- `leads.opt_out` é a blacklist canônica (`is_lead_blacklisted()` em
  `backend/app/leads/service.py:380`), com guardrail duplo: filtro na criação da
  campanha e recheque no milissegundo do envio.
- `follow_up_jobs` e o watchdog operam sobre **conversas**, não sobre criação de
  lead — criar lead sem conversa não agenda follow-up.
- `leads.rolling_summary` **não é renderizado em nenhuma tela** (zero referências em
  `frontend/src`); serve apenas à IA.
- A aba "Notas" (`frontend/src/components/conversas/tabs/crm-notas-tab.tsx`) lê de
  `/api/leads/{id}/notes` → tabela `lead_notes`, e renderiza numa timeline junto com
  `lead_events`.
- `assigned_to` é UUID de `auth.users`. João = `1c3c78ed-ef47-4dca-9a63-2052f28e8fd6`
  (`joao@cafecanastra.com`).
- Convenções existentes em `metadata`: chave `origem` (344 usos, valores
  `terceirizacao` e `atacado`). Tags existentes incluem `Já é Cliente` (18 usos).

## Decisões

Cada decisão abaixo foi tomada pelo usuário durante o grilling. São requisitos, não
sugestões.

**D1 — Escopo da gravação.** Gravar somente dados (leads, notas, opt-out). Nenhum
registro em `broadcasts`/`broadcast_leads`, para eliminar a possibilidade de envio
acidental. O disparo é criado depois pela interface do CRM.

**D2 — Onde os leads aparecem.** `stage='pending'`, `status='imported'` (o default,
semanticamente honesto: não foram qualificados nesta rodada). Rastreio por
`metadata.origem='reativacao_bling'` + `metadata.lote='reativacao_bling_2026-08-10'`
e pela tag `Já é Cliente` nos que já compraram. Não criar stage novo (o frontend só
renderiza os de `AGENT_STAGES` em `frontend/src/lib/constants.ts`) e não usar
`stage='atacado'` (poluiria a coluna de qualificação com leads que nunca conversaram).

**D3 — Formato do briefing.** Nota única estruturada em `lead_notes`, com histórico
de compra, produto, perfil, dados cadastrais e vendedor anterior. Não usar
`rolling_summary` (invisível na UI) nem duas notas separadas.

**D4 — Atribuição.** `assigned_to = 1c3c78ed-…` (João) em todos, e o disparo sairá
pelo número dele. O usuário optou por centralizar, ciente de que o Arthur atendia
103 desses leads (R$ 149.733) e tem número próprio na WABA. Mitigação: o briefing
registra "Vendedor anterior: <nome>".

**D5 — Leads já existentes (40): conservador.** Adicionar nota e preencher **apenas
campos vazios** (`cnpj`, `razao_social`, `nome_fantasia`, `endereco`, `email`).
`metadata` recebe **merge**, nunca substituição. **Não alterar** `stage`, `status`,
`human_control`, `ai_enabled`, nem `assigned_to` já preenchido — 12 desses leads
estão em `human_control=true` e a maioria já foi qualificada como
`secretaria/active`.

**D6 — Saudação.** A variável `{{1}}` do template usa `leads.name` quando existir
(30 casos onde o CRM tem o nome da pessoa: "Carina", "Paulo", "Eduardo"), e o nome
do Bling limpo de sufixos como fallback. Motivo: o Bling guarda razão social
("Divina Terra - BALNEÁRIO CAMBORIÚ") e o CRM guarda como a pessoa se identificou.

**D7 — Exclusões da lista de disparo.** Quatro contatos recebem lead e nota, mas
ficam fora da campanha:

| Contato | Telefone | Motivo |
|---|---|---|
| Incec Brasil Social | `5511996057340` | cliente avisou: "nossa operação com café foi encerrada" (LTV R$ 14.271) |
| Emporio Sabor Do Norte | `5511989374541` | o número é atendimento automático da loja |
| Gran Cremma | `5516997442292` | lead quente: pediu portfólio completo e cápsulas/drip; exige resposta do vendedor, não template de cadastro |
| Divina Terra - Balneário Camboriú | `5554996324731` | declinou com gatilho: "quando eu diminuir esse estoque, eu volto" |

**D8 — Proteção.** `pg_dump` completo antes de qualquer escrita, tudo em transação
única com rollback automático em erro, operações idempotentes, e um
`rollback.sql` entregue ao fim.

**D9 — Duplicata lógica (declarada, não perguntada).** `Atma it solutions`
(`5511981154002`) existe no CRM como `11981154002`. Em vez de criar duplicata,
normalizar o `phone` do registro existente para o formato E.164 e tratá-lo como um
dos 40. Seguro porque `messages` referencia `lead_id`, não o telefone.

## Regras de conteúdo do briefing

Uma nota por lead, com `author = 'Sistema — Reativação Bling'`. Estrutura:

```
REATIVAÇÃO 10/08/2026 — lote reativacao_bling_2026-08-10

CLIENTE INATIVO há 2.573 dias (última compra: 23/07/2019)
Histórico: 1 pedido · R$ 13.918,48 · ticket médio R$ 13.918,48
Comprava: Café Cru Beneficiado (1.200 un)
PERFIL: café verde/industrial — não abordar como reposição de varejo

Cadastro: CNPJ 27.114.890/0001-19 · Gravataí/RS
NF-e emitidas: 1 · Orçamentos: 0 · Sem débito em aberto
Vendedor anterior: Arthur Silva Boaventura
ICP 55 (C-médio) · id_bling 5845664414
```

Variações obrigatórias:

- **Nunca comprou** (62 casos): trocar o bloco de histórico por
  `LEAD SEM COMPRA — cadastrado no Bling, nunca faturou`.
- **Perfil atípico** (46 casos): incluir a linha `PERFIL:` com o rótulo derivado do
  produto — `cápsula` (22), `granel/volume` (14), `drip` (7),
  `café verde/industrial` (2), `kit/presente` (1). Nos demais, omitir a linha.
- **Excluídos da campanha** (4 casos de D7): incluir como primeira linha
  `⚠ FORA DA CAMPANHA: <motivo>`.
- **Débito em aberto:** quando `valor_vencido > 0`, trocar "Sem débito em aberto"
  por `DÉBITO VENCIDO: R$ X (N títulos, máx N dias de atraso) — tratar como cobrança`.
  (Na lista atual são 0, porque inadimplentes já foram filtrados; a regra existe
  para reuso do script.)

## Critérios de aceitação

1. `pg_dump` gerado, com tamanho reportado, antes de qualquer escrita.
2. Após execução: `select count(*) from leads where metadata->>'lote' = 'reativacao_bling_2026-08-10'` retorna 276.
3. `select count(*) from lead_notes where content like 'REATIVAÇÃO 10/08/2026%'` retorna 276.
4. `select count(*) from leads where opt_out` aumenta em exatamente 51.
5. Nenhum lead dos 40 pré-existentes tem `stage`, `status`, `human_control` ou
   `ai_enabled` alterado (verificação por comparação com snapshot pré-execução).
6. Zero registros em `broadcasts` ou `broadcast_leads` criados.
7. Rodar o script duas vezes não cria leads nem notas duplicadas.
8. `rollback.sql` existe e, se executado, devolve o banco ao estado do snapshot
   (validado em dry-run contra contagens).
9. Nenhum dos 51 opt-outs aparece na lista final de disparo de 272.
