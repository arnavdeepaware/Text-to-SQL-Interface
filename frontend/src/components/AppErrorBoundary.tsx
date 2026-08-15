import { Component, ErrorInfo, ReactNode } from "react";

interface AppErrorBoundaryProps {
  children: ReactNode;
}

interface AppErrorBoundaryState {
  hasError: boolean;
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false
  };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Frontend rendering failed", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="app-shell app-shell--centered">
          <section className="error-panel" role="alert" aria-labelledby="app-error-heading">
            <p className="eyebrow">Interface unavailable</p>
            <h1 id="app-error-heading">The workspace could not be rendered</h1>
            <p>Refresh the page and try again. No query was submitted by this screen.</p>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
