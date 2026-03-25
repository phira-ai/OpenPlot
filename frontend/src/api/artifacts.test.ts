import { describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  fetchResponse: vi.fn(),
}));

import { fetchResponse } from "./client";
import { downloadAnnotationArtifact, downloadPlotModeArtifact } from "./artifacts";

const fetchResponseMock = vi.mocked(fetchResponse);

describe("artifacts api", () => {
  it("delegates raw artifact downloads through the shared client transport", async () => {
    const response = { ok: true } as Response;
    fetchResponseMock.mockResolvedValue(response);

    await downloadAnnotationArtifact("annotation-1");
    await downloadPlotModeArtifact("plot-a");

    expect(fetchResponseMock).toHaveBeenNthCalledWith(1, "/api/annotations/annotation-1/export");
    expect(fetchResponseMock).toHaveBeenNthCalledWith(2, "/api/plot-mode/export?workspace_id=plot-a");
  });
});
