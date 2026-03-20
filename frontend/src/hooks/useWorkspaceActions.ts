import { useCallback, useState } from "react";

import { asErrorMessage } from "@/lib/errors";

interface UseWorkspaceActionsOptions {
  activeWorkspaceId: string | null;
  createNewSession: () => Promise<unknown>;
  activateSession: (sessionId: string) => Promise<unknown>;
  renameWorkspace: (sessionId: string, workspaceName: string) => Promise<unknown>;
  deleteWorkspace: (sessionId: string) => Promise<unknown>;
  clearFocusedAnnotation: () => void;
  onError?: (message: string) => void;
}

export function useWorkspaceActions({
  activeWorkspaceId,
  createNewSession,
  activateSession,
  renameWorkspace,
  deleteWorkspace,
  clearFocusedAnnotation,
  onError,
}: UseWorkspaceActionsOptions) {
  const [sessionActionPending, setSessionActionPending] = useState(false);
  const [sessionActionError, setSessionActionError] = useState<string | null>(null);

  const handleCreateSession = useCallback(async () => {
    setSessionActionPending(true);
    setSessionActionError(null);
    clearFocusedAnnotation();

    try {
      await createNewSession();
    } catch (err: unknown) {
      const message = asErrorMessage(err, "Failed to create a new workspace");
      setSessionActionError(message);
      onError?.(message);
    } finally {
      setSessionActionPending(false);
    }
  }, [clearFocusedAnnotation, createNewSession, onError]);

  const handleActivateSession = useCallback(
    async (sessionId: string) => {
      if (activeWorkspaceId === sessionId) {
        return;
      }

      setSessionActionPending(true);
      setSessionActionError(null);
      clearFocusedAnnotation();

      try {
        await activateSession(sessionId);
      } catch (err: unknown) {
        const message = asErrorMessage(err, "Failed to open workspace");
        setSessionActionError(message);
        onError?.(message);
      } finally {
        setSessionActionPending(false);
      }
    },
    [activeWorkspaceId, activateSession, clearFocusedAnnotation, onError],
  );

  const handleRenameWorkspace = useCallback(
    async (sessionId: string, workspaceName: string) => {
      setSessionActionPending(true);
      setSessionActionError(null);

      try {
        await renameWorkspace(sessionId, workspaceName);
      } catch (err: unknown) {
        const message = asErrorMessage(err, "Failed to rename workspace");
        setSessionActionError(message);
        onError?.(message);
      } finally {
        setSessionActionPending(false);
      }
    },
    [onError, renameWorkspace],
  );

  const handleDeleteWorkspace = useCallback(
    async (sessionId: string) => {
      setSessionActionPending(true);
      setSessionActionError(null);
      clearFocusedAnnotation();

      try {
        await deleteWorkspace(sessionId);
      } catch (err: unknown) {
        const message = asErrorMessage(err, "Failed to delete workspace");
        setSessionActionError(message);
        onError?.(message);
      } finally {
        setSessionActionPending(false);
      }
    },
    [clearFocusedAnnotation, deleteWorkspace, onError],
  );

  return {
    sessionActionPending,
    sessionActionError,
    handleCreateSession,
    handleActivateSession,
    handleRenameWorkspace,
    handleDeleteWorkspace,
  };
}
