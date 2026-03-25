import { fetchResponse } from "./client";

export function downloadAnnotationArtifact(annotationId: string) {
  return fetchResponse(`/api/annotations/${annotationId}/export`);
}

export function downloadPlotModeArtifact(workspaceId: string | null) {
  const params = new URLSearchParams();
  if (workspaceId?.trim()) {
    params.set("workspace_id", workspaceId);
  }
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return fetchResponse(`/api/plot-mode/export${suffix}`);
}
