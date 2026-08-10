import { useEffect, useState } from "react";

import { apiClient } from "../../api/client";
import { StatusIndicator } from "../../components/StatusIndicator";
import type { HealthResponse } from "../../types/api";
import { QueryWorkspace } from "../query/QueryWorkspace";

type HealthState =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: HealthResponse; error: null }
  | { status: "failed"; data: null; error: string };

export function HomePage() {
  const [health, setHealth] = useState<HealthState>({
    status: "loading",
    data: null,
    error: null
  });

  useEffect(() => {
    const controller = new AbortController();

    void apiClient
      .getHealth()
      .then((data) => {
        if (!controller.signal.aborted) {
          setHealth({ status: "ready", data, error: null });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setHealth({
            status: "failed",
            data: null,
            error: error instanceof Error ? error.message : "Unable to reach the API."
          });
        }
      });

    return () => {
      controller.abort();
    };
  }, []);

  return (
    <main className="app-shell">
      <QueryWorkspace />

      <aside className="side-rail" aria-label="Workspace status">
        <StatusIndicator
          health={health.data}
          isLoading={health.status === "loading"}
          error={health.error}
        />
      </aside>
    </main>
  );
}
