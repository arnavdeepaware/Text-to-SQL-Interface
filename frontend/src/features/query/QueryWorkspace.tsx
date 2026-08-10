import { KeyboardEvent, SyntheticEvent, useMemo, useState } from "react";

import { APIClientError, apiClient } from "../../api/client";
import type { ClarificationRequiredResponse, QueryExecutionResponse } from "../../types/api";
import { ConfidencePanel } from "./ConfidencePanel";
import { FeedbackPanel } from "./FeedbackPanel";
import { ResultsTable } from "./ResultsTable";
import { SQLPreview } from "./SQLPreview";

type QueryStatus = "idle" | "loading" | "success" | "blocked" | "failed";

interface QueryState {
  status: QueryStatus;
  latestSuccess: QueryExecutionResponse | null;
  blocked: BlockedQuery | null;
  error: FailedQuery | null;
  submittedQuestion: string | null;
}

interface BlockedQuery {
  title: string;
  message: string;
  reasons: string[];
  requestId: string | null;
  clarification: ClarificationRequiredResponse | null;
  originalQuestion: string;
}

interface FailedQuery {
  title: string;
  message: string;
  code: string | null;
  requestId: string | null;
}

const initialState: QueryState = {
  status: "idle",
  latestSuccess: null,
  blocked: null,
  error: null,
  submittedQuestion: null
};

export function QueryWorkspace() {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<QueryState>(initialState);

  const isLoading = state.status === "loading";
  const hasStaleResult = isLoading && state.latestSuccess !== null;
  const canSubmit = question.trim().length > 0 && !isLoading;

  async function submitQuestion(overrideQuestion?: string) {
    const normalizedQuestion = (overrideQuestion ?? question).trim();
    if (normalizedQuestion.length === 0 || isLoading) {
      return;
    }

    setState((current) => ({
      status: "loading",
      latestSuccess: current.latestSuccess,
      blocked: null,
      error: null,
      submittedQuestion: normalizedQuestion
    }));

    try {
      const response = await apiClient.query({ question: normalizedQuestion });
      if (response.result_type === "clarification_required") {
        setState((current) => ({
          status: "blocked",
          latestSuccess: current.latestSuccess,
          blocked: clarificationToBlockedQuery(response, normalizedQuestion),
          error: null,
          submittedQuestion: normalizedQuestion
        }));
        return;
      }

      setState({
        status: "success",
        latestSuccess: response,
        blocked: null,
        error: null,
        submittedQuestion: normalizedQuestion
      });
    } catch (error) {
      if (isBlockedError(error)) {
        setState((current) => ({
          status: "blocked",
          latestSuccess: current.latestSuccess,
          blocked: apiErrorToBlockedQuery(error, normalizedQuestion),
          error: null,
          submittedQuestion: normalizedQuestion
        }));
        return;
      }

      setState((current) => ({
        status: "failed",
        latestSuccess: current.latestSuccess,
        blocked: null,
        error: apiErrorToFailedQuery(error),
        submittedQuestion: normalizedQuestion
      }));
    }
  }

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitQuestion();
  }

  function handleQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void submitQuestion();
    }
  }

  function handleClarificationSelect(clarifiedQuestion: string) {
    void submitQuestion(clarifiedQuestion);
  }

  function handleRetry() {
    if (state.submittedQuestion !== null) {
      void submitQuestion(state.submittedQuestion);
    }
  }

  return (
    <section className="workspace" aria-labelledby="workspace-title" aria-busy={isLoading}>
      <div className="workspace-header">
        <div>
          <p className="eyebrow">Query workspace</p>
          <h1 id="workspace-title">Ask a read-only data question</h1>
        </div>
        <p className="workspace-subtitle">
          Generated SQL is validated and executed by the backend. This interface does not accept
          arbitrary SQL.
        </p>
      </div>

      <form className="query-form" onSubmit={handleSubmit}>
        <label htmlFor="question">Natural-language question</label>
        <textarea
          id="question"
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
          }}
          onKeyDown={handleQuestionKeyDown}
          placeholder="Show gross revenue by product category"
          rows={4}
          aria-describedby="question-help question-status"
          aria-keyshortcuts="Control+Enter Meta+Enter"
        />
        <p id="question-help" className="visually-hidden">
          Submit the question with the Submit button, or press Control Enter on Windows and Linux or
          Command Enter on macOS.
        </p>
        <div className="query-form-footer">
          <p id="question-status" role="status" aria-live="polite" aria-atomic="true">
            {statusText(state, hasStaleResult)}
          </p>
          <button type="submit" disabled={!canSubmit}>
            {isLoading ? "Running" : "Submit"}
          </button>
        </div>
      </form>

      {isLoading && state.latestSuccess === null ? <LoadingWorkspace /> : null}

      {hasStaleResult ? (
        <div className="stale-banner" role="status" aria-live="polite">
          Showing the previous successful result while the new request runs.
        </div>
      ) : null}

      {state.status === "idle" ? <EmptyWorkspace /> : null}
      {state.status === "blocked" && state.blocked !== null ? (
        <BlockedPanel
          blocked={state.blocked}
          onSelectClarification={handleClarificationSelect}
          disabled={isLoading}
        />
      ) : null}
      {state.status === "failed" && state.error !== null ? (
        <ErrorPanel
          error={state.error}
          onRetry={handleRetry}
          canRetry={state.submittedQuestion !== null && !isLoading}
        />
      ) : null}
      {state.latestSuccess !== null ? (
        <QueryResultView result={state.latestSuccess} stale={hasStaleResult} />
      ) : null}
    </section>
  );
}

function EmptyWorkspace() {
  return (
    <div className="empty-state">
      <h2>No query has run yet</h2>
      <p>Submit a question to review generated SQL, validation details, and tabular results.</p>
    </div>
  );
}

function LoadingWorkspace() {
  return (
    <div className="loading-panel" role="status" aria-live="polite" aria-label="Loading query">
      <span className="visually-hidden">Running query.</span>
      <div className="loading-panel__header">
        <span className="skeleton skeleton--title" />
        <span className="skeleton skeleton--metric" />
      </div>
      <span className="skeleton skeleton--line" />
      <span className="skeleton skeleton--line skeleton--short" />
      <div className="skeleton-table" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}

function QueryResultView({ result, stale }: { result: QueryExecutionResponse; stale: boolean }) {
  const warnings = useMemo(() => resultWarnings(result), [result]);

  return (
    <article className={`result-panel${stale ? " result-panel--stale" : ""}`}>
      <header className="result-header">
        <div>
          <p className="eyebrow">Executed result</p>
          <h2>{result.question}</h2>
        </div>
        <dl className="result-metrics" aria-label="Execution metadata">
          <div>
            <dt>Rows</dt>
            <dd>{result.row_count}</dd>
          </div>
          <div>
            <dt>Time</dt>
            <dd>{result.execution_duration_ms} ms</dd>
          </div>
          <div>
            <dt>Truncated</dt>
            <dd>{result.truncated ? "Yes" : "No"}</dd>
          </div>
        </dl>
      </header>

      <section className="result-section" aria-labelledby="sql-heading">
        <h3 id="sql-heading">Generated SQL</h3>
        <SQLPreview sql={result.sql} />
      </section>

      <section className="result-section" aria-labelledby="explanation-heading">
        <h3 id="explanation-heading">Explanation</h3>
        <p className="explanation">{result.explanation}</p>
      </section>

      {warnings.length > 0 ? <WarningsPanel warnings={warnings} /> : null}

      <ConfidencePanel confidence={result.hallucination_confidence} metadata={result.metadata} />

      <section className="result-section" aria-labelledby="results-heading">
        <div className="section-heading-row">
          <h3 id="results-heading">Results</h3>
          <span>{result.columns.length} columns</span>
        </div>
        <ResultsTable columns={result.columns} rows={result.rows} />
      </section>

      <FeedbackPanel requestId={result.request_id} />
    </article>
  );
}

function WarningsPanel({ warnings }: { warnings: string[] }) {
  return (
    <section className="warning-panel" aria-labelledby="warnings-heading">
      <h3 id="warnings-heading">Guardrail warnings</h3>
      <ul>
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
    </section>
  );
}

function BlockedPanel({
  blocked,
  onSelectClarification,
  disabled
}: {
  blocked: BlockedQuery;
  onSelectClarification: (question: string) => void;
  disabled: boolean;
}) {
  return (
    <section className="blocked-panel" aria-labelledby="blocked-heading" role="status">
      <div>
        <p className="eyebrow">Not executed</p>
        <h2 id="blocked-heading">{blocked.title}</h2>
        <p>{blocked.message}</p>
      </div>
      <p className="original-question">
        Original question: <span>{blocked.originalQuestion}</span>
      </p>
      <div>
        <h3>Blocked reasons</h3>
        <ul>
          {blocked.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </div>
      {blocked.clarification !== null ? (
        <div>
          <h3>Clarification options</h3>
          <ul>
            {blocked.clarification.clarification_options.map((option, index) => {
              const optionId = `clarification-option-${String(index)}`;

              return (
                <li key={option.interpretation}>
                  <strong id={optionId}>{option.interpretation}</strong>
                  <span>{option.example}</span>
                  <button
                    type="button"
                    aria-describedby={optionId}
                    onClick={() => {
                      onSelectClarification(
                        clarifiedQuestion(blocked.originalQuestion, option.example)
                      );
                    }}
                    disabled={disabled}
                  >
                    Use this interpretation
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {blocked.requestId !== null ? (
        <p className="request-id">Request {blocked.requestId}</p>
      ) : null}
    </section>
  );
}

function ErrorPanel({
  error,
  onRetry,
  canRetry
}: {
  error: FailedQuery;
  onRetry: () => void;
  canRetry: boolean;
}) {
  return (
    <section className="error-panel" aria-labelledby="error-heading" role="alert">
      <p className="eyebrow">Request failed</p>
      <h2 id="error-heading">{error.title}</h2>
      <p>{error.message}</p>
      <button type="button" onClick={onRetry} disabled={!canRetry}>
        Retry request
      </button>
      {error.code !== null ? <p className="request-id">Code {error.code}</p> : null}
      {error.requestId !== null ? <p className="request-id">Request {error.requestId}</p> : null}
    </section>
  );
}

function statusText(state: QueryState, hasStaleResult: boolean): string {
  if (hasStaleResult) {
    return "Running a new request; previous result is marked stale.";
  }

  if (state.status === "loading") {
    return "Running request.";
  }

  if (state.status === "success") {
    return "Query executed.";
  }

  if (state.status === "blocked") {
    return "Query was not executed.";
  }

  if (state.status === "failed") {
    return "Request failed.";
  }

  return "Ready.";
}

function resultWarnings(result: QueryExecutionResponse): string[] {
  return result.guardrails.findings.map((finding) => `${finding.code}: ${finding.message}`);
}

function clarificationToBlockedQuery(
  response: ClarificationRequiredResponse,
  originalQuestion: string
): BlockedQuery {
  return {
    title: "Clarification required",
    message: response.message,
    reasons: ["clarification_required"],
    requestId: response.request_id,
    clarification: response,
    originalQuestion
  };
}

function apiErrorToBlockedQuery(error: APIClientError, originalQuestion: string): BlockedQuery {
  return {
    title: "Query blocked before execution",
    message: error.message,
    reasons: [error.code],
    requestId: error.requestId,
    clarification: null,
    originalQuestion
  };
}

function clarifiedQuestion(originalQuestion: string, example: string): string {
  return `${originalQuestion} (${example})`;
}

function apiErrorToFailedQuery(error: unknown): FailedQuery {
  if (error instanceof APIClientError) {
    return {
      title: "The request could not be completed",
      message: error.message,
      code: error.code,
      requestId: error.requestId
    };
  }

  return {
    title: "The request could not be completed",
    message: error instanceof Error ? error.message : "An unexpected frontend error occurred.",
    code: null,
    requestId: null
  };
}

function isBlockedError(error: unknown): error is APIClientError {
  if (!(error instanceof APIClientError)) {
    return false;
  }

  return (
    error.status === 422 ||
    error.code.includes("blocked") ||
    error.code.includes("guardrail") ||
    error.code.includes("validation")
  );
}
