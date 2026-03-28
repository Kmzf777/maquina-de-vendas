"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";

export default function AuthenticatedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const isConversas = pathname === "/conversas";

  return (
    <div className="flex h-screen canvas-texture">
      <Sidebar />
      <main
        className={`flex-1 relative z-10 ${
          isConversas ? "overflow-hidden" : "p-8 overflow-auto"
        }`}
      >
        {children}
      </main>
    </div>
  );
}
