# Endereço do cliente no PDF de orçamento — design

Cartão: "Endereço não aparece no PDF de orcamento gerado no CRM" (9adfe0f1), quadro BEEINSIDE CANSTRA CRM.

## Problema

Palavras do cartão: "Endereço não aparece no PDF de orcamento gerado no CRM". O Rafael confirmou que
se trata do **endereço do cliente**, o mesmo da ficha do contato no Bling, impresso junto com o nome
e o CNPJ.

O que a investigação de 2026-10-14 encontrou:

- O PDF é montado por `GET /api/quotes/{id}/pdf` (`backend/app/quotes/router.py`) e desenhado em
  `backend/app/quotes/pdf.py`. `_cliente()` imprime só CLIENTE, CPF/CNPJ, E-MAIL, WHATSAPP e A/C.
  Nenhum endereço do cliente entra no documento. O único endereço impresso é o da Canastra, no
  cabeçalho.
- O CRM não tem o endereço guardado. Dos 19 orçamentos, só 1 lead tem `leads.endereco`, e mesmo
  assim só o nome da rua. A cópia local `bling_contacts.endereco` está vazia em 6.686 dos 6.689
  contatos, porque a sincronização usa a listagem do Bling e ela não traz o endereço.
- A ficha do contato no Bling (`GET /contatos/{id}`) traz `endereco.geral` completo: endereco,
  numero, complemento, bairro, cep, municipio, uf. Isso foi conferido em produção, só com leitura,
  num cliente que tem orçamento.

## Decisão (com o Rafael)

Opção A: no download do PDF, consultar ao vivo a ficha do contato vinculado no Bling e imprimir o
endereço. O banco não muda, a sincronização não muda e os 19 orçamentos que já existem passam a
sair com endereço.

## O que muda

Repositório: `ValerIA` (máquina de vendas), só o backend. Serviço afetado: `canastra_api`.

### `backend/app/quotes/router.py`
- Nova função `_endereco_do_cliente(lead_id, account) -> str | None`:
  1. Busca em `lead_bling_contacts` o `bling_contact_id` do lead **na conta do orçamento**
     (`conta_do_pdf`).
  2. Se achar, faz `GET /contatos/{id}` com `BlingClient(account=conta_do_pdf)`, sob um
     `asyncio.wait_for` de 5 s, e formata `data.endereco.geral`.
  3. Se não houver vínculo, se o Bling falhar (erro, timeout, 4xx/5xx) ou se a ficha vier sem
     endereço, usa `leads.endereco` (texto livre) quando estiver preenchido. Sem nenhum dos dois,
     devolve `None`.
  4. Qualquer falha vira `logger.warning("[QUOTES] ...")` e **nunca** impede o download.
- `_load_lead_para_pdf` passa a selecionar também `endereco`.
- `dados` ganha `"lead_endereco": <resultado>`. A lista continua explícita, e `internal_notes`
  continua fora.

### `backend/app/quotes/pdf.py`
- Nova função pura `formatar_endereco(geral: dict) -> str | None`, no formato
  `Rua X, 123 - Sala 2 · Bairro · Cidade/UF · CEP 00000-000`. Partes vazias são omitidas, e o CEP
  sai com máscara quando tiver 8 dígitos. Sem rua nem cidade, devolve `None`.
- `_cliente()` ganha a linha `("ENDEREÇO", quote.get("lead_endereco"))` logo depois de CPF/CNPJ.
  Segue a regra que já existe: sem valor, a linha some. O texto passa por `_esc` como os demais.

### Relação com o cartão b3788533 ("End. colocados no CRM não vão para o Bling")
Os dois cartões se complementam. Quando aquele for publicado, o endereço digitado no CRM chega ao
Bling, e o PDF o lê de lá. O PDF não depende daquele cartão.

## Como testar em modo teste

No worktree `ValerIA/.claude/worktrees/agente-9adfe0f1`, branch `agente/9adfe0f1`.

1. **TDD (pytest, local):**
   - `backend/tests/test_quotes_pdf.py`:
     - `formatar_endereco` com endereço completo, sem complemento, sem número, com CEP sem máscara
       e vazio (`None`).
     - O PDF gerado contém o texto do endereço quando `lead_endereco` vem preenchido e não contém o
       rótulo "ENDEREÇO" quando ele vem vazio. O texto do PDF é extraído com a ferramenta que os
       testes já usam.
   - `backend/tests/test_quotes_router.py`, com o Bling e o Supabase falsos (padrão do arquivo):
     - Vínculo encontrado e Bling com endereço: endereço formatado.
     - Bling dá erro ou timeout: cai para `leads.endereco`.
     - Sem vínculo e sem `leads.endereco`: `None` e PDF gerado mesmo assim (200).
     - O Bling é consultado na conta do orçamento, e não na conta padrão.
   - Suíte inteira de `backend/tests` verde antes de seguir.
2. **PDF real, sem publicar:** na VPS, build da imagem do branch como
   `canastra-api:teste-9adfe0f1`, sem tocar em `canastra-api:latest`. Em seguida,
   `docker run --rm` de um script de uma linha, com a mesma env e rede do `canastra_api`, que chama a
   lógica da rota para o orçamento mais recente. A única ação externa é um GET no Bling (leitura).
   O PDF é convertido em PNG (PyMuPDF/pdftoppm) e vira o print do bloco do cliente com o endereço.
   O container é descartado no fim.

## Como publicar

1. No worktree: `git pull origin master` (merge, sem rebase de branch compartilhado) e testes de
   novo.
2. `git push origin agente/9adfe0f1:master`. O GitHub Actions (`deploy.yml`) valida, faz o build de
   `canastra-api:latest` na VPS e roda `docker service update --force canastra_api` e
   `canastra_worker`. O job do CRM (`crm_crm`) também roda, porque o workflow não filtra por pasta;
   o frontend não muda.
3. Acompanhar o run (`gh run watch`) e `docker service ps canastra_api` até a réplica nova ficar
   `Running`.
4. **Voltar atrás:** `git revert <commit>` e push para `master`, sem force. O mesmo deploy
   republica a versão anterior. A mudança não toca banco, então não há migração a desfazer.

## Como testar em produção

- Baixar, pela rota de produção, o PDF de um orçamento **já existente** (o mais recente, do vínculo
  conferido na investigação) com o usuário de teste do CRM, ou pelo botão de PDF na tela
  `/orcamento`. Converter em PNG e conferir o bloco do cliente com o endereço. Esse PNG é o print.
- Conferir `docker service logs canastra_api` sem `[QUOTES]` de erro novo.
- **Sem ação com efeito externo:** baixar o PDF só lê do Supabase e faz um GET no Bling. Nenhum
  orçamento, venda, pedido ou NF é criado ou alterado, nenhuma mensagem vai a cliente e nada é
  cobrado. O PDF é gerado só para conferência e não é enviado a ninguém.

## Fora do escopo

- Gravar o endereço na sincronização de contatos (opção B) ou no orçamento (opção C).
- Editar endereço no CRM ou enviá-lo ao Bling (é o cartão b3788533).
- Endereço de entrega diferente do cadastral e qualquer mudança visual no resto do PDF.
- Frontend e banco: nenhuma mudança.
