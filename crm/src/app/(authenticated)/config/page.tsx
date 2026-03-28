"use client";

import { useState } from "react";
import { WhatsAppTab } from "@/components/config/whatsapp-tab";
import { TagsTab } from "@/components/config/tags-tab";

const TABS = [
  { key: "whatsapp", label: "WhatsApp" },
  { key: "tags", label: "Tags" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ConfigPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("whatsapp");

  return (
    <div className="max-w-3xl">
      <h1 className="text-[28px] font-bold text-[#1f1f1f] mb-8">Configuracoes</h1>

      <div className="mb-8">
        <nav className="inline-flex gap-1 p-1 bg-[#f6f7ed] rounded-xl">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-5 py-2 text-[13px] font-medium rounded-lg transition-all ${
                activeTab === tab.key
                  ? "bg-[#1f1f1f] text-white shadow-sm"
                  : "text-[#5f6368] hover:text-[#1f1f1f] hover:bg-white/60"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {activeTab === "whatsapp" && <WhatsAppTab />}
      {activeTab === "tags" && <TagsTab />}
    </div>
  );
}
