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
