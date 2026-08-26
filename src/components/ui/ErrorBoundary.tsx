import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "../ui/icons";

interface Props {
    children?: ReactNode;
}

interface State {
    hasError: boolean;
    error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
    public state: State = {
        hasError: false,
        error: null,
    };

    public static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    public componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
        console.error("Uncaught React Error:", error, errorInfo);
    }

    private handleReset = () => {
        this.setState({ hasError: false, error: null });
        window.location.reload();
    };

    public render() {
        if (this.state.hasError) {
            return (
                <div className="flex-1 flex flex-col items-center justify-center h-screen bg-zinc-100 dark:bg-zinc-950 p-6">
          <div className="bg-white dark:bg-zinc-900 border border-red-200 dark:border-red-900/50 p-8 rounded-2xl shadow-xl max-w-md w-full text-center">
            <div className="w-16 h-16 bg-red-100 dark:bg-red-500/10 text-red-500 rounded-2xl flex items-center justify-center mx-auto mb-6">
              <AlertTriangle className="w-8 h-8" />
            </div>
            <h1 className="text-xl font-bold text-zinc-900 dark:text-white mb-2">
              Something went wrong
            </h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">
              The application encountered an unexpected rendering error. Your saved files are safe.
            </p>
            <div className="bg-zinc-50 dark:bg-zinc-950 p-4 rounded-lg text-left overflow-x-auto mb-6 border border-zinc-200 dark:border-white/5">
              <code className="text-[10px] text-red-600 dark:text-red-400 font-mono whitespace-pre-wrap">
                {this.state.error?.message || "Unknown error"}
              </code>
            </div>
            <button
              onClick={this.handleReset}
              className="w-full flex items-center justify-center gap-2 bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 px-4 py-2.5 rounded-xl font-bold hover:bg-zinc-800 dark:hover:bg-zinc-200 transition-colors shadow-sm"
            >
              <RefreshCw className="w-4 h-4" /> Reload Application
            </button>
          </div>
        </div>
            );
        }
        return this.props.children;
    }
}