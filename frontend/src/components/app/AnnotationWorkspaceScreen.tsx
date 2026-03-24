import type { ComponentProps, ReactNode } from "react";
import { CircleHelp } from "lucide-react";

import type { NotificationBubble } from "../NotificationBubbleStack";
import FeedbackSidebar from "../FeedbackSidebar";
import FixStepLiveModal from "../FixStepLiveModal";
import NotificationBubbleStack from "../NotificationBubbleStack";
import PlotViewer from "../PlotViewer";
import SessionSidebar from "../SessionSidebar";
import Toolbar from "../Toolbar";
import WalkthroughPromptModal from "../WalkthroughPromptModal";
import WalkthroughTour from "../WalkthroughTour";
import { Button } from "@/components/ui/button";
import { TooltipProvider } from "@/components/ui/tooltip";

interface AnnotationWorkspaceScreenProps {
  notifications: NotificationBubble[];
  onDismissNotification: (id: string) => void;
  toolbarProps: ComponentProps<typeof Toolbar>;
  showWorkspaceSidebar: boolean;
  onWorkspaceHotzoneEnter: () => void;
  onWorkspaceHotzoneLeave: () => void;
  sessionSidebarProps: Omit<ComponentProps<typeof SessionSidebar>, "open">;
  plotViewerKey: string;
  plotViewerProps: ComponentProps<typeof PlotViewer>;
  feedbackSidebarProps: ComponentProps<typeof FeedbackSidebar>;
  footerSourcePath: string;
  footerPlotType: string;
  footerBranchName: string;
  footerRevisionCount: number;
  footerCheckedOutVersionId: string;
  onRestartWalkthrough: () => void;
  walkthroughPromptOpen: boolean;
  onStartWalkthrough: () => void;
  onDismissWalkthroughPrompt: () => void;
  onDontShowWalkthroughAgain: () => void;
  showWalkthroughTour: boolean;
  onCloseWalkthroughTour: () => void;
  onWalkthroughStepTargetChange: (target: string | null) => void;
  fixStepLiveModalProps: ComponentProps<typeof FixStepLiveModal> | null;
  runnerAuthDialog: ReactNode;
}

export default function AnnotationWorkspaceScreen({
  notifications,
  onDismissNotification,
  toolbarProps,
  showWorkspaceSidebar,
  onWorkspaceHotzoneEnter,
  onWorkspaceHotzoneLeave,
  sessionSidebarProps,
  plotViewerKey,
  plotViewerProps,
  feedbackSidebarProps,
  footerSourcePath,
  footerPlotType,
  footerBranchName,
  footerRevisionCount,
  footerCheckedOutVersionId,
  onRestartWalkthrough,
  walkthroughPromptOpen,
  onStartWalkthrough,
  onDismissWalkthroughPrompt,
  onDontShowWalkthroughAgain,
  showWalkthroughTour,
  onCloseWalkthroughTour,
  onWalkthroughStepTargetChange,
  fixStepLiveModalProps,
  runnerAuthDialog,
}: AnnotationWorkspaceScreenProps) {
  return (
    <TooltipProvider>
      <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
        <NotificationBubbleStack notifications={notifications} onDismiss={onDismissNotification} />
        <Toolbar {...toolbarProps} />

        <div
          aria-hidden
          className="fixed inset-y-0 left-0 z-30 hidden w-8 lg:block"
          onMouseEnter={onWorkspaceHotzoneEnter}
          onMouseLeave={onWorkspaceHotzoneLeave}
        />

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <SessionSidebar {...sessionSidebarProps} open={showWorkspaceSidebar} />

          <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
            <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
              <PlotViewer key={plotViewerKey} {...plotViewerProps} />
            </main>

            <FeedbackSidebar {...feedbackSidebarProps} />
          </div>
        </div>

        <footer
          data-walkthrough="session-footer"
          className="flex items-center justify-between border-t border-border/80 bg-muted/35 px-4 py-1.5 text-xs text-muted-foreground"
        >
          <span className="truncate pr-4">
            {footerSourcePath} &mdash; {footerPlotType} &mdash; {footerBranchName}
          </span>
          <div className="flex shrink-0 items-center gap-1.5">
            <span>
              Rev {footerRevisionCount} · {footerCheckedOutVersionId}
            </span>
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
          mode="annotation"
          onStart={onStartWalkthrough}
          onDismiss={onDismissWalkthroughPrompt}
          onDontShowAgain={onDontShowWalkthroughAgain}
        />

        {showWalkthroughTour ? (
          <WalkthroughTour
            onClose={onCloseWalkthroughTour}
            onStepTargetChange={onWalkthroughStepTargetChange}
          />
        ) : null}

        {fixStepLiveModalProps ? <FixStepLiveModal {...fixStepLiveModalProps} /> : null}

        {runnerAuthDialog}
      </div>
    </TooltipProvider>
  );
}
