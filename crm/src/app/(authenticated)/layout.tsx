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
    <div className="flex h-screen">
      <Sidebar />
      <main
        className={`flex-1 ${
          isConversas ? "overflow-hidden" : "bg-gray-50 p-6 overflow-auto"
        }`}
      >
        {children}
      </main>
    </div>
  );
}
