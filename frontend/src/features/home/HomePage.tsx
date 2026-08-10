import { useEffect, useState } from "react";

import { apiClient } from "../../api/client";
import { StatusIndicator } from "../../components/StatusIndicator";
import type { HealthResponse } from "../../types/api";

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
      <section className="intro-panel" aria-labelledby="page-title">
        <p className="eyebrow">Safe Text-to-SQL workspace</p>
        <h1 id="page-title">Read-only query client foundation</h1>
        <p>
          The frontend shell is connected to the backend contracts and ready for the query workflow
          to be built on top of it.
        </p>
      </section>

      <StatusIndicator
        health={health.data}
        isLoading={health.status === "loading"}
        error={health.error}
      />
    </main>
  );
}
