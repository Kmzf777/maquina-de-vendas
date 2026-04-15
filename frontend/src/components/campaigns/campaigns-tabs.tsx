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
      <div className="flex gap-1 mb-5">
        <button
          onClick={() => setTab("broadcasts")}
          className={`px-4 py-2 rounded-lg text-[13px] font-medium transition-colors ${
            tab === "broadcasts" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
          }`}
        >
          Disparos ({broadcasts.length})
        </button>
        <button
          onClick={() => setTab("cadences")}
          className={`px-4 py-2 rounded-lg text-[13px] font-medium transition-colors ${
            tab === "cadences" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] hover:bg-[#f6f7ed]"
          }`}
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
