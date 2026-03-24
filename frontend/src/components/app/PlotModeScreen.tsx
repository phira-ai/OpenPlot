import type { ComponentProps, ReactNode } from "react";
import { CircleHelp } from "lucide-react";

import type { NotificationBubble } from "../NotificationBubbleStack";
import NotificationBubbleStack from "../NotificationBubbleStack";
import PlotModePreview from "../PlotModePreview";
import PlotModeSidebar from "../PlotModeSidebar";
import PlotModeWalkthroughTour from "../PlotModeWalkthroughTour";
import SessionSidebar from "../SessionSidebar";
import Toolbar from "../Toolbar";
import WalkthroughPromptModal from "../WalkthroughPromptModal";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";

interface PlotModeScreenProps {
  notifications: NotificationBubble[];
  onDismissNotification: (id: string) => void;
  toolbarProps: ComponentProps<typeof Toolbar>;
  allowWorkspaceSidebar: boolean;
  showWorkspaceSidebar: boolean;
  onWorkspaceHotzoneEnter: () => void;
  onWorkspaceHotzoneLeave: () => void;
  sessionSidebarProps: Omit<ComponentProps<typeof SessionSidebar>, "open">;
  desktopViewport: boolean;
  plotModePreviewProps: ComponentProps<typeof PlotModePreview>;
  plotModeSidebarProps: Omit<ComponentProps<typeof PlotModeSidebar>, "desktopViewport">;
  selectedFileCount: number;
  onRestartWalkthrough: () => void;
  walkthroughPromptOpen: boolean;
  onStartWalkthrough: () => void;
  onDismissWalkthroughPrompt: () => void;
  onDontShowWalkthroughAgain: () => void;
  showPlotModeWalkthroughTour: boolean;
  onClosePlotModeWalkthroughTour: () => void;
  onPlotModeWalkthroughStepTargetChange: (target: string | null) => void;
  runnerAuthDialog: ReactNode;
}

export default function PlotModeScreen({
  notifications,
  onDismissNotification,
  toolbarProps,
  allowWorkspaceSidebar,
  showWorkspaceSidebar,
  onWorkspaceHotzoneEnter,
  onWorkspaceHotzoneLeave,
  sessionSidebarProps,
  desktopViewport,
  plotModePreviewProps,
  plotModeSidebarProps,
  selectedFileCount,
  onRestartWalkthrough,
  walkthroughPromptOpen,
  onStartWalkthrough,
  onDismissWalkthroughPrompt,
  onDontShowWalkthroughAgain,
  showPlotModeWalkthroughTour,
  onClosePlotModeWalkthroughTour,
  onPlotModeWalkthroughStepTargetChange,
  runnerAuthDialog,
}: PlotModeScreenProps) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
      <NotificationBubbleStack notifications={notifications} onDismiss={onDismissNotification} />
      <Toolbar {...toolbarProps} />

      {allowWorkspaceSidebar ? (
        <div
          aria-hidden
          className="fixed inset-y-0 left-0 z-30 hidden w-8 lg:block"
          onMouseEnter={onWorkspaceHotzoneEnter}
          onMouseLeave={onWorkspaceHotzoneLeave}
        />
      ) : null}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <SessionSidebar {...sessionSidebarProps} open={showWorkspaceSidebar} />

        {desktopViewport ? (
          <div className="min-h-0 flex-1 overflow-hidden">
            <ResizablePanelGroup orientation="horizontal" className="h-full w-full">
              <ResizablePanel defaultSize="67%" minSize="44%">
                <main className="h-full min-h-0 min-w-0 overflow-hidden">
                  <PlotModePreview {...plotModePreviewProps} />
                </main>
              </ResizablePanel>

              <ResizableHandle
                withHandle
                className="bg-transparent text-muted-foreground/70 transition-colors hover:text-foreground"
              />

              <ResizablePanel defaultSize="33%" minSize="33%">
                <div className="h-full min-h-0 overflow-hidden">
                  <PlotModeSidebar {...plotModeSidebarProps} desktopViewport={desktopViewport} />
                </div>
              </ResizablePanel>
            </ResizablePanelGroup>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
              <PlotModePreview {...plotModePreviewProps} />
            </main>

            <PlotModeSidebar {...plotModeSidebarProps} desktopViewport={desktopViewport} />
          </div>
        )}
      </div>

      <footer
        data-walkthrough="plot-mode-footer"
        className="flex items-center justify-between border-t border-border/80 bg-muted/35 px-4 py-1.5 text-xs text-muted-foreground"
      >
        <span>
          {selectedFileCount} selected file{selectedFileCount === 1 ? "" : "s"}
        </span>
        <div className="flex shrink-0 items-center gap-1.5">
          <span>Refine the draft here, then move to annotation when it is ready</span>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            onClick={onRestartWalkthrough}
            aria-label="Restart walkthrough"
            title="Restart walkthrough"
          >
            <CircleHelp className="h-3.5 w-3.5" />
          </Button>
        </div>
      </footer>

      <WalkthroughPromptModal
        open={walkthroughPromptOpen}
        mode="plot"
        onStart={onStartWalkthrough}
        onDismiss={onDismissWalkthroughPrompt}
        onDontShowAgain={onDontShowWalkthroughAgain}
      />

      {showPlotModeWalkthroughTour ? (
        <PlotModeWalkthroughTour
          onClose={onClosePlotModeWalkthroughTour}
          onStepTargetChange={onPlotModeWalkthroughStepTargetChange}
        />
      ) : null}

      {runnerAuthDialog}
    </div>
  );
}
