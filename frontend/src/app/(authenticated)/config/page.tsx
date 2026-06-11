"use client";

import { useState, useEffect } from "react";
import { TagsTab } from "@/components/config/tags-tab";
import { PricingTab } from "@/components/config/pricing-tab";
import { LpWebhookTab } from "@/components/config/lp-webhook-tab";
import { SlaTab } from "@/components/config/sla-tab";
import { createClient } from "@/lib/supabase/client";

const BASE_TABS = [
  { key: "tags", label: "Tags" },
  { key: "pricing", label: "Precos IA" },
  { key: "lp-webhook", label: "Landing Pages" },
] as const;

type TabKey = "tags" | "pricing" | "lp-webhook" | "sla";

export default function ConfigPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("tags");
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => {
      setIsAdmin(data.user?.app_metadata?.role === "admin");
    });
  }, []);

  const tabs: { key: TabKey; label: string }[] = [
    ...BASE_TABS,
    ...(isAdmin ? [{ key: "sla" as const, label: "SLA" }] : []),
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
        <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">Configurações</h1>
        <p className="text-[14px] text-[#7b7b78] mt-0.5">Preferências e integrações</p>
      </div>

      <div className="px-4 md:px-8 py-4 md:py-8 overflow-auto flex-1 bg-[#faf9f6]">
        <div className="max-w-3xl">
          <div className="flex border-b border-[#dedbd6] mb-8">
            {tabs.map((tab) => (
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
          {activeTab === "lp-webhook" && <LpWebhookTab />}
          {activeTab === "sla" && isAdmin && <SlaTab />}
        </div>
      </div>
    </div>
  );
}
