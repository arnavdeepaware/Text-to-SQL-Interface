import { useEffect, useState } from "react";

import { apiClient } from "../../api/client";
import type { QueryHistoryRecord } from "../../types/api";

const HISTORY_PAGE_SIZE = 5;

type HistoryStatus = "loading" | "ready" | "loading_more" | "failed";

interface HistoryState {
  status: HistoryStatus;
  records: QueryHistoryRecord[];
  total: number;
  error: string | null;
}

export function HistoryPanel() {
  const [state, setState] = useState<HistoryState>({
    status: "loading",
    records: [],
    total: 0,
    error: null
  });

  useEffect(() => {
    void loadHistory(0);
  }, []);

  const hasMore = state.records.length < state.total;

  async function loadHistory(offset: number) {
    setState((current) => ({
      ...current,
      status: offset === 0 ? "loading" : "loading_more",
      error: null
    }));

    try {
      const page = await apiClient.getHistory({ limit: HISTORY_PAGE_SIZE, offset });
      setState((current) => ({
        status: "ready",
        records: offset === 0 ? page.records : [...current.records, ...page.records],
        total: page.total,
        error: null
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        status: "failed",
        error: error instanceof Error ? error.message : "History could not be loaded."
      }));
    }
  }

  return (
    <section className="history-panel" aria-labelledby="history-heading">
      <div className="history-header">
        <div>
          <p className="eyebrow">History</p>
          <h2 id="history-heading">Recent queries</h2>
        </div>
        <button
          type="button"
          onClick={() => {
            void loadHistory(0);
          }}
          disabled={state.status === "loading" || state.status === "loading_more"}
        >
          Refresh
        </button>
      </div>

      {state.status === "loading" ? <p className="history-note">Loading history.</p> : null}
      {state.status === "failed" && state.error !== null ? (
        <p className="history-error" role="alert">
          {state.error}
        </p>
      ) : null}
      {state.records.length === 0 && state.status !== "loading" ? (
        <p className="history-note">No query history yet.</p>
      ) : null}
      {state.records.length > 0 ? (
        <ol className="history-list">
          {state.records.map((record) => (
            <li key={record.request_id}>
              <span className={`history-outcome history-outcome--${record.outcome}`}>
                {record.outcome.replace("_", " ")}
              </span>
              <strong>{record.normalized_question}</strong>
              <span>{new Date(record.created_at).toLocaleString()}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {hasMore ? (
        <button
          type="button"
          onClick={() => {
            void loadHistory(state.records.length);
          }}
          disabled={state.status === "loading_more"}
        >
          {state.status === "loading_more" ? "Loading" : "Load more"}
        </button>
      ) : null}
    </section>
  );
}
