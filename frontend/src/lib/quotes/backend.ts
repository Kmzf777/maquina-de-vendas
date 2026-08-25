/**
 * Base do FastAPI para as rotas de orcamento que sao proxy.
 *
 * Sao cinco rotas repassando para o mesmo servico (POST, PUT/GET por id, PATCH
 * de situacao, convert e PDF); com a expressao inline em cada arquivo, corrigir
 * o nome da variavel de ambiente exigiria acertar cinco lugares e errar um
 * deixaria uma rota falando com `localhost` em producao.
 *
 * O `replace` tira a barra final: `NEXT_PUBLIC_FASTAPI_URL` termina com `/` em
 * alguns ambientes e `${base}/api/quotes` viraria `//api/quotes`, que o FastAPI
 * responde com 404 em vez de rotear.
 *
 * O `localhost` do fallback so vale para o processo local do Next; dentro do
 * Docker a variavel sempre existe e aponta para o nome do servico (regra 3 do
 * CLAUDE.md). E o mesmo fallback que `api/bling/orders` e `api/sales` ja usam —
 * mudar so aqui criaria uma divergencia pior que o valor.
 */
export function backendUrl(): string {
  return (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
}
