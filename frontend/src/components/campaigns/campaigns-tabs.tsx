"use client";

import { useState } from "react";
import type { Broadcast, Cadence } from "@/lib/types";
import { BroadcastList } from "./broadcast-list";
import { CadenceList } from "./cadence-list";

interface CampaignsTabsProps {
  broadcasts: Broadcast[];
  cadences: Cadence[];
  onRefreshBroadcasts: () => void;
}

export function CampaignsTabs({ broadcasts, cadences, onRefreshBroadcasts }: CampaignsTabsProps) {
  const [tab, setTab] = useState<"broadcasts" | "cadences">("broadcasts");

  return (
    <div>
      <div className="flex border-b border-[#dedbd6] mb-5">
        <button
          onClick={() => setTab("broadcasts")}
          className={tab === "broadcasts"
            ? "border-b-2 border-[#111111] text-[#111111] px-4 py-2 text-[14px] font-normal"
            : "border-b-2 border-transparent text-[#7b7b78] px-4 py-2 text-[14px] font-normal hover:text-[#111111] transition-colors"}
        >
          Disparos ({broadcasts.length})
        </button>
        <button
          onClick={() => setTab("cadences")}
          className={tab === "cadences"
            ? "border-b-2 border-[#111111] text-[#111111] px-4 py-2 text-[14px] font-normal"
            : "border-b-2 border-transparent text-[#7b7b78] px-4 py-2 text-[14px] font-normal hover:text-[#111111] transition-colors"}
        >
          Cadencias ({cadences.length})
        </button>
      </div>

      {tab === "broadcasts" ? (
        <BroadcastList broadcasts={broadcasts} onRefresh={onRefreshBroadcasts} />
      ) : (
        <CadenceList cadences={cadences} />
      )}
    </div>
  );
}
