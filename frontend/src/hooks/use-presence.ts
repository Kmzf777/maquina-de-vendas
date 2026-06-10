"use client";

import { useEffect, useState, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";

export interface KnownUser {
  email: string;
  name: string;
  role: "admin" | "vendedor";
}

export const KNOWN_USERS: KnownUser[] = [
  { email: "arthur@cafecanastra.com", name: "Arthur", role: "vendedor" },
  { email: "rafael@cafecanastra.com", name: "Rafael", role: "admin"    },
  { email: "kelwin@cafecanastra.com", name: "Kelwin", role: "admin"    },
  { email: "joao@cafecanastra.com",   name: "João",   role: "vendedor" },
];

export interface UserPresenceState {
  email: string;
  name: string;
  role: "admin" | "vendedor";
  /** "online" = connected + visible, "ausente" = connected but tab hidden, "offline" = not in channel */
  status: "online" | "ausente" | "offline";
  page: string | null;
}

type PresencePayload = {
  email: string;
  name: string;
  role: string;
  page: string;
  status: "online" | "ausente";
};

const STATUS_ORDER: Record<UserPresenceState["status"], number> = {
  online: 0,
  ausente: 1,
  offline: 2,
};

function buildUserList(
  presenceState: Record<string, PresencePayload[]>
): UserPresenceState[] {
  // Build a map of email -> most recent presence entry
  const onlineMap = new Map<string, PresencePayload>();
  for (const entries of Object.values(presenceState)) {
    for (const entry of entries) {
      if (entry.email) {
        // Later entries in the array are newer; keep the last one
        onlineMap.set(entry.email, entry);
      }
    }
  }

  const users: UserPresenceState[] = KNOWN_USERS.map((known) => {
    const presence = onlineMap.get(known.email);
    if (presence) {
      return {
        email: known.email,
        name: known.name,
        role: known.role,
        status: presence.status === "ausente" ? "ausente" : "online",
        page: presence.page ?? null,
      };
    }
    return {
      email: known.email,
      name: known.name,
      role: known.role,
      status: "offline",
      page: null,
    };
  });

  return users.sort(
    (a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status]
  );
}

/**
 * Reads the `crm-presence` channel and returns a merged list of all known
 * users with their current presence status. Offline users are filled from
 * KNOWN_USERS. Always returns 4 entries.
 */
export function usePresence() {
  const supabase = useMemo(() => createClient(), []);
  const [users, setUsers] = useState<UserPresenceState[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const channel = supabase.channel("crm-presence");

    channel
      .on("presence", { event: "sync" }, () => {
        const state = channel.presenceState() as Record<string, PresencePayload[]>;
        setUsers(buildUserList(state));
        setLoading(false);
      })
      .on("presence", { event: "join" }, () => {
        const state = channel.presenceState() as Record<string, PresencePayload[]>;
        setUsers(buildUserList(state));
        setLoading(false);
      })
      .on("presence", { event: "leave" }, () => {
        const state = channel.presenceState() as Record<string, PresencePayload[]>;
        setUsers(buildUserList(state));
      })
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  return { users, loading };
}
