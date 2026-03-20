export interface PlotWorkspaceActionState {
  selectingFiles: boolean;
  sendingMessage: boolean;
  finalizing: boolean;
}

export type PlotWorkspaceActionStateById = Record<string, PlotWorkspaceActionState>;

const EMPTY_PLOT_WORKSPACE_ACTION_STATE: PlotWorkspaceActionState = {
  selectingFiles: false,
  sendingMessage: false,
  finalizing: false,
};

export function getPlotWorkspaceActionState(
  stateById: PlotWorkspaceActionStateById,
  workspaceId: string | null | undefined,
): PlotWorkspaceActionState {
  if (!workspaceId) {
    return EMPTY_PLOT_WORKSPACE_ACTION_STATE;
  }
  return stateById[workspaceId] ?? EMPTY_PLOT_WORKSPACE_ACTION_STATE;
}

export function isPlotWorkspaceBusy(state: PlotWorkspaceActionState): boolean {
  return state.selectingFiles || state.sendingMessage || state.finalizing;
}

export function updatePlotWorkspaceActionState(
  stateById: PlotWorkspaceActionStateById,
  workspaceId: string | null | undefined,
  patch: Partial<PlotWorkspaceActionState>,
): PlotWorkspaceActionStateById {
  if (!workspaceId) {
    return stateById;
  }

  const nextState = {
    ...getPlotWorkspaceActionState(stateById, workspaceId),
    ...patch,
  };

  if (!isPlotWorkspaceBusy(nextState)) {
    const { [workspaceId]: _removed, ...remaining } = stateById;
    return remaining;
  }

  return {
    ...stateById,
    [workspaceId]: nextState,
  };
}
