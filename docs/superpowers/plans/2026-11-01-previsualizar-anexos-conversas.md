# Pré-visualizar anexos na tela Conversas — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ao clicar num anexo (imagem, vídeo, documento) do chat em Conversas, abrir uma janela por cima do chat com o conteúdo e os botões Baixar e Fechar. O áudio ganha "Baixar".

**Architecture:** Duas peças novas:
- uma função pura, `lib/media-download.ts`, que monta o link de download e decide o tipo de prévia;
- um modal, `components/conversas/media-viewer.tsx`, desenhado via `createPortal` em `document.body`.

`message-bubble.tsx` só torna os anexos clicáveis e abre o modal.

**Tech Stack:** Next.js (App Router), React, Tailwind, vitest + @testing-library/react (jsdom).

Spec: `docs/superpowers/specs/2026-11-01-previsualizar-anexos-conversas-design.md`

Fatos já conferidos em produção (01/11/2026):
- O Storage (`supabase/storage-api v1.60.4`) responde `GET <url>?download=<nome>` com `content-disposition: attachment; filename=<nome>`. Sem o parâmetro, serve inline e com o `content-type` certo (`application/pdf`). Não manda `X-Frame-Options`, e o CRM não tem CSP, então o PDF abre num `<iframe>`.
- Documento: o nome está em `document_name` ou, quando é null, em `content`. Na base, 272 dos 275 sem `document_name` têm `content` terminando em `.pdf`.

Comandos (rodar em `frontend/`): `npx vitest run <arquivo>`, `npm test`, `npm run lint`, `npm run build`.

---

### Task 1: `lib/media-download.ts` (função pura)

**Files:**
- Create: `frontend/src/lib/media-download.ts`
- Test: `frontend/src/lib/media-download.test.ts`

- [ ] **Step 1: Escrever o teste que falha**

```ts
import { describe, it, expect } from "vitest";
import { mediaDownloadHref, mediaFileName, documentPreviewKind } from "./media-download";

describe("mediaFileName", () => {
  it("usa o nome do arquivo quando existe", () => {
    expect(mediaFileName("document", "Pedido Café.pdf")).toBe("Pedido Café.pdf");
  });
  it("cai no nome padrão por tipo quando não há nome", () => {
    expect(mediaFileName("document", null)).toBe("documento");
    expect(mediaFileName("image", undefined)).toBe("imagem.jpg");
    expect(mediaFileName("video", "")).toBe("video.mp4");
    expect(mediaFileName("audio", "   ")).toBe("audio.ogg");
  });
});

describe("mediaDownloadHref", () => {
  it("URL do Storage ganha ?download=<nome> (o Storage responde como anexo)", () => {
    const href = mediaDownloadHref(
      "https://supabase.canastrainteligencia.com/storage/v1/object/public/media/a/b.pdf",
      "Pedido Café.pdf",
    );
    const u = new URL(href);
    expect(u.origin + u.pathname).toBe(
      "https://supabase.canastrainteligencia.com/storage/v1/object/public/media/a/b.pdf",
    );
    expect(u.searchParams.get("download")).toBe("Pedido Café.pdf");
  });
  it("proxy /api/media ganha download=1 e filename, mantendo os parâmetros", () => {
    const href = mediaDownloadHref("/api/media?media_id=123&conversation_id=conv-1", "nota.pdf");
    const u = new URL(href, "http://x");
    expect(u.pathname).toBe("/api/media");
    expect(u.searchParams.get("media_id")).toBe("123");
    expect(u.searchParams.get("conversation_id")).toBe("conv-1");
    expect(u.searchParams.get("download")).toBe("1");
    expect(u.searchParams.get("filename")).toBe("nota.pdf");
    expect(href.startsWith("/api/media?")).toBe(true);
  });
  it("blob: volta igual (o download vem do atributo download do link)", () => {
    expect(mediaDownloadHref("blob:http://localhost/abc", "x.pdf")).toBe("blob:http://localhost/abc");
  });
});

describe("documentPreviewKind", () => {
  it("nome terminado em .pdf → pdf (qualquer caixa)", () => {
    expect(documentPreviewKind("Nota Fiscal.PDF")).toBe("pdf");
  });
  it("sem nome → pdf (a base mostra que quase todos são PDF)", () => {
    expect(documentPreviewKind(null)).toBe("pdf");
    expect(documentPreviewKind("")).toBe("pdf");
  });
  it("outros formatos → file (sem prévia, só Baixar)", () => {
    expect(documentPreviewKind("arte.psd")).toBe("file");
    expect(documentPreviewKind("apresentacao.pptx")).toBe("file");
    expect(documentPreviewKind("video.mp4")).toBe("file");
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npx vitest run src/lib/media-download.test.ts`
Expected: FAIL. Mensagem: `Failed to resolve import "./media-download"`.

- [ ] **Step 3: Implementar**

```ts
/**
 * Link de download e tipo de prévia de um anexo do chat (tela Conversas).
 *
 * `media_url` chega em três formatos:
 * - URL do Supabase Storage (https://…): o Storage responde `?download=<nome>` com
 *   Content-Disposition: attachment. O atributo `download` do <a> não vale cross-origin.
 * - `/api/media?media_id=…` (media_id legado da Meta): o proxy aceita `download=1&filename=`.
 * - `blob:` (mensagem recém-enviada): o atributo `download` do <a> resolve.
 */
export type MediaKind = "image" | "video" | "audio" | "document";

const DEFAULT_NAMES: Record<MediaKind, string> = {
  image: "imagem.jpg",
  video: "video.mp4",
  audio: "audio.ogg",
  document: "documento",
};

export function mediaFileName(kind: MediaKind, name?: string | null): string {
  const trimmed = name?.trim();
  return trimmed ? trimmed : DEFAULT_NAMES[kind];
}

export function mediaDownloadHref(src: string, fileName: string): string {
  if (src.startsWith("blob:")) return src;
  if (src.startsWith("http")) {
    const url = new URL(src);
    url.searchParams.set("download", fileName);
    return url.toString();
  }
  const url = new URL(src, "http://x");
  url.searchParams.set("download", "1");
  url.searchParams.set("filename", fileName);
  return url.pathname + url.search;
}

/** PDF abre no visualizador do navegador; sem nome conta como PDF (272 de 275 na base são). */
export function documentPreviewKind(name?: string | null): "pdf" | "file" {
  const trimmed = name?.trim();
  if (!trimmed) return "pdf";
  return /\.pdf$/i.test(trimmed) ? "pdf" : "file";
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `npx vitest run src/lib/media-download.test.ts`
Expected: PASS (8 testes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/media-download.ts frontend/src/lib/media-download.test.ts
git commit -m "feat(anexos-conversas): link de download e tipo de previa do anexo"
```

---

### Task 2: `components/conversas/media-viewer.tsx` (o modal)

Independente da Task 1: recebe `downloadHref` pronto.

**Files:**
- Create: `frontend/src/components/conversas/media-viewer.tsx`
- Test: `frontend/src/components/conversas/media-viewer.test.tsx`

- [ ] **Step 1: Escrever o teste que falha**

```tsx
/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, screen, fireEvent } from "@testing-library/react";
import { MediaViewer } from "./media-viewer";

afterEach(cleanup);

function renderViewer(over: Partial<React.ComponentProps<typeof MediaViewer>> = {}) {
  const onClose = vi.fn();
  render(
    <MediaViewer
      kind="image"
      src="https://cdn.example/foto.jpg"
      name="foto.jpg"
      downloadHref="https://cdn.example/foto.jpg?download=foto.jpg"
      onClose={onClose}
      {...over}
    />,
  );
  return { onClose };
}

describe("MediaViewer", () => {
  it("abre como diálogo com o nome do arquivo", () => {
    renderViewer();
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(screen.getByText("foto.jpg")).toBeTruthy();
  });

  it("imagem: mostra a imagem grande", () => {
    renderViewer();
    const img = screen.getByRole("dialog").querySelector("img");
    expect(img?.getAttribute("src")).toBe("https://cdn.example/foto.jpg");
  });

  it("vídeo: mostra o player com controles", () => {
    renderViewer({ kind: "video", src: "https://cdn.example/v.mp4", name: "Vídeo" });
    const video = screen.getByRole("dialog").querySelector("video");
    expect(video?.getAttribute("src")).toBe("https://cdn.example/v.mp4");
    expect(video?.hasAttribute("controls")).toBe(true);
  });

  it("pdf: abre o documento num iframe", () => {
    renderViewer({ kind: "pdf", src: "https://cdn.example/n.pdf", name: "nota.pdf" });
    const iframe = screen.getByTitle("nota.pdf");
    expect(iframe.tagName).toBe("IFRAME");
    expect(iframe.getAttribute("src")).toBe("https://cdn.example/n.pdf");
  });

  it("arquivo sem prévia: avisa e não tenta mostrar", () => {
    renderViewer({ kind: "file", src: "https://cdn.example/a.psd", name: "arte.psd" });
    expect(screen.getByText("Sem pré-visualização para este tipo de arquivo")).toBeTruthy();
    const dialog = screen.getByRole("dialog");
    expect(dialog.querySelector("iframe, img, video")).toBeNull();
  });

  it("Baixar aponta para o link de download com o nome do arquivo", () => {
    renderViewer();
    const link = screen.getAllByRole("link", { name: /Baixar/ })[0];
    expect(link.getAttribute("href")).toBe("https://cdn.example/foto.jpg?download=foto.jpg");
    expect(link.getAttribute("download")).toBe("foto.jpg");
  });

  it("fecha no X", () => {
    const { onClose } = renderViewer();
    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fecha com Esc", () => {
    const { onClose } = renderViewer();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fecha no clique do fundo escuro, mas não no clique do conteúdo", () => {
    const { onClose } = renderViewer();
    fireEvent.click(screen.getByRole("dialog").querySelector("img")!);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("media-viewer-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npx vitest run src/components/conversas/media-viewer.test.tsx`
Expected: FAIL. Mensagem: `Failed to resolve import "./media-viewer"`.

- [ ] **Step 3: Implementar**

```tsx
"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";

export type MediaViewerKind = "image" | "video" | "pdf" | "file";

interface MediaViewerProps {
  kind: MediaViewerKind;
  src: string;
  name: string;
  downloadHref: string;
  onClose: () => void;
}

/** Janela por cima do chat para ver um anexo sem baixar (e baixar, se quiser). */
export function MediaViewer({ kind, src, name, downloadHref, onClose }: MediaViewerProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const downloadLink = (
    <a
      href={downloadHref}
      download={name}
      className="rounded-md bg-white/10 px-3 py-1.5 text-[13px] font-medium text-white hover:bg-white/20"
    >
      Baixar
    </a>
  );

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={name}
      className="fixed inset-0 z-[100] flex flex-col bg-black/85"
    >
      <div className="flex items-center gap-3 px-4 py-3 text-white">
        <span className="min-w-0 flex-1 truncate text-[14px]">{name}</span>
        {downloadLink}
        <button
          type="button"
          aria-label="Fechar"
          onClick={onClose}
          className="rounded-md p-1.5 text-white/80 hover:bg-white/10 hover:text-white"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div
        data-testid="media-viewer-backdrop"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
        className="flex min-h-0 flex-1 items-center justify-center p-4 pt-0"
      >
        {kind === "image" ? (
          <img src={src} alt={name} className="max-h-full max-w-full object-contain" />
        ) : kind === "video" ? (
          <video src={src} controls autoPlay className="max-h-full max-w-full" />
        ) : kind === "pdf" ? (
          <iframe src={src} title={name} className="h-full w-full max-w-5xl rounded-md bg-white" />
        ) : (
          <div className="flex flex-col items-center gap-4 rounded-md bg-white/5 px-8 py-10 text-center text-white">
            <span className="text-[14px]">Sem pré-visualização para este tipo de arquivo</span>
            {downloadLink}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `npx vitest run src/components/conversas/media-viewer.test.tsx`
Expected: PASS (9 testes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/conversas/media-viewer.tsx frontend/src/components/conversas/media-viewer.test.tsx
git commit -m "feat(anexos-conversas): janela de pre-visualizacao do anexo"
```

---

### Task 3: Ligar no `message-bubble.tsx` (depende das Tasks 1 e 2)

**Files:**
- Modify: `frontend/src/components/conversas/message-bubble.tsx`. Mexer nos ramos `isAudio`, `isVideo`, `isImage` e `isDocument` (perto das linhas 460-555) e no estado do componente (perto da linha 289).
- Test: `frontend/src/components/conversas/message-bubble.test.tsx` (acrescentar um `describe` no fim)

- [ ] **Step 1: Escrever o teste que falha** (acrescentar ao fim do arquivo de teste existente. `renderBubble`, `screen` e `fireEvent` já estão importados/definidos lá)

```tsx
describe("MessageBubble — pré-visualizar anexo", () => {
  const STORAGE = "https://supabase.canastrainteligencia.com/storage/v1/object/public/media/x";

  it("clicar na imagem abre a janela com a imagem e Baixar", () => {
    renderBubble({ message_type: "image", media_url: `${STORAGE}/foto.jpg` });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ampliar imagem" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.querySelector("img")?.getAttribute("src")).toBe(`${STORAGE}/foto.jpg`);
    const baixar = screen.getAllByRole("link", { name: "Baixar" })[0];
    expect(new URL(baixar.getAttribute("href")!).searchParams.get("download")).toBe("imagem.jpg");
  });

  it("vídeo tem botão de ampliar que abre o player na janela", () => {
    renderBubble({ message_type: "video", media_url: `${STORAGE}/v.mp4` });
    fireEvent.click(screen.getByRole("button", { name: "Ampliar vídeo" }));
    expect(screen.getByRole("dialog").querySelector("video")).toBeTruthy();
  });

  it("documento PDF: Abrir mostra o PDF na janela; Baixar baixa com o nome", () => {
    renderBubble({
      message_type: "document",
      media_url: `${STORAGE}/n.pdf`,
      document_name: "Pedido Café.pdf",
    });
    const baixar = screen.getByRole("link", { name: "Baixar" });
    expect(new URL(baixar.getAttribute("href")!).searchParams.get("download")).toBe("Pedido Café.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Abrir" }));
    expect(screen.getByTitle("Pedido Café.pdf").tagName).toBe("IFRAME");
  });

  it("documento sem document_name usa o content como nome e abre como PDF", () => {
    renderBubble({ message_type: "document", media_url: `${STORAGE}/n.pdf`, content: "boleto.pdf" });
    fireEvent.click(screen.getByRole("button", { name: "Abrir" }));
    expect(screen.getByTitle("boleto.pdf").tagName).toBe("IFRAME");
  });

  it("documento .psd abre a janela sem prévia", () => {
    renderBubble({ message_type: "document", media_url: `${STORAGE}/a.psd`, document_name: "arte.psd" });
    fireEvent.click(screen.getByRole("button", { name: "Abrir" }));
    expect(screen.getByText("Sem pré-visualização para este tipo de arquivo")).toBeTruthy();
  });

  it("documento legado (media_id) baixa pelo proxy com download=1", () => {
    renderBubble({ message_type: "document", media_url: "123456", document_name: "nota.pdf" });
    const href = screen.getByRole("link", { name: "Baixar" }).getAttribute("href")!;
    const u = new URL(href, "http://x");
    expect(u.pathname).toBe("/api/media");
    expect(u.searchParams.get("download")).toBe("1");
    expect(u.searchParams.get("filename")).toBe("nota.pdf");
  });

  it("áudio continua tocando no balão e ganha Baixar", () => {
    const { container } = renderBubble({ message_type: "audio", media_url: `${STORAGE}/a.ogg` });
    expect(container.querySelector("audio")).toBeTruthy();
    const baixar = screen.getByRole("link", { name: "Baixar" });
    expect(new URL(baixar.getAttribute("href")!).searchParams.get("download")).toBe("audio.ogg");
  });

  it("Esc fecha a janela", () => {
    renderBubble({ message_type: "image", media_url: `${STORAGE}/foto.jpg` });
    fireEvent.click(screen.getByRole("button", { name: "Ampliar imagem" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `npx vitest run src/components/conversas/message-bubble.test.tsx`
Expected: os testes novos FALHAM com "Unable to find an accessible element with the role "button" and name "Ampliar imagem"" (e equivalentes). Os testes antigos continuam passando.

- [ ] **Step 3: Implementar**

3a. Imports, no topo do arquivo, junto dos outros `@/lib`:

```tsx
import { mediaDownloadHref, mediaFileName, documentPreviewKind } from "@/lib/media-download";
import { MediaViewer, type MediaViewerKind } from "./media-viewer";
```

3b. Estado, logo depois de `const [audioError, setAudioError] = useState(false);`:

```tsx
  const [viewerOpen, setViewerOpen] = useState(false);
```

3c. Depois de `const mediaExpired = isMediaExpired(message);`, monte o que a janela precisa:

```tsx
  // Pré-visualização do anexo (janela por cima do chat) + link de download com nome.
  const docName = message.document_name || message.content || "Documento";
  const attachment: { kind: MediaViewerKind; name: string; fileName: string } | null = isImage
    ? { kind: "image", name: "Imagem", fileName: mediaFileName("image", null) }
    : isVideo
      ? { kind: "video", name: "Vídeo", fileName: mediaFileName("video", null) }
      : isDocument
        ? {
            kind: documentPreviewKind(message.document_name || message.content),
            name: docName,
            fileName: mediaFileName("document", message.document_name || message.content),
          }
        : isAudio
          ? { kind: "file", name: "Áudio", fileName: mediaFileName("audio", null) }
          : null;
  const downloadHref = mediaSrc && attachment ? mediaDownloadHref(mediaSrc, attachment.fileName) : null;
```

3d. Ramo de áudio: troque o `<audio …/>` (o ramo não expirado) por:

```tsx
              <div className="flex flex-col">
                <audio
                  controls
                  src={mediaSrc}
                  className="h-10 max-w-[240px]"
                  onError={() => setAudioError(true)}
                />
                {downloadHref && (
                  <a
                    href={downloadHref}
                    download={attachment?.fileName}
                    className="text-[11px] underline opacity-70 hover:opacity-100 mt-0.5 self-start"
                  >
                    Baixar
                  </a>
                )}
              </div>
```

3e. Ramo de vídeo: troque o `<video …/>` (o ramo não expirado) por:

```tsx
              <div className="relative">
                <video
                  controls
                  src={mediaSrc}
                  className="max-w-[320px] max-h-[400px] rounded-[4px] block"
                  onError={() => setVideoError(true)}
                />
                <button
                  type="button"
                  aria-label="Ampliar vídeo"
                  title="Ampliar"
                  onClick={() => setViewerOpen(true)}
                  className="absolute top-1.5 right-1.5 rounded-md bg-black/50 p-1 text-white hover:bg-black/70"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
                  </svg>
                </button>
              </div>
```

3f. Ramo de imagem: troque o `<img …/>` (o ramo não expirado) por:

```tsx
              <button
                type="button"
                aria-label="Ampliar imagem"
                onClick={() => setViewerOpen(true)}
                className="block cursor-zoom-in p-0"
              >
                <img
                  src={mediaSrc}
                  alt="Imagem enviada"
                  className="max-w-[240px] max-h-[320px] object-contain rounded-[4px] block"
                  onError={() => setImgError(true)}
                />
              </button>
```

3g. Ramo de documento: substitua o IIFE inteiro (`(() => { const docName = …; const downloadHref = …; return (…); })()`) por:

```tsx
          <div className="flex items-center gap-2 py-1">
            <svg className="w-5 h-5 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
            </svg>
            <div className="flex flex-col min-w-0">
              <span className="text-[13px] truncate max-w-[180px]">{docName}</span>
              {downloadHref && mediaExpired ? (
                <span className="text-[11px] opacity-60 mt-0.5">Arquivo expirado</span>
              ) : downloadHref && (
                <span className="flex items-center gap-2 text-[11px] mt-0.5">
                  <button
                    type="button"
                    onClick={() => setViewerOpen(true)}
                    className="underline opacity-70 hover:opacity-100"
                  >
                    Abrir
                  </button>
                  <a
                    href={downloadHref}
                    download={attachment?.fileName}
                    className="underline opacity-70 hover:opacity-100"
                  >
                    Baixar
                  </a>
                </span>
              )}
            </div>
          </div>
```

3h. Renderizar a janela: logo antes do `</div>` que fecha o JSX retornado pelo ramo principal do `MessageBubbleImpl` (o mesmo que contém os ramos de mídia), acrescente:

```tsx
      {viewerOpen && mediaSrc && downloadHref && attachment && (
        <MediaViewer
          kind={attachment.kind}
          src={mediaSrc}
          name={attachment.name}
          downloadHref={downloadHref}
          onClose={() => setViewerOpen(false)}
        />
      )}
```

(O `MediaViewer` usa portal em `document.body`, então a posição no JSX não afeta o layout.)

- [ ] **Step 4: Rodar e ver passar**

Run: `npx vitest run src/components/conversas/message-bubble.test.tsx`
Expected: PASS, os novos e os antigos. O antigo "documento com media_id legado antigo mantém o nome e troca Baixar pelo aviso" continua verde.

- [ ] **Step 5: Suíte, lint e build**

Run: `npm test && npm run lint && npm run build`
Expected: tudo verde. Se o lint geral já falhar em master, rodar `npx eslint` só nos 5 arquivos tocados: nenhum erro novo neles.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/conversas/message-bubble.tsx frontend/src/components/conversas/message-bubble.test.tsx
git commit -m "feat(anexos-conversas): anexos do chat abrem na janela de previa, com Baixar"
```

---

### Task 4: Teste na tela real (modo teste) e prints

- [ ] `npm run dev` em `frontend/` do worktree (usa o `.env.local` do frontend, que aponta para o Supabase de produção; só leitura).
- [ ] Achar via SELECT uma conversa com imagem, PDF (Storage) e vídeo recentes. Abrir `http://localhost:3000/conversas` nela.
- [ ] Conferir: a imagem amplia, o PDF abre no iframe, o Baixar devolve `content-disposition: attachment` com o nome certo (`curl -D -` no href) e o Esc fecha.
- [ ] Prints em `ValerIA/.claude/worktrees/prints/agente-3a6de8d1/` (imagem ampliada, PDF na janela, balão de documento) e olhar cada PNG.
