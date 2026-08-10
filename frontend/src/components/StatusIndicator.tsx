import type { HealthResponse } from "../types/api";

interface StatusIndicatorProps {
  health: HealthResponse | null;
  isLoading: boolean;
  error: string | null;
}

export function StatusIndicator({ health, isLoading, error }: StatusIndicatorProps) {
  const status = statusLabel(health, isLoading, error);
  const tone = error === null && health?.status === "ok" ? "ok" : "degraded";

  return (
    <section className="status-card" aria-labelledby="status-heading">
      <div>
        <p className="eyebrow">Backend status</p>
        <h2 id="status-heading">{status}</h2>
      </div>
      <span className={`status-pill status-pill--${tone}`} aria-live="polite">
        {isLoading ? "Checking" : (health?.status ?? "Unavailable")}
      </span>
      {health !== null ? (
        <dl className="status-details">
          <div>
            <dt>Version</dt>
            <dd>{health.version}</dd>
          </div>
          <div>
            <dt>Database</dt>
            <dd>{health.checks.database?.status ?? "unknown"}</dd>
          </div>
        </dl>
      ) : null}
      {error !== null ? <p className="status-error">{error}</p> : null}
    </section>
  );
}

function statusLabel(health: HealthResponse | null, isLoading: boolean, error: string | null) {
  if (isLoading) {
    return "Checking API health";
  }

  if (error !== null) {
    return "API health unavailable";
  }

  if (health?.status === "ok") {
    return "API is ready";
  }

  return "API is degraded";
}
