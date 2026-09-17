import { Component, type ErrorInfo, type PropsWithChildren } from "react";

interface State { failed: boolean }

export default class ErrorBoundary extends Component<PropsWithChildren, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, information: ErrorInfo) {
    if (import.meta.env.DEV) console.error("Workspace render failed", error, information);
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="workspace-loading" role="alert">
          <span className="workspace-loading__mark" aria-hidden="true">S</span>
          <h1>We could not open this workspace</h1>
          <p>No changes were made. Reload the page or return to the overview.</p>
          <span className="row-actions">
            <button className="button button--primary" onClick={() => window.location.reload()}>Reload</button>
            <a className="button button--secondary" href="/app/">Workspace overview</a>
          </span>
        </main>
      );
    }
    return this.props.children;
  }
}
