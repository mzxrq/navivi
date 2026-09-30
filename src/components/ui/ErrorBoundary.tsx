import { Component, ErrorInfo, ReactNode } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { AlertTriangle, Check, Copy, Minus, RefreshCw, X } from "./icons";
import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
  showDetails: boolean;
  copied: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
    showDetails: false,
    copied: false,
  };

  public static getDerivedStateFromError(error: Error): Partial<State> {
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

  private detailsText = () =>
    [
      this.state.error?.message || t`errorboundary_error-message`,
      this.state.error?.stack,
      this.state.errorInfo?.componentStack,
    ]
      .filter(Boolean)
      .join("\n\n");

  private handleCopy = () => {
    void navigator.clipboard.writeText(this.detailsText());
    this.setState({ copied: true });
    setTimeout(() => this.setState({ copied: false }), 2000);
  };

  public render() {
    if (!this.state.hasError) return this.props.children;

    const { showDetails, copied } = this.state;

    return (
      <div className="fixed inset-0 z-99999 flex flex-col bg-zinc-50 dark:bg-zinc-950">
        <div data-tauri-drag-region className="h-10 shrink-0 flex items-center justify-end">
          <button
            type="button"
            onClick={() => void getCurrentWindow().minimize().catch(() => {})}
            aria-label={t`Minimize`}
            className="h-full w-11 flex items-center justify-center text-zinc-500 hover:bg-black/5 dark:hover:bg-white/10 transition-colors"
          >
            <Minus className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={() => void getCurrentWindow().close().catch(() => {})}
            aria-label={t`Close`}
            className="h-full w-11 flex items-center justify-center text-zinc-500 hover:bg-red-500 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto flex items-center justify-center p-6">
        <div className="w-full max-w-lg rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-white/10 shadow-xl overflow-hidden">
          <div className="p-6">
            <div className="flex items-start gap-3.5">
              <span className="w-9 h-9 rounded-xl bg-red-500/10 text-red-500 flex items-center justify-center shrink-0">
                <AlertTriangle className="w-4.5 h-4.5" />
              </span>
              <div className="min-w-0">
                <h1 className="text-[15px] font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
                  <Trans>something-went-wrong</Trans>
                </h1>
                <p className="mt-1 text-[13px] leading-relaxed text-zinc-500 dark:text-zinc-400">
                  <Trans>errorboundary_reason</Trans>
                </p>
              </div>
            </div>

            <p className="mt-4 px-3 py-2.5 rounded-lg bg-red-500/5 border border-red-500/15 text-[12px] leading-relaxed text-red-700 dark:text-red-300 wrap-break-word select-text">
              {this.state.error?.message || t`errorboundary_error-message`}
            </p>

            {showDetails && (
              <pre className="mt-2 max-h-48 overflow-auto custom-scrollbar px-3 py-2.5 rounded-lg bg-zinc-50 dark:bg-black/30 border border-zinc-200 dark:border-white/10 text-[11px] leading-relaxed text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap font-sans select-text">
                {[this.state.error?.stack, this.state.errorInfo?.componentStack]
                  .filter(Boolean)
                  .join("\n\n")}
              </pre>
            )}
          </div>

          <div className="flex items-center gap-2 px-6 pb-6">
            <button
              type="button"
              onClick={() => this.setState({ showDetails: !showDetails })}
              className="h-8 px-3 rounded-lg text-[13px] font-medium text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
            >
              {showDetails ? t`Hide details` : t`Show details`}
            </button>
            <button
              type="button"
              onClick={this.handleCopy}
              className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-[13px] font-medium text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
              {copied ? t`Copied` : t`Copy error`}
            </button>
            <button
              type="button"
              onClick={this.handleReset}
              className="ml-auto flex items-center gap-1.5 h-8 px-3.5 rounded-lg bg-navi text-white text-[13px] font-semibold hover:brightness-110 transition"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <Trans>Reload Application</Trans>
            </button>
          </div>
        </div>
        </div>
      </div>
    );
  }
}
