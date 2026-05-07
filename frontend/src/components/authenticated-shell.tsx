"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { NotificationToast } from "@/components/notification-toast";

export function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isConversas = pathname === "/conversas";
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    document.body.style.overflow = drawerOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [drawerOpen]);

  useEffect(() => {
    if (!drawerOpen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawerOpen(false); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [drawerOpen]);

  return (
    <div className="flex h-svh bg-[#faf9f6] overflow-x-hidden">
      {/* Desktop sidebar — hidden on mobile */}
      <div className="hidden md:flex flex-shrink-0">
        <Sidebar />
      </div>

      {/* Mobile top bar — hidden on desktop */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-30 h-14 bg-[#f0ede8] border-b border-[#dedbd6] flex items-center px-4 gap-3 flex-shrink-0">
        <button
          onClick={() => setDrawerOpen(true)}
          className="w-8 h-8 flex items-center justify-center rounded-[4px] text-[#313130] hover:bg-[#dedbd6]/60 transition-colors"
          aria-label="Abrir menu"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
          </svg>
        </button>
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-[4px] bg-[#111111] flex items-center justify-center">
            <span className="text-[10px] font-medium text-white">V</span>
          </div>
          <span className="text-[14px] font-medium text-[#111111] tracking-tight">
            ValerIA<span className="text-[#ff5600] ml-0.5">·</span>
          </span>
        </div>
      </div>

      {/* Mobile drawer overlay */}
      {drawerOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="relative w-[260px] h-full shadow-xl">
            <Sidebar onClose={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}

      <main
        className={`flex-1 relative flex flex-col pt-14 md:pt-0 ${
          isConversas ? "overflow-hidden" : "overflow-auto"
        }`}
      >
        {children}
      </main>
      <NotificationToast />
    </div>
  );
}

