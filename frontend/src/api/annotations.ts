import type { Annotation } from "../types";
import { fetchJSON } from "./client";

export function createAnnotation(annotation: Partial<Annotation>) {
  return fetchJSON<{ status: string; id: string }>("/api/annotations", {
    method: "POST",
    body: JSON.stringify(annotation),
  });
}

export function deleteAnnotation(id: string) {
  return fetchJSON(`/api/annotations/${id}`, { method: "DELETE" });
}

export function updateAnnotation(id: string, updates: Partial<Annotation>) {
  return fetchJSON(`/api/annotations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}
