import { AlertTriangle } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

/** Contains a crash to one screen; the shell and navigation keep working. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("screen crashed", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="mx-auto max-w-md rounded-xl border border-red-200 bg-white p-6 text-center shadow-sm">
        <AlertTriangle className="mx-auto size-8 text-red-600" aria-hidden />
        <p className="mt-3 font-semibold">This screen hit a problem</p>
        <p className="mt-1 text-sm text-slate-500">Your data is safe. Reload the page, or use the menu to continue working.</p>
        <button className="mt-4 rounded-lg bg-brand-700 px-4 py-2 text-sm font-medium text-white" onClick={() => location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
