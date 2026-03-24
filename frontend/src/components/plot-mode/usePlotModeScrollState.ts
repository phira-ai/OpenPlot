import { useEffect, useRef } from "react";

import type { PlotModeChatMessage } from "../../types";
import { getPlotChatScrollIntent } from "@/lib/plotModeUi";

const PLOT_CHAT_BOTTOM_THRESHOLD_PX = 80;

function isPlotChatNearBottom(container: HTMLDivElement): boolean {
  return (
    container.scrollHeight - container.scrollTop - container.clientHeight <=
    PLOT_CHAT_BOTTOM_THRESHOLD_PX
  );
}

export function usePlotModeScrollState({
  workspaceId,
  messages,
}: {
  workspaceId: string | null;
  messages: PlotModeChatMessage[];
}) {
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const pendingInitialRestoreRef = useRef(true);
  const pendingWorkspaceRestoreRef = useRef<string | null>(null);
  const previousMessagesRef = useRef(
    messages.map((entry) => ({
      id: entry.id,
      role: entry.role,
      content: entry.content,
    })),
  );
  const previousWorkspaceIdRef = useRef<string | null>(workspaceId);
  const userNearBottomRef = useRef(true);

  useEffect(() => {
    if (!messagesRef.current) {
      return;
    }

    const container = messagesRef.current;
    const updateUserNearBottom = () => {
      userNearBottomRef.current = isPlotChatNearBottom(container);
    };

    updateUserNearBottom();
    container.addEventListener("scroll", updateUserNearBottom, { passive: true });

    return () => {
      container.removeEventListener("scroll", updateUserNearBottom);
    };
  }, []);

  useEffect(() => {
    if (previousWorkspaceIdRef.current !== workspaceId) {
      pendingWorkspaceRestoreRef.current = workspaceId;
    }
  }, [workspaceId]);

  useEffect(() => {
    if (!messagesRef.current) {
      return;
    }

    const previousWorkspaceId = previousWorkspaceIdRef.current;
    const previousMessages = previousMessagesRef.current;

    if (pendingInitialRestoreRef.current) {
      previousWorkspaceIdRef.current = workspaceId;
      previousMessagesRef.current = messages.map((entry) => ({
        id: entry.id,
        role: entry.role,
        content: entry.content,
      }));

      if (messages.length === 0) {
        return;
      }

      const container = messagesRef.current;
      const scrollFrame = window.requestAnimationFrame(() => {
        container.scrollTo({ top: container.scrollHeight });
        pendingInitialRestoreRef.current = false;
        userNearBottomRef.current = true;
      });

      return () => {
        window.cancelAnimationFrame(scrollFrame);
      };
    }

    const scrollIntent = getPlotChatScrollIntent({
      previousWorkspaceId,
      nextWorkspaceId: workspaceId,
      pendingRestoreWorkspaceId: pendingWorkspaceRestoreRef.current,
      previousMessages,
      nextMessages: messages,
      userNearBottom: userNearBottomRef.current,
    });

    previousWorkspaceIdRef.current = workspaceId;
    previousMessagesRef.current = messages.map((entry) => ({
      id: entry.id,
      role: entry.role,
      content: entry.content,
    }));

    if (scrollIntent === "preserve-position") {
      return;
    }

    const container = messagesRef.current;
    const scrollFrame = window.requestAnimationFrame(() => {
      container.scrollTo({ top: container.scrollHeight });
      pendingWorkspaceRestoreRef.current = null;
      userNearBottomRef.current = true;
    });

    return () => {
      window.cancelAnimationFrame(scrollFrame);
    };
  }, [messages, workspaceId]);

  return { messagesRef };
}
