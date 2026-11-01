# Pré-visualizar anexos na tela Conversas

**Data:** 2026-11-01
**Cartão:** 3a6de8d1 — "Deixar arquivos enviados e recebidos com pre-visualização, sem necessidade de baixar para ver mas caso necessário com a opcão de baixar."
**Branch:** `agente/3a6de8d1` (de `origin/master`)

## Problema

Nas palavras do Rafael: arquivos enviados e recebidos precisam ter pré-visualização, **sem
necessidade de baixar para ver**, mas **com a opção de baixar** quando necessário. O escopo é
só a tela **Conversas** do CRM.

Hoje, em `frontend/src/components/conversas/message-bubble.tsx`:

| Tipo | Hoje | Base em produção |
|---|---|---|
| Imagem | miniatura de no máximo 240×320 no balão. Não amplia e não baixa. | 5.824 |
| Documento (PDF etc.) | só o link "Baixar". Para ver, é preciso baixar. | 382 (94 com `.pdf` no nome, 275 sem nome) |
| Vídeo | toca no balão. Não amplia e não baixa. | 37 |
| Áudio | toca no balão. Não baixa. | 2.986 |

O `media_url` pode estar em três formatos:
- URL do Supabase Storage (`https://supabase.canastrainteligencia.com/...`), servida com o `content-type` certo. Exemplo: PDF sai como `application/pdf`, que o navegador abre direto.
- `blob:` de mensagem que acabou de ser enviada.
- `media_id` legado da Meta, servido por `/api/media` (inline, ou anexo com `download=1&filename=`).

## O que muda (abordagem A, escolhida pelo Rafael)

Ao clicar num anexo no balão, abre uma **janela por cima do chat** (modal em tela cheia,
fundo escuro), sem sair da conversa. A janela tem:

- **Cabeçalho**: o nome do arquivo (ou "Imagem" / "Vídeo") e os botões **Baixar** e **Fechar (X)**.
- **Corpo**, conforme o tipo:
  - **Imagem**: imagem grande, ajustada à tela (`object-contain`).
  - **Vídeo**: player grande com controles.
  - **PDF**: o documento aberto ali mesmo (`<iframe>` com o visualizador do navegador, com rolagem de páginas).
  - **Outros documentos** que o navegador não mostra (.ai, .psd, .pptx, .eps…): aviso "Sem pré-visualização para este tipo de arquivo" e o botão Baixar em destaque.
- A janela fecha com **Esc**, no **X** ou com clique no fundo escuro.

Como se reconhece um PDF: o nome termina em `.pdf`. Documento sem nome (são 275) é tratado como
PDF e vai para o `<iframe>`. Se o navegador não conseguir mostrá-lo, o botão Baixar continua
disponível no cabeçalho.

No balão:
- **Imagem** e **vídeo**: a miniatura vira clicável (cursor de mão) e abre a janela. O vídeo
  continua tocando no balão. Para ampliar, há um botão de "expandir" sobre ele, porque o clique no
  vídeo é do player.
- **Documento**: o cartão do arquivo vira clicável e abre a janela. Ganha também o link
  "Abrir" ao lado do "Baixar", que continua lá.
- **Áudio**: continua tocando no balão, sem janela. Ganha só um link "Baixar" pequeno abaixo.
- Sticker, localização e contato ficam como estão.

**Baixar** força o download com o nome do arquivo, conforme o formato do `media_url`:
- URL do Supabase Storage: acrescenta `?download=<nome>`. O Storage responde com `Content-Disposition: attachment`.
- `/api/media`: já existe com `download=1&filename=`.
- `blob:`: usa o atributo `download` do link.
- Sem nome: usa "documento", "imagem.jpg", "video.mp4" ou "audio.ogg".

## Onde

- Repositório `ValerIA`, só o frontend:
  - `frontend/src/components/conversas/media-viewer.tsx` (novo): o modal. Recebe `{ tipo, src, nome, downloadHref, onClose }`.
  - `frontend/src/lib/media-download.ts` (novo): função pura que monta o link de download para os três formatos de `media_url`.
  - `frontend/src/components/conversas/message-bubble.tsx`: torna os anexos clicáveis, abre o modal e põe Baixar no áudio.
  - Testes: `media-download.test.ts`, `media-viewer.test.tsx` e casos novos em `message-bubble.test.tsx`.
- Nenhuma mudança em backend, banco, Storage ou `/api/media`.

## Como testar em modo teste

1. **Testes automáticos** (vitest) no worktree:
   - `media-download`: os três formatos de URL, nome com acento e espaço, e documento sem nome.
   - `media-viewer`: renderiza imagem, vídeo, PDF (`iframe`) e tipo sem prévia. Fecha com Esc e com o X. O botão Baixar aponta para o link certo.
   - `message-bubble`: clicar na imagem ou no documento abre o modal, e o áudio mostra Baixar.
   - Rodar a suíte inteira do frontend, `npm run build` e o lint, como faz o CI.
2. **Tela real, local**: `npm run dev` do frontend no worktree, apontando para o Supabase de
   produção. A tela só **lê** as mensagens que já existem e não envia nada. Abrir uma conversa com
   imagem, PDF e vídeo recebidos e conferir:
   - a janela abre e mostra o conteúdo;
   - Baixar entrega o arquivo com o nome certo;
   - Esc fecha a janela.
3. **Prints** com `print-frontend.mjs` em `http://localhost:3000/conversas`: um da imagem
   ampliada, um do PDF aberto na janela e um do balão de documento com "Abrir / Baixar".

## Como publicar

- `git pull origin master` no branch, conferir os testes de novo e depois
  `git push origin agente/3a6de8d1:master`. O push aciona o GitHub Actions (`deploy.yml`). Como
  mudou `frontend/`, o job `deploy-crm` roda testes e build e faz o deploy do serviço `crm_crm`
  na VPS. Nenhum outro serviço é tocado.
- Acompanhar o run no GitHub Actions e conferir na VPS com `docker service ps crm_crm` e
  `docker service logs crm_crm --since 10m`.
- **Voltar atrás:** `git revert` do merge na master e push. O Actions refaz o deploy da versão
  anterior. Em emergência, use `docker service rollback crm_crm`.

## Como testar em produção

- Abrir `https://crm.canastrainteligencia.com/conversas`, numa conversa com imagem, PDF e vídeo já recebidos.
  Conferir a janela, o Baixar e o Esc, e fazer os prints.
- **Nenhuma ação com efeito externo.** O teste só abre e baixa arquivos que já existem. Nenhuma
  mensagem é enviada a cliente, nada vai para o Bling e nada é gravado no banco.

## Fora do escopo

- Outras telas do CRM (perfil do lead, orçamentos etc.).
- Galeria para navegar entre os anexos da conversa (setas anterior/próximo).
- Zoom e rotação de imagem e prévia de .pptx, .psd e .ai.
- Pré-visualizar o arquivo **antes de enviar** (no campo de anexar).
- Mudanças em `/api/media` ou no Storage.
