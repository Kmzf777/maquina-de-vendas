# Preparação da campanha de reativação — runbook

Prepara os leads no CRM com briefing de contexto e registra os opt-outs pendentes.
**Não dispara nada.** O disparo é criado depois, pela interface do CRM.

- Spec: `docs/superpowers/specs/2026-08-08-reativacao-crm-preparacao-design.md`
- Plano: `docs/superpowers/plans/2026-08-08-reativacao-crm-preparacao.md`
- Código: `scripts/reativacao/generate_sql.py` (não executa nada — só gera `preparar.sql` e `rollback.sql`), `scripts/reativacao/transform.py`

Números do lote atual (`reativacao_bling_2026-08-10`), verificados contra a produção:
**235 leads novos, 41 existentes, 276 notas, 51 opt-outs (10 pulados de 61
candidatos detectados), 4 exclusões.** `preparar.sql` sai com ~6.600 linhas /
~400 KB; `rollback.sql` com ~25 linhas.

**Nota sobre os números (fix round 3, C2):** a duplicata lógica da decisão D9
(`Atma`, `11981154002` → `5511981154002`) só é reconhecida como "existente"
depois que `carregar_nomes_crm` passou a normalizar as chaves do TSV — antes
disso ela contava como "novo" e o `INSERT` correspondente era engolido pelo
`ON CONFLICT (phone) DO NOTHING` (porque a normalização de telefone do passo 1
já tinha renomeado a linha do banco). Por isso os números mudaram de
**236/40** para **235/41** em relação a uma versão anterior deste runbook —
a lista final de disparo continua em 272 (276 − 4 exclusões).

---

## 0. Pré-requisito: backup

O banco de produção **não tem backup automático** (`archive_mode = off`, sem
dump nem cron agendado). Tirar o dump é obrigatório antes de qualquer escrita —
não é um "seria bom", é o único jeito de voltar atrás se algo além do que o
`rollback.sql` cobre der errado.

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D pg_dump -U postgres --no-owner postgres > /root/backup-pre-reativacao-\$(date +%F).sql; ls -lh /root/backup-pre-reativacao-*.sql"
```

**Esperado:** um arquivo listado com tamanho compatível com o banco (~106 MB).
Não seguir adiante se o tamanho vier muito menor que isso (dump truncado).

---

## 1. Levantar o estado atual do CRM

Três arquivos, todos puxados do banco de produção para a máquina local.

### 1.1 Leads que já existem (telefone + nome)

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -c \"\\copy (select regexp_replace(phone, '[^0-9]', '', 'g'), coalesce(name, '') from leads) to stdout\"" > /tmp/nomes_crm.tsv
```

**⚠ Armadilha documentada — não "corrigir" isto de volta:** o formato TEXT
padrão do `\copy` do psql **escapa um TAB real como os dois caracteres literais
`\t`** quando o TAB está *dentro do valor de uma única coluna* — é o que
acontece se a consulta for escrita como
`select phone || chr(9) || name ...` (concatenando telefone e nome numa
coluna só, usando `chr(9)` como separador manual). Uma versão anterior deste
CLI leu esse arquivo quebrado e reportou silenciosamente "zero leads
existentes" — **276 novos / 0 existentes**, em vez de **236 / 40**. O comando
acima evita a armadilha por construção: são **duas colunas reais** na
consulta (`phone`, `name`), então o delimitador entre elas é o byte de TAB
verdadeiro que o próprio `COPY` usa internamente — não um caractere digitado
em nenhuma camada de shell. O CLI (`carregar_nomes_crm` em `generate_sql.py`)
tolera as duas formas (TAB real ou a sequência literal `\t`) e recusa o
arquivo se nenhuma linha for parseável, mas **o comando de extração aqui
deve continuar produzindo TAB real** — a tolerância no CLI é uma rede de
segurança, não uma desculpa para gerar o arquivo errado.

**Esperado:** arquivo não vazio, uma linha por lead, `wc -l /tmp/nomes_crm.tsv`
compatível com a base (milhares de linhas). Se vier vazio ou com uma única
linha estranha, **pare** — o CLI vai abortar com `ValueError` ao ler isso, o
que é o comportamento correto (nunca tratar "CRM vazio" como estado normal).

### 1.2 Telefones que já têm dono (`assigned_to` preenchido)

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -A -t -c \"select regexp_replace(phone, '[^0-9]', '', 'g') from leads where assigned_to is not null\"" > /tmp/donos.txt
```

**Atenção:** `--donos` é opcional na sintaxe do CLI, mas **nunca rode sem
ele** neste lote. Se o arquivo vier vazio ou for omitido, `gerar_update_conservador`
trata *todos* os 41 leads existentes como "sem dono" e atribui `assigned_to`
ao João mesmo nos que já têm responsável — sobrescrevendo uma atribuição real.

### 1.3 Telefones já marcados `opt_out = true`

```bash
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker exec \$D psql -U postgres -A -t -c \"select regexp_replace(phone, '[^0-9]', '', 'g') from leads where opt_out = true\"" > /tmp/optouts_ja_marcados.txt
```

Este arquivo vai para `--optouts-ja-marcados` no passo 3 — sem ele, o CLI
tentaria marcar de novo quem já está marcado, a contagem de UPDATEs
efetivamente aplicados ficaria menor que `len(optouts)`, e o próprio SQL
gerado abortaria a transação inteira no `RAISE EXCEPTION` do rodapé (ver
seção 5).

---

## 2. Preparar o arquivo de opt-outs detectados

`/tmp/optouts.json` vem de um processo separado de detecção por mensagem (fora
do escopo deste script): 61 telefones candidatos, cada um com `data` e `texto`
da mensagem que caracterizou o opt-out. Se o processo de detecção gerar campos
extras, reduza para só o que o CLI espera:

```bash
python -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); \
  json.dump({k:{'data':v['data'],'texto':v['texto']} for k,v in d.items()}, \
  open('/tmp/optouts.json','w',encoding='utf-8'), ensure_ascii=False)" \
  <caminho do JSON de detecção>
```

**Importante:** este arquivo deve conter **todos** os 61 candidatos, mesmo os
que já estão marcados no banco. É o `--optouts-ja-marcados` (passo 1.3) que
filtra os 10 já marcados — não pré-filtre aqui, senão a contagem que o CLI
reporta como "pulados" fica sem sentido de auditoria (ver passo 4).

---

## 3. Gerar o SQL

Rodar da raiz do repo. Os CSVs de entrada ficam fora do repo, em
`DB Leads/` (pasta irmã de `maquina-de-vendas`):

```bash
python scripts/reativacao/generate_sql.py \
  --disparo "../DB Leads/DISPARO-segunda-2026-08-10.csv" \
  --master  "../DB Leads/CANASTRA-LEADS-MASTER-2026-08-08.csv" \
  --nomes-crm /tmp/nomes_crm.tsv \
  --donos /tmp/donos.txt \
  --optouts /tmp/optouts.json \
  --optouts-ja-marcados /tmp/optouts_ja_marcados.txt \
  --esperado-novos 235 \
  --esperado-existentes 41 \
  --saida /tmp/reativacao
```

`--esperado-novos` e `--esperado-existentes` **não são só documentação** —
se a contagem calculada a partir dos CSVs não bater exatamente com esses
números, o CLI imprime `ERRO: contagem nao bate com o esperado -> ...` em
stderr, retorna código de saída 1 e **não escreve nenhum arquivo** (nem
`preparar.sql` nem `rollback.sql`). Isso troca "um humano comparando números
impressos de cor" por uma trava automática — sempre passe esses dois flags
com os valores esperados do lote, nunca rode sem eles.

**Saída esperada (stdout):**

```
leads novos:      235
leads existentes: 41
notas:            276
opt-outs:         51
  pulados (confirmados no CRM):     10
  pulados (NAO encontrados no CRM): 0
exclusoes:        4
gerado: /tmp/reativacao/preparar.sql
gerado: /tmp/reativacao/rollback.sql
```

Se `pulados (NAO encontrados no CRM)` vier maior que zero, **pare e
investigue antes de continuar** — o CLI já imprime os telefones ofensivos
logo abaixo dessa linha. Isso significa que `--optouts` ou
`--optouts-ja-marcados` tem um telefone que não corresponde a nenhum lead do
CRM, ou seja, um dos dois arquivos de entrada está errado (número
desatualizado, erro de digitação, etc.) — nunca assuma que é inofensivo,
porque o risco é justamente descartar por engano um opt-out real (a pessoa
continuaria recebendo mensagem).

---

## 4. Revisar o SQL gerado antes de executar

Guardrails de contagem (devem bater exatamente com os números do passo 3):

```bash
grep -c "INSERT INTO leads"      /tmp/reativacao/preparar.sql   # 235
grep -c "UPDATE leads SET"       /tmp/reativacao/preparar.sql   # 93  (41 existentes + 51 opt-outs + 1 normalizacao de telefone)
grep -c "INSERT INTO lead_notes" /tmp/reativacao/preparar.sql   # 276
grep -c "RAISE EXCEPTION"        /tmp/reativacao/preparar.sql   # 4   (3 do rodape + 1 da normalizacao de telefone D9)
```

Guardrails de segurança (devem dar **zero**, sem exceção):

```bash
grep -cE "broadcasts|broadcast_leads" /tmp/reativacao/preparar.sql            # 0 — obrigatório: nenhuma referência às tabelas de disparo
grep -cE "SET \(?(stage|status|human_control|ai_enabled)" /tmp/reativacao/preparar.sql  # 0 — obrigatório: nenhuma escrita nessas colunas
```

Se qualquer um desses vier diferente do esperado, **não execute** — volte ao
código (`generate_sql.py`), não ao SQL gerado (o arquivo nunca deve ser
editado à mão; o próprio cabeçalho do arquivo diz isso).

Conferir também o tamanho e o rollback:

```bash
wc -l /tmp/reativacao/preparar.sql   # ~6.600 linhas
wc -l /tmp/reativacao/rollback.sql   # ~25 linhas
```

Por fim, ler à mão os 4 blocos marcados `⚠ FORA DA CAMPANHA` dentro do SQL
(procure por essa string) — são os leads com `MOTIVOS_EXCLUSAO`: recebem lead
e nota, mas não fazem parte da campanha de disparo.

---

## 5. Executar

```bash
scp /tmp/reativacao/preparar.sql root@173.249.15.11:/tmp/
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker cp /tmp/preparar.sql \$D:/tmp/; docker exec \$D psql -U postgres -v ON_ERROR_STOP=1 -f /tmp/preparar.sql"
```

O próprio arquivo já abre com `\set ON_ERROR_STOP on` e `BEGIN;` — o
`-v ON_ERROR_STOP=1` na linha de comando é redundância defensiva, não a única
proteção. Qualquer erro em qualquer statement aborta a transação inteira;
nada fica pela metade.

---

## 6. Verificar

**Não há verificação manual de números aqui.** Antes do `COMMIT;`, o próprio
`preparar.sql` roda quatro blocos `DO $$ ... END $$` que contam/checam:
(1) leads do lote (chaveado em `metadata->>'origem'` **e** `metadata->>'lote'`
juntos — nunca só `lote`, para nunca colidir com a contagem de opt-outs, que
usa a chave separada `optout_lote`), (2) notas do lote, (3) opt-outs marcados
por este lote, e um quarto bloco logo após a normalização de telefone (D9),
que verifica que ela de fato afetou exatamente 1 linha. Todos executam
`RAISE EXCEPTION` se a contagem/condição não bater com o esperado
(235+41=276 leads/notas, 51 opt-outs). Um `RAISE EXCEPTION` dentro de uma
transação Postgres força o rollback automático de tudo que veio antes,
inclusive dos `INSERT`s que pareciam ter dado certo — o psql retorna erro e o
`COMMIT;` no final do arquivo nunca roda.

Ou seja: **se o comando do passo 5 terminar sem erro (código de saída 0 e sem
`ERROR` na saída), a preparação foi aplicada corretamente e já está
committada.** Se aparecer `ERROR:  esperado N ..., encontrado M` (ou o erro de
normalização de telefone), **a transação inteira foi revertida e nada foi
escrito no banco** — nenhum lead, nenhuma nota, nenhum opt-out desta execução
persiste, mesmo que o `psql` tenha impressos os `\echo` de sucesso antes do
erro. Trate como falha completa, investigue a causa (normalmente um dos
arquivos do passo 1 mudou entre a geração do SQL e a execução) e regenere o
SQL do zero a partir do passo 1. Nunca assuma "deu quase certo" — ou o
`COMMIT;` rodou (tudo persistiu) ou não rodou (nada persistiu); não há meio
termo dentro de uma única transação.

Ainda assim, é razoável confirmar visualmente as linhas `\echo` impressas
durante a execução (`--- leads do lote (esperado: 276) ---`, etc.) — elas
aparecem mesmo quando tudo passa, só não são a proteção em si.

---

## 7. Rollback (se necessário)

```bash
scp /tmp/reativacao/rollback.sql root@173.249.15.11:/tmp/
ssh root@173.249.15.11 "D=\$(docker ps -qf name=supabase_db); docker cp /tmp/rollback.sql \$D:/tmp/; docker exec \$D psql -U postgres -v ON_ERROR_STOP=1 -f /tmp/rollback.sql"
```

**O que o rollback desfaz:**

1. Remove todas as `lead_notes` cujo conteúdo contém o identificador do lote
   (as 276 notas de briefing, novas e existentes).
2. Desmarca `opt_out` **somente** nos leads que este lote marcou
   (`metadata->>'optout_lote'` igual ao lote **e**
   `optout_fonte = 'mensagem_do_cliente'`) — opt-outs de qualquer outro
   lote/motivo não são tocados — e, na mesma instrução, limpa as chaves de
   evidência do opt-out (`optout_quando`, `optout_disse`, `optout_fonte`,
   `optout_lote`).
3. Apaga os leads que este lote **criou** — e só esses.
4. Remove as chaves de metadata do lote (`lote`, `origem`, `id_bling`,
   `icp_score`, `criado_por_lote`) de qualquer lead que este lote criou ou
   atualizou (`metadata->>'origem' = 'reativacao_bling'` **e**
   `metadata->>'lote'` igual ao lote — as duas juntas, nunca só uma: os
   opt-outs nunca gravam `origem`, então este passo nunca os alcança nem
   apaga por engano um `metadata.origem` pré-existente de outra origem
   `terceirizacao`/`atacado`).

**Por que o critério do passo 3 é `metadata->>'criado_por_lote'`, e não "lead
sem mensagem":** essa chave só é escrita por `gerar_insert_lead` (leads
novos) — `gerar_update_conservador` (leads existentes) nunca a grava. Uma
versão anterior do rollback usava "o lead não tem nenhuma mensagem" como
único critério para decidir o que apagar, partindo da suposição de que só
leads novos ficariam sem mensagem. Na produção real isso é falso: **3 dos 41
leads pré-existentes não têm mensagem nenhuma**, e esse rollback antigo teria
apagado esses 3 leads reais junto com **4 notas** que já existiam antes deste
lote. Chavear em `criado_por_lote` elimina esse risco por construção — a
checagem "sem mensagem" continua no SQL, mas agora como uma segunda rede de
segurança combinada com `AND`, não como critério único.

**O que o rollback NÃO desfaz** — se qualquer um destes importar, restaure o
dump do passo 0 em vez de confiar no rollback:

- **Campos preenchidos em leads existentes.** `gerar_update_conservador` só
  preenche colunas que estavam vazias (`COALESCE(NULLIF(col, ''), ...)`) —
  o rollback não limpa `cnpj`, `razao_social`, `nome_fantasia`, `email`,
  `endereco` nem `assigned_to` de volta ao estado anterior nesses 41 leads.
  Só a chave de metadata do lote sai; o valor de coluna que foi preenchido
  fica.
- **A normalização de telefone da decisão D9** (`11981154002` →
  `5511981154002`). O rollback não reverte esse UPDATE.
- **Leads criados por este lote que já receberam mensagem** de alguém antes
  do rollback rodar — a condição "sem mensagem" no passo 3 os protege de
  serem apagados (uma conversa real já em andamento não deve desaparecer),
  mas isso significa que ficam órfãos: sem a nota de briefing, sem as chaves
  de metadata do lote, porém ainda existindo como lead. Precisa de decisão
  manual sobre o que fazer com eles.

Ao final o script imprime `--- deve retornar 0 ---` seguido da contagem de
notas restantes do lote — deve ser `0`. Se vier diferente, alguma nota não
foi removida (ex.: teve uma edição manual no conteúdo entre a execução e o
rollback que mudou o padrão `LIKE`).

**Se algo pior acontecer** (dado corrompido fora do que o rollback cobre,
execução parcial por interrupção de rede, etc.): restaurar o dump do passo 0
é sempre o caminho seguro, já que o banco não tem nenhum outro backup.
