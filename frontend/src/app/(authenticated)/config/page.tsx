"use client";

import { useState } from "react";
import { TagsTab } from "@/components/config/tags-tab";
import { PricingTab } from "@/components/config/pricing-tab";

const TABS = [
  { key: "tags", label: "Tags" },
  { key: "pricing", label: "Precos IA" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ConfigPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("tags");

  return (
    <div className="max-w-3xl">
      <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111] mb-8">
        Configuracoes
      </h1>

      <div className="flex border-b border-[#dedbd6] mb-8">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={activeTab === tab.key
              ? "border-b-2 border-[#111111] text-[#111111] px-4 py-2 text-[14px] font-normal"
              : "border-b-2 border-transparent text-[#7b7b78] px-4 py-2 text-[14px] font-normal hover:text-[#111111] transition-colors"}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "tags" && <TagsTab />}
      {activeTab === "pricing" && <PricingTab />}
    </div>
  );
}
