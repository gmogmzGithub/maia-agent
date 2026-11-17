"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { api, session } from "@/shared/lib/api";
import { ConversationSession } from "./session";

const storageKey = "maia-conversation";

/** Browser adapter. Session policy is independent of React, storage and real timers. */
export default function useConversation() {
  const [controller] = useState(() => new ConversationSession({
    request: api, session,
    saved: {
      get: () => localStorage.getItem(storageKey),
      set: (id) => localStorage.setItem(storageKey, id),
      clear: () => localStorage.removeItem(storageKey),
    },
    id: () => crypto.randomUUID(), schedule: setTimeout, cancel: clearTimeout,
  }));
  const state = useSyncExternalStore(controller.subscribe, controller.snapshot, controller.snapshot);
  useEffect(() => {
    const propertyId = new URLSearchParams(window.location.search).get("propiedad");
    void controller.start(propertyId, () => {
      const url = new URL(window.location.href);
      url.searchParams.delete("propiedad");
      window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    });
    return () => controller.stop();
  }, [controller]);
  return { ...state, sendMessage: controller.send, setText: controller.setText,
    updateConversation: controller.update, newSearch: controller.newSearch,
    retry: controller.retry, refresh: controller.refreshAfterError };
}
