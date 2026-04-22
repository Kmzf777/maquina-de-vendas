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
    <div className="flex flex-col h-full">
      {/* Page Header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
        <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">Configurações</h1>
        <p className="text-[14px] text-[#7b7b78] mt-0.5">Preferências e integrações</p>
      </div>

      <div className="p-8 overflow-auto flex-1 bg-[#faf9f6]">
        <div className="max-w-3xl">
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
      </div>
    </div>
  );
}
