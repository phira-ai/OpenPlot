// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PlotModeSidebar from "./PlotModeSidebar";
import type { PlotModeState } from "../types";

function createPlotModeState(): PlotModeState {
  return {
    id: "plot-a",
    phase: "ready",
    workspace_name: "Workspace A",
    workspace_dir: "/tmp/workspace-a",
    files: [],
    input_bundle: null,
    messages: [
      {
        id: "assistant-1",
        role: "assistant",
        content: "Latest draft update",
        metadata: null,
        created_at: "2026-03-18T19:00:00Z",
      },
    ],
    data_profiles: [],
    resolved_sources: [],
    active_resolved_source_ids: [],
    selected_data_profile_id: null,
    tabular_selector: null,
    pending_question_set: null,
    execution_mode: "quick",
    latest_plan_summary: "",
    latest_plan_outline: [],
    latest_plan_plot_type: "svg",
    latest_plan_actions: [],
    current_script: "print('hi')",
    current_script_path: null,
    current_plot: "/tmp/plot.png",
    plot_type: "svg",
    latest_user_goal: "",
    selected_runner: "opencode",
    selected_model: "",
    selected_variant: "",
    runner_session_ids: {},
    last_error: null,
    created_at: "2026-03-18T18:00:00Z",
    updated_at: "2026-03-18T19:00:00Z",
  };
}

function createQuestionState({ pending = true }: { pending?: boolean } = {}): PlotModeState {
  const firstQuestion = {
    id: "question-1",
    title: "Style",
    prompt: "Pick a plotting style",
    options: [
      {
        id: "option-1",
        label: "Minimal",
        description: "Keep the chart clean",
        recommended: true,
      },
    ],
    allow_custom_answer: false,
    multiple: false,
    answered: false,
    selected_option_ids: [],
    answer_text: null,
  };
  const secondQuestion = {
    id: "question-2",
    title: "Palette",
    prompt: "Pick a color palette",
    options: [
      {
        id: "option-2",
        label: "Muted",
        description: "Prefer softer colors",
        recommended: false,
      },
    ],
    allow_custom_answer: false,
    multiple: false,
    answered: false,
    selected_option_ids: [],
    answer_text: null,
  };

  const questionSet = {
    id: "question-set-1",
    purpose: "continue_plot_planning" as const,
    title: "Plot style",
    source_ids: [],
    questions: [firstQuestion, secondQuestion],
  };

  return {
    ...createPlotModeState(),
    messages: [
      {
        id: "assistant-question-1",
        role: "assistant",
        content: "Choose the plotting style.",
        metadata: {
          kind: "question",
          title: "Plot style",
          items: [],
          table_columns: [],
          table_rows: [],
          table_caption: null,
          table_source_label: null,
          question_set_id: questionSet.id,
          question_set_title: questionSet.title,
          questions: questionSet.questions,
        },
        created_at: "2026-03-18T19:00:00Z",
      },
    ],
    pending_question_set: pending ? questionSet : null,
  };
}

function createKickoffQuestionState(): PlotModeState {
  const questionSet = {
    id: "question-set-kickoff-1",
    purpose: "kickoff_plot_planning" as const,
    title: "Kickoff plot planning",
    source_ids: [],
    questions: [
      {
        id: "question-kickoff-1",
        title: "Goal",
        prompt: "What kind of plot should we plan?",
        options: [
          {
            id: "option-kickoff-1",
            label: "Start from this direction",
            description: "Use this plan as the starting point",
            recommended: true,
          },
        ],
        allow_custom_answer: true,
        multiple: false,
        answered: false,
        selected_option_ids: [],
        answer_text: null,
      },
    ],
  };

  return {
    ...createPlotModeState(),
    messages: [
      {
        id: "assistant-question-kickoff-1",
        role: "assistant",
        content: "Tell me how you want to start planning this plot.",
        metadata: {
          kind: "question",
          title: "Kickoff plot planning",
          items: [],
          table_columns: [],
          table_rows: [],
          table_caption: null,
          table_source_label: null,
          question_set_id: questionSet.id,
          question_set_title: questionSet.title,
          questions: questionSet.questions,
        },
        created_at: "2026-03-18T19:00:00Z",
      },
    ],
    pending_question_set: questionSet,
  };
}

function flushAnimationFrames() {
  const callbacks = [...rafCallbacksRef.current];
  rafCallbacksRef.current = [];
  for (const callback of callbacks) {
    callback(0);
  }
}

const rafCallbacksRef: { current: FrameRequestCallback[] } = { current: [] };

describe("PlotModeSidebar", () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let scrollToMock: ReturnType<typeof vi.fn>;
  let rafCallbacks: FrameRequestCallback[];

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    rafCallbacks = [];
    rafCallbacksRef.current = rafCallbacks;
    scrollToMock = vi.fn();

    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    );
    vi.stubGlobal("navigator", { maxTouchPoints: 0 });
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
      rafCallbacksRef.current.push(callback);
      return rafCallbacksRef.current.length;
    }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    window.requestAnimationFrame = globalThis.requestAnimationFrame;
    window.cancelAnimationFrame = globalThis.cancelAnimationFrame;

    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        return 1200;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollToMock,
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
  });

  it("scrolls to the latest message on initial mount with existing chat history", async () => {
    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={createPlotModeState()}
          desktopViewport
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "~/",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
    });

    const messages = container.querySelector<HTMLElement>("[data-plot-messages]");
    expect(messages).not.toBeNull();
    Object.defineProperty(messages!, "scrollTo", {
      configurable: true,
      value: scrollToMock,
    });
    expect(rafCallbacks.length).toBeGreaterThan(0);

    await act(async () => {
      for (const callback of rafCallbacks) {
        callback(0);
      }
    });

    expect(scrollToMock).toHaveBeenCalledWith({ top: 1200 });
  });

  it("clears pending user message bubbles when switching workspaces", async () => {
    let releaseSend: (() => void) | undefined;
    const pendingSend = new Promise<void>((resolve) => {
      releaseSend = resolve;
    });

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={createPlotModeState()}
          desktopViewport={false}
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "~/",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => pendingSend}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
    });

    const textarea = container.querySelector<HTMLTextAreaElement>("textarea");
    const form = container.querySelector<HTMLFormElement>("form");
    expect(textarea).not.toBeNull();
    expect(form).not.toBeNull();

    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setValue?.call(textarea!, "draft for workspace A");
      textarea!.dispatchEvent(new Event("input", { bubbles: true }));
      textarea!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    await act(async () => {
      form!.requestSubmit();
    });

    expect(container.textContent).toContain("draft for workspace A");

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={{
            ...createPlotModeState(),
            id: "plot-b",
            workspace_name: "Workspace B",
            messages: [],
          }}
          desktopViewport={false}
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "~/",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    expect(container.textContent).not.toContain("draft for workspace A");
    if (releaseSend) {
      releaseSend();
    }
  });

  it("clears an unsent composer draft when switching workspaces", async () => {
    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={createPlotModeState()}
          desktopViewport={false}
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
    });

    const textarea = container.querySelector<HTMLTextAreaElement>("textarea");
    expect(textarea).not.toBeNull();

    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setValue?.call(textarea!, "draft that should not carry over");
      textarea!.dispatchEvent(new Event("input", { bubbles: true }));
      textarea!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(textarea?.value).toBe("draft that should not carry over");

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={{
            ...createPlotModeState(),
            id: "plot-b",
            workspace_name: "Workspace B",
          }}
          desktopViewport={false}
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    const switchedTextarea = container.querySelector<HTMLTextAreaElement>("textarea");
    expect(switchedTextarea?.value).toBe("");
  });

  it("closes the source sheet when switching workspaces", async () => {
    const awaitingFilesState = {
      ...createPlotModeState(),
      phase: "awaiting_files" as const,
      current_script: null,
      current_script_path: null,
      current_plot: null,
    };

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={awaitingFilesState}
          desktopViewport={false}
          forceInitialFileSelection
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "~/",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    expect(document.body.textContent).toContain("Attach local data files or plotting script");

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={{
            ...awaitingFilesState,
            id: "plot-b",
            workspace_name: "Workspace B",
          }}
          desktopViewport={false}
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "~/",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    expect(document.body.textContent).not.toContain("Attach local data files or plotting script");
  });

  it("requests workspace-relative source suggestions with an empty initial query", async () => {
    const fetchSuggestions = vi.fn(async () => ({
      suggestions: [],
      query: "",
      selection_type: "data" as const,
      base_dir: "/tmp/workspace-a",
    }));

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={{
            ...createPlotModeState(),
            phase: "awaiting_files",
            current_script: null,
            current_script_path: null,
            current_plot: null,
          }}
          desktopViewport={false}
          forceInitialFileSelection
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={fetchSuggestions}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    expect(fetchSuggestions).toHaveBeenCalled();
    expect(fetchSuggestions).toHaveBeenCalledWith("", "data");
  });

  it("shows fetched path suggestions and submits the selected data source", async () => {
    const onSelectPaths = vi.fn(async () => {});

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={{
            ...createPlotModeState(),
            phase: "awaiting_files",
            current_script: null,
            current_script_path: null,
            current_plot: null,
          }}
          desktopViewport={false}
          forceInitialFileSelection
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [
              {
                path: "/tmp/workspace-a/data/sales.csv",
                display_path: "~/data/sales.csv",
                is_dir: false,
                is_file: true,
              },
            ],
            query: "",
            selection_type: "data",
            base_dir: "/tmp/workspace-a",
          })}
          onSelectPaths={onSelectPaths}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    const suggestionButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button[type="button"]')).find(
      (button) => button.textContent?.includes("~/data/sales.csv"),
    );
    expect(suggestionButton).not.toBeNull();

    await act(async () => {
      const input = document.body.querySelector<HTMLInputElement>("input");
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setValue?.call(input!, "/tmp/workspace-a/data/sales.csv");
      input!.dispatchEvent(new Event("input", { bubbles: true }));
      input!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const addButton = Array.from(document.body.querySelectorAll<HTMLButtonElement>('button[type="button"]')).find(
      (button) => button.textContent === "Add",
    );
    expect(addButton).not.toBeNull();

    await act(async () => {
      addButton?.click();
    });

    const confirmButton = Array.from(document.body.querySelectorAll<HTMLButtonElement>('button[type="button"]')).find(
      (button) => button.getAttribute("aria-label") === "Use selected sources",
    );
    expect(confirmButton).not.toBeNull();

    await act(async () => {
      confirmButton?.click();
    });

    expect(onSelectPaths).toHaveBeenCalledWith("data", ["/tmp/workspace-a/data/sales.csv"]);
  });

  it("renders historical question cards as read-only when they are no longer pending", async () => {
    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={createQuestionState({ pending: false })}
          desktopViewport={false}
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    const optionButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button[type="button"]')).find(
      (button) => button.textContent?.includes("Minimal"),
    );
    const tabButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button[type="button"]')).find(
      (button) => button.textContent?.includes("Palette"),
    );
    expect(container.textContent).toContain("Pick a plotting style");
    expect(optionButton?.disabled).toBe(true);

    await act(async () => {
      tabButton?.click();
    });

    expect(container.textContent).toContain("Pick a plotting style");
    expect(container.textContent).not.toContain("Pick a color palette");
  });

  it("keeps typed kickoff text visible and submits it with the final selected option", async () => {
    const onAnswerQuestion = vi.fn(async () => {});

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={createKickoffQuestionState()}
          desktopViewport={false}
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={onAnswerQuestion}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    const textarea = container.querySelector<HTMLTextAreaElement>('textarea[placeholder="Type your answer"]');
    const optionButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button[type="button"]')).find(
      (button) => button.textContent?.includes("Start from this direction"),
    );

    expect(textarea).not.toBeNull();
    expect(optionButton).not.toBeNull();

    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setValue?.call(textarea!, "Focus on comparing the first two series.");
      textarea!.dispatchEvent(new Event("input", { bubbles: true }));
      textarea!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(textarea?.value).toBe("Focus on comparing the first two series.");
    expect(container.textContent).toContain("Focus on comparing the first two series.");

    await act(async () => {
      optionButton!.click();
    });

    expect(onAnswerQuestion).toHaveBeenCalledWith("question-set-kickoff-1", [
      {
        question_id: "question-kickoff-1",
        option_ids: ["option-kickoff-1"],
        text: "Focus on comparing the first two series.",
      },
    ]);
  });

  it("advances through pending questions and submits the full answer set", async () => {
    const onAnswerQuestion = vi.fn(async () => {});

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={createQuestionState()}
          desktopViewport={false}
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={onAnswerQuestion}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    const firstOptionButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button[type="button"]')).find(
      (button) => button.textContent?.includes("Minimal"),
    );
    expect(firstOptionButton).not.toBeNull();

    await act(async () => {
      firstOptionButton?.click();
    });

    expect(container.textContent).toContain("Pick a color palette");

    const secondOptionButton = Array.from(container.querySelectorAll<HTMLButtonElement>('button[type="button"]')).find(
      (button) => button.textContent?.includes("Muted"),
    );
    expect(secondOptionButton).not.toBeNull();

    await act(async () => {
      secondOptionButton?.click();
    });

    expect(onAnswerQuestion).toHaveBeenCalledWith("question-set-1", [
      {
        question_id: "question-1",
        option_ids: ["option-1"],
        text: null,
      },
      {
        question_id: "question-2",
        option_ids: ["option-2"],
        text: null,
      },
    ]);
  });

  it("renders message timestamps and submits composer prompts", async () => {
    const onSendMessage = vi.fn(async () => {});
    const createdAt = "2026-03-18T19:00:00Z";
    const expectedTimestamp = new Date(Date.parse(createdAt)).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    });

    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={{
            ...createPlotModeState(),
            messages: [
              {
                id: "user-1",
                role: "user",
                content: "Please compare the first two series.",
                metadata: null,
                created_at: createdAt,
              },
              {
                id: "assistant-1",
                role: "assistant",
                content: "Latest draft update",
                metadata: null,
                created_at: createdAt,
              },
            ],
          }}
          desktopViewport={false}
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={onSendMessage}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    expect(container.textContent).toContain(expectedTimestamp);

    const textarea = container.querySelector<HTMLTextAreaElement>("textarea");
    expect(textarea).not.toBeNull();

    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setValue?.call(textarea!, "Tighten the legend labels.");
      textarea!.dispatchEvent(new Event("input", { bubbles: true }));
      textarea!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const form = container.querySelector<HTMLFormElement>("form");
    expect(form).not.toBeNull();

    await act(async () => {
      form?.requestSubmit();
    });

    expect(onSendMessage).toHaveBeenCalledWith("Tighten the legend labels.");
    const refreshedTextarea = container.querySelector<HTMLTextAreaElement>("textarea");
    expect(refreshedTextarea?.value).toBe("");
  });

  it("uses a narrow desktop reveal strip for the prompt composer", async () => {
    await act(async () => {
      root.render(
        <PlotModeSidebar
          state={createQuestionState()}
          desktopViewport
          forceInitialFileSelection={false}
          selectingFiles={false}
          sendingMessage={false}
          finalizing={false}
          onFetchPathSuggestions={async () => ({
            suggestions: [],
            query: "",
            selection_type: "data",
            base_dir: "/tmp",
          })}
          onSelectPaths={async () => {}}
          onSubmitTabularHint={async () => {}}
          onSendMessage={async () => {}}
          onShowError={() => {}}
          plotModeExecutionMode="quick"
          onChangePlotModeExecutionMode={async () => {}}
          onAnswerQuestion={async () => {}}
          onNext={async () => {}}
        />,
      );
      flushAnimationFrames();
    });

    const revealZone = Array.from(container.querySelectorAll<HTMLDivElement>("div")).find((element) =>
      element.className.includes("bottom-[3.75rem]") && element.className.includes("z-10"),
    );

    expect(revealZone).toBeDefined();
    expect(revealZone?.className).toContain("h-8");
    expect(revealZone?.className).not.toContain("h-24");
  });
});
