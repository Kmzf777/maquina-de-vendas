"use client";

import type { QuickReply } from "@/lib/types";

interface Props {
  items: QuickReply[];
  highlightedIndex: number;
  onSelect: (item: QuickReply) => void;
  onCreate: () => void;
  onHighlight: (index: number) => void;
}

export function QuickReplyMenu({ items, highlightedIndex, onSelect, onCreate, onHighlight }: Props) {
  return (
    <div className="absolute bottom-full left-3 right-3 mb-2 z-20 max-h-56 overflow-y-auto bg-white border border-[#dedbd6] rounded-[6px] shadow-lg">
      {items.length === 0 ? (
        <div className="px-3 py-3 text-[13px] text-[#7b7b78]">Nenhuma resposta rápida encontrada.</div>
      ) : (
        <ul className="py-1">
          {items.map((item, i) => (
            <li key={item.id}>
              <button
                type="button"
                onMouseDown={(e) => { e.preventDefault(); onSelect(item); }}
                onMouseEnter={() => onHighlight(i)}
                className={
                  "w-full text-left px-3 py-2 transition-colors " +
                  (i === highlightedIndex ? "bg-[#f5f3f0]" : "bg-transparent hover:bg-[#faf9f6]")
                }
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[14px] text-[#111111] font-normal truncate">{item.title}</span>
                  {item.shortcut && (
                    <span className="text-[12px] text-[#7b7b78] flex-shrink-0">/{item.shortcut}</span>
                  )}
                </div>
                <p className="text-[12px] text-[#7b7b78] truncate">{item.content}</p>
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        onMouseDown={(e) => { e.preventDefault(); onCreate(); }}
        className="w-full text-left px-3 py-2 border-t border-[#dedbd6] text-[14px] text-[#111111] hover:bg-[#faf9f6] transition-colors"
      >
        + Criar mensagem
      </button>
    </div>
  );
}
