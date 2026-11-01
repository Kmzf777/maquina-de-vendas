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
