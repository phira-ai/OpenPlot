import type { Branch } from "../types";
import { fetchJSON } from "./client";

export function checkoutVersion(versionId: string, branchId?: string) {
  return fetchJSON("/api/checkout", {
    method: "POST",
    body: JSON.stringify({
      version_id: versionId,
      branch_id: branchId,
    }),
  });
}

export function checkoutBranch(branchId: string) {
  return fetchJSON(`/api/branches/${branchId}/checkout`, {
    method: "POST",
  });
}

export function renameBranch(branchId: string, name: string) {
  return fetchJSON<{
    status: string;
    branch: Branch;
    active_branch_id: string | null;
  }>(`/api/branches/${encodeURIComponent(branchId)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}
