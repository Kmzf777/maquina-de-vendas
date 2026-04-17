"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";

export function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isConversas = pathname === "/conversas";

  return (
    <div className="flex h-screen bg-[#faf9f6]">
      <Sidebar />
      <main
        className={`flex-1 relative ${
          isConversas ? "overflow-hidden" : "p-8 overflow-auto"
        }`}
      >
        {children}
      </main>
    </div>
  );
}
