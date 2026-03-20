// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PlotModePreview from "./PlotModePreview";

class ResizeObserverMock {
  static instances: ResizeObserverMock[] = [];

  callback: ResizeObserverCallback;
  observed: Element[] = [];

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    ResizeObserverMock.instances.push(this);
  }

  observe = (target: Element) => {
    this.observed.push(target);
  };

  disconnect = () => {};
}

describe("PlotModePreview", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    ResizeObserverMock.instances = [];
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
  });

  it("measures the stable viewport container instead of the inner frame", async () => {
    await act(async () => {
      root.render(
        <PlotModePreview
          hasPlot
          imageUrl="/plot.png"
          workspaceId="plot-workspace"
          plotVersion={1}
        />,
      );
    });

    const viewport = container.querySelector<HTMLElement>("[data-plot-preview-viewport]");
    const frame = container.querySelector<HTMLElement>("[data-plot-preview-frame]");
    const image = container.querySelector<HTMLImageElement>('img[alt="Generated plot preview"]');

    expect(viewport).not.toBeNull();
    expect(frame).not.toBeNull();
    expect(image).not.toBeNull();

    vi.spyOn(viewport!, "getBoundingClientRect").mockReturnValue({
      width: 900,
      height: 700,
      top: 0,
      left: 0,
      right: 900,
      bottom: 700,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    vi.spyOn(frame!, "getBoundingClientRect").mockReturnValue({
      width: 500,
      height: 400,
      top: 0,
      left: 0,
      right: 500,
      bottom: 400,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });

    Object.defineProperty(image!, "naturalWidth", { configurable: true, value: 1200 });
    Object.defineProperty(image!, "naturalHeight", { configurable: true, value: 800 });

    await act(async () => {
      image!.dispatchEvent(new Event("load"));
    });

    expect(ResizeObserverMock.instances[0]?.observed).toContain(viewport);
    expect(ResizeObserverMock.instances[0]?.observed).not.toContain(frame);
    expect(image?.style.width).toBe("852px");
    expect(image?.style.height).toBe("568px");
  });

  it("clears stale preview sizing and load errors when switching workspaces", async () => {
    await act(async () => {
      root.render(
        <PlotModePreview
          hasPlot
          imageUrl="/plot-a.png"
          workspaceId="plot-a"
          plotVersion={1}
        />,
      );
    });

    const viewport = container.querySelector<HTMLElement>("[data-plot-preview-viewport]");
    const image = container.querySelector<HTMLImageElement>('img[alt="Generated plot preview"]');
    expect(viewport).not.toBeNull();
    expect(image).not.toBeNull();

    vi.spyOn(viewport!, "getBoundingClientRect").mockReturnValue({
      width: 900,
      height: 700,
      top: 0,
      left: 0,
      right: 900,
      bottom: 700,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });

    Object.defineProperty(image!, "naturalWidth", { configurable: true, value: 1200 });
    Object.defineProperty(image!, "naturalHeight", { configurable: true, value: 800 });

    await act(async () => {
      image!.dispatchEvent(new Event("load"));
    });

    expect(image?.style.width).toBe("852px");

    await act(async () => {
      image!.dispatchEvent(new Event("error"));
    });

    expect(container.textContent).toContain("Preview unavailable");

    await act(async () => {
      root.render(
        <PlotModePreview
          hasPlot
          imageUrl="/plot-b.png"
          workspaceId="plot-b"
          plotVersion={1}
        />,
      );
    });

    const switchedImage = container.querySelector<HTMLImageElement>('img[alt="Generated plot preview"]');
    expect(container.textContent).not.toContain("Preview unavailable");
    expect(switchedImage).not.toBeNull();
    expect(switchedImage?.style.width).toBe("");
    expect(switchedImage?.style.height).toBe("");
  });
});
