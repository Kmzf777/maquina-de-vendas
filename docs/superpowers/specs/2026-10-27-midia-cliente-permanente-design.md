# Arquivos do cliente param de sumir, com rotação segura de 6 meses

Cartão: "Corrigir sumiço dos arquivos após pouco tempo de enviados" (da1f51a7).

## Problema

Nas palavras do Rafael: os arquivos somem pouco tempo depois de enviados.

Causa, conferida em produção em 27/10:
- **Foto, vídeo, documento e figurinha que o cliente manda** são salvos em `messages.media_url` só
  como o *media_id* da Meta, sem cópia no nosso servidor. O CRM busca o arquivo na Meta toda vez
  que alguém abre a conversa (`frontend/src/app/api/media/route.ts`).
- A Meta apaga essas mídias depois de alguns dias. No teste com a Graph API, mídias de 23/10 e
  24/10 ainda abriam (200), e todas de 19/10 para trás deram erro (400).
- O áudio do cliente (bucket `audio`) e tudo o que o vendedor ou o robô enviam
  (`whatsapp-media/outbound/`) já têm cópia no nosso servidor e continuam abrindo.

Espaço: o disco da VPS tem 387 GB, com 212 GB livres. O Storage inteiro ocupa ~0,95 GB e cresce de
200 a 350 MB por mês. Pela estimativa (não medida), a mídia do cliente acrescenta ~100 MB/mês.

Decisão do Rafael: **opção B**. Guardar cópia de tudo e apagar o que tiver mais de **6 meses**.

## O que muda

### 1. Cópia da mídia do cliente na chegada (backend)
- `backend/app/buffer/processor.py`, em `_resolve_media`: para image, video, document e sticker
  que chegam como `media_id`, baixa o arquivo com `_download_media_with_retry` (o mesmo caminho do
  áudio) e sobe para `whatsapp-media/inbound/<media_id>.<ext>` (helper novo
  `_upload_inbound_media_to_storage`, no molde de `_upload_audio_to_storage`).
- `media_url` passa a guardar a URL pública do Storage.
- Fail-soft: se o download ou o upload falhar, fica o `media_id` como hoje e a mensagem nasce do
  mesmo jeito. Nada muda no que a Valéria lê ou responde.
- Teto de tamanho: o mesmo limite que a Meta aceita (16 MB para mídia, 100 MB para documento).
  Acima disso não copia e mantém o `media_id`.

### 2. Rotação de 6 meses (worker)
- Tarefa periódica nova no `canastra_worker` (`backend/app/worker/main.py`, via `run_periodic`),
  módulo novo `backend/app/media_retention/`. Roda 1 vez por dia, apaga em lotes de até 500
  objetos por rodada e repete até acabar.
- **Escopo do que apaga** (só isto): objetos com `created_at` de mais de 180 dias em
  - bucket `audio` (áudio do cliente);
  - bucket `whatsapp-media`, prefixos `inbound/` e `outbound/`.
- **Nunca apaga**: `whatsapp-media/valeria-botoes/` (imagens fixas do fluxo de botões), qualquer
  outro bucket ou prefixo, e arquivo cuja URL apareça em configuração de fluxo, campanha ou
  template. Antes de apagar, o job confere se a URL é referenciada fora da tabela `messages`.
  Se for, pula o arquivo.
- Apaga pela API do Storage (`storage.from_(bucket).remove(paths)`), nunca por `DELETE` direto no
  banco.
- Depois de apagar, marca as mensagens que apontavam para o arquivo:
  `metadata.media_expired = true` (o `media_url` fica, como registro).
- Registro: cada rodada grava no log (`[media-retention]`) quantos arquivos apagou, quantos bytes
  liberou e quantos pulou. Os caminhos apagados vão para uma tabela nova `media_retention_log`
  (caminho, bucket, tamanho, apagado_em).
- **Modo simulação**: a variável `MEDIA_RETENTION_DRY_RUN` vem `true` por padrão. Nesse modo o
  job só lista e registra o que apagaria, sem apagar nada. A primeira semana em produção roda
  assim; depois de conferida a lista, a variável passa a `false`.
- A idade (180 dias) fica na variável `MEDIA_RETENTION_DAYS`, para mudar sem deploy de código.

### 3. Tela de Conversas (frontend)
- `frontend/src/components/conversas/message-bubble.tsx`: se `metadata.media_expired` for true, ou
  se a mídia não carregar (o proxy da Meta responde erro ou o Storage responde 404), mostra a
  caixa "Arquivo expirado" no lugar da imagem quebrada ou do botão de baixar que não funciona.
- Isso também cobre as mídias antigas que já sumiram da Meta (de ~20/10 para trás), que **não
  voltam**.

## Onde

- Repo `ValerIA`, branch `agente/da1f51a7`.
- Backend: `backend/app/buffer/processor.py`, `backend/app/worker/main.py`, módulo novo
  `backend/app/media_retention/`, migração SQL da tabela `media_retention_log`.
- Frontend: `message-bubble.tsx` e, se preciso, `frontend/src/app/api/media/route.ts`.
- Serviços: `canastra_api` (recebe a mídia), `canastra_worker` (rotação), `crm_crm` (tela).

## Como testar em modo teste

- Testes automatizados (pytest) no worktree:
  - `_resolve_media` com image, video, document e sticker: sobe para `inbound/` e devolve a URL;
    em falha devolve o `media_id`; acima do teto não copia.
  - Job de retenção com Storage e banco falsos: apaga só o que passou de 180 dias e está nos
    prefixos permitidos; pula `valeria-botoes/` e URL referenciada; em dry-run não chama
    `remove`; marca `media_expired`; respeita o lote de 500.
- Frontend (vitest/jest do repo): a bolha mostra "Arquivo expirado" com `media_expired` e quando
  a mídia dá erro.
- Ponta a ponta no backend dev (`dev.canastrainteligencia.com`, Dev Router): uma foto e um PDF
  enviados do número de teste da whitelist precisam aparecer com URL `.../whatsapp-media/inbound/...`
  e abrir (HTTP 200, conteúdo conferido).
- Print: tela de Conversas do CRM em dev com a foto recebida e uma mídia antiga mostrando
  "Arquivo expirado".
- Dry-run do job contra o banco de produção, **só leitura** (SELECT): lista quantos arquivos e
  quantos MB seriam apagados hoje. Hoje o resultado esperado é perto de zero, porque o arquivo
  mais antigo é de maio de 2026.

## Como publicar

1. `git pull origin master` no branch, rodar a suíte de novo.
2. Merge em `master` e `git push origin agente/da1f51a7:master`. O GitHub Actions faz o deploy de
   `crm_crm`, `canastra_api` e `canastra_worker`.
3. Migração da tabela `media_retention_log`: só cria tabela, nada é alterado ou apagado.
4. `MEDIA_RETENTION_DRY_RUN=true` em produção na estreia.
5. Como voltar atrás: `git revert` do merge + push (redeploy pelo Actions), ou
   `docker service rollback` dos três serviços. A tabela nova pode ficar sem prejuízo. Os
   arquivos copiados em `inbound/` não atrapalham o código antigo, porque a bolha já abre
   qualquer URL http.

## Como testar em produção

- Esperar uma foto real de cliente chegar (sem mandar nada a ninguém), conferir que `media_url`
  é `.../inbound/...` e que abre no CRM. Print da conversa.
- Logs do `canastra_worker` com `[media-retention]` em dry-run: número de arquivos que seriam
  apagados e a lista na `media_retention_log`.
- Uma conversa antiga com foto de antes de 20/10 mostrando "Arquivo expirado".
- **Nenhuma ação com efeito externo**: nada de mensagem a cliente, pedido, NF ou cobrança. O
  teste em produção só lê e não apaga nada, porque o job estreia em dry-run.
- Desligar o dry-run (`false`) só depois de o Rafael ver a lista da primeira semana. Como ainda
  não há arquivo com mais de 6 meses, a primeira exclusão real deve acontecer por volta de
  novembro e dezembro de 2026.

## Fora do escopo

- Recuperar as mídias que já sumiram da Meta. Não é possível.
- Comprimir imagem ou mandar arquivo para armazenamento externo (opção C).
- Mudar a mídia do vendedor e do robô além da rotação de 6 meses.
- Mexer em outros buckets do Supabase.
