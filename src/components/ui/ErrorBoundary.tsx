import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "./icons";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error("Uncaught React Error:", error, errorInfo);
    // Storing errorInfo in state allows us to display the component stack trace
    this.setState({ errorInfo }); 
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      return (
        // Fixed overlay ensures it covers the screen even if nested deep in the DOM tree
        <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-zinc-50/80 dark:bg-zinc-950/80 backdrop-blur-md p-6 selection:bg-red-500/30">
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200/60 dark:border-white/10 shadow-2xl rounded-2xl max-w-lg w-full overflow-hidden flex flex-col">
            
            {/* Visual Accent Line */}
            <div className="h-1.5 w-full bg-gradient-to-r from-red-500 to-rose-400" />

            <div className="p-8">
              <div className="flex items-start gap-5 mb-6">
                <div className="shrink-0 w-12 h-12 bg-red-100 dark:bg-red-500/10 text-red-600 dark:text-red-400 rounded-full flex items-center justify-center ring-4 ring-red-50 dark:ring-red-500/5">
                  <AlertTriangle className="w-6 h-6 stroke-[2.5]" />
                </div>
                <div>
                  <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100 tracking-tight">
                    <Trans>something-went-wrong</Trans>
                  </h1>
                  <p className="text-sm text-zinc-500 dark:text-zinc-400 mt-1.5 leading-relaxed">
                    <Trans>errorboundary_reason</Trans>
                  </p>
                </div>
              </div>

              {/* Terminal-style Error Output */}
              <div className="bg-zinc-950 dark:bg-black rounded-xl overflow-hidden border border-zinc-800 dark:border-zinc-800/50 shadow-inner mb-8">
                <div className="flex items-center px-4 py-2.5 bg-zinc-900 border-b border-zinc-800">
                  <div className="flex gap-1.5 mr-3">
                    <div className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
                    <div className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
                    <div className="w-2.5 h-2.5 rounded-full bg-zinc-700" />
                  </div>
                  <span className="text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
                    Error Trace
                  </span>
                </div>
                <div className="p-4 overflow-x-auto max-h-48 overflow-y-auto">
                  <code className="text-xs text-rose-300 font-mono whitespace-pre-wrap leading-relaxed block">
                    {this.state.error?.message || t`errorboundary_error-message`}
                    {this.state.errorInfo?.componentStack && (
                      <span className="block mt-3 text-zinc-500">
                        {this.state.errorInfo.componentStack}
                      </span>
                    )}
                  </code>
                </div>
              </div>

              <button
                onClick={this.handleReset}
                className="w-full flex items-center justify-center gap-2 bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 px-5 py-3 rounded-xl font-medium hover:bg-zinc-800 dark:hover:bg-zinc-200 transition-all active:scale-[0.98] shadow-md shadow-zinc-900/5"
              >
                <RefreshCw className="w-4 h-4" />
                <Trans>Reload Application</Trans>
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}