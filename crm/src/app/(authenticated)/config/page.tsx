"use client";

import { useState } from "react";
import { WhatsAppTab } from "@/components/config/whatsapp-tab";
import { TagsTab } from "@/components/config/tags-tab";
import { PasswordTab } from "@/components/config/password-tab";

const TABS = [
  { key: "whatsapp", label: "WhatsApp" },
  { key: "tags", label: "Tags" },
  { key: "senha", label: "Senha" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ConfigPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("whatsapp");

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Configuracoes</h1>

      <div className="border-b border-gray-200 mb-6">
        <nav className="flex gap-0">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? "border-violet-600 text-violet-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {activeTab === "whatsapp" && <WhatsAppTab />}
      {activeTab === "tags" && <TagsTab />}
      {activeTab === "senha" && <PasswordTab />}
    </div>
  );
}
