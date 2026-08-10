import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { expect, vi } from "vitest";

import { App } from "./App";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import {
  mockLowConfidenceResponse,
  mockMediumConfidenceResponse,
  mockQueryExecutionResponse,
  mockUnavailableConfidenceResponse
} from "./test/mocks/handlers";
import { server } from "./test/mocks/server";
import type { ClarificationRequiredResponse, QueryResponse } from "./types/api";

test("renders the query workspace and backend health", async () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: /ask a read-only data question/i })).toBeVisible();
  expect(await screen.findByText(/api is ready/i)).toBeVisible();
  expect(screen.getByText("0.1.0")).toBeVisible();
});

test("submits a question with the keyboard and renders SQL, explanation, metadata, and results", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.click(screen.getByLabelText(/natural-language question/i));
  await user.keyboard("Show gross revenue by product category{Control>}{Enter}{/Control}");

  expect(await screen.findByText(/query executed/i)).toBeVisible();
  expect(screen.getByText("SELECT")).toBeVisible();
  expect(screen.getByText(/aggregates line totals by product category/i)).toBeVisible();
  expect(screen.getByText("18 ms")).toBeVisible();
  expect(screen.getByText("No")).toBeVisible();
  expect(screen.getByRole("cell", { name: "Hardware" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "52500" })).toBeVisible();
});

test("supports the query form entirely by keyboard navigation", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.tab();
  expect(screen.getByLabelText(/natural-language question/i)).toHaveFocus();
  await user.keyboard("Show gross revenue by product category");
  await user.keyboard("{Control>}{Enter}{/Control}");

  expect(await screen.findByText(/query executed/i)).toBeVisible();
  expect(screen.getByRole("cell", { name: "Hardware" })).toBeVisible();
});

test("shows high validated confidence without equating it to model confidence", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(
    screen.getByLabelText(/natural-language question/i),
    "Show gross revenue by product category"
  );
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(await screen.findByRole("heading", { name: /91% validated score/i })).toBeVisible();
  expect(screen.getByText("high")).toBeVisible();
  expect(screen.getByText(/model-reported confidence: 72%/i)).toBeVisible();
  expect(screen.getByText(/provider telemetry, not the validated confidence score/i)).toBeVisible();

  await user.click(screen.getByText(/validation signal breakdown/i));
  expect(screen.getByText("schema_coverage_passed")).toBeVisible();
  expect(screen.getByText(/tables_checked/i)).toBeVisible();
});

test("shows low confidence warnings, explanations, and evidence", async () => {
  server.use(
    http.post("*/v1/query", () => HttpResponse.json<QueryResponse>(mockLowConfidenceResponse))
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show revenue");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(await screen.findByRole("heading", { name: /32% validated score/i })).toBeVisible();
  expect(screen.getByText("low")).toBeVisible();
  expect(screen.getByText(/back-translation alignment was weak/i)).toBeVisible();

  await user.click(screen.getByText(/validation signal breakdown/i));
  expect(screen.getByText("answer_alignment_failed")).toBeVisible();
  expect(screen.getByText(/did not closely match/i)).toBeVisible();
  expect(screen.getByText(/generated_topic/i)).toBeVisible();
});

test("shows medium validated confidence with cautionary context", async () => {
  server.use(
    http.post("*/v1/query", () => HttpResponse.json<QueryResponse>(mockMediumConfidenceResponse))
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show revenue by category");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(await screen.findByRole("heading", { name: /67% validated score/i })).toBeVisible();
  expect(screen.getByText("medium")).toBeVisible();
  expect(screen.getByText(/small sample size/i)).toBeVisible();

  await user.click(screen.getByText(/validation signal breakdown/i));
  expect(screen.getByText("result_sanity_caution")).toBeVisible();
});

test("shows unavailable validation signals as unavailable rather than failed", async () => {
  server.use(
    http.post("*/v1/query", () =>
      HttpResponse.json<QueryResponse>(mockUnavailableConfidenceResponse)
    )
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show order count");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(
    await screen.findByRole("heading", { name: /validated score unavailable/i })
  ).toBeVisible();
  expect(screen.getByText("not applicable")).toBeVisible();
  expect(screen.getByText(/semantic alignment provider was unavailable/i)).toBeVisible();

  await user.click(screen.getByText(/validation signal breakdown/i));
  expect(screen.getByText("semantic_alignment_unavailable")).toBeVisible();
  expect(screen.getByText("unavailable")).toBeVisible();
  expect(screen.getByText(/retryable/i)).toBeVisible();
});

test("handles missing validation signal details without implying failure", async () => {
  server.use(
    http.post("*/v1/query", () =>
      HttpResponse.json<QueryResponse>({
        ...mockUnavailableConfidenceResponse,
        hallucination_confidence: {
          ...mockUnavailableConfidenceResponse.hallucination_confidence,
          signals: []
        }
      })
    )
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show order count");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(
    await screen.findByRole("heading", { name: /validated score unavailable/i })
  ).toBeVisible();
  await user.click(screen.getByText(/validation signal breakdown/i));
  expect(screen.getByText(/no validation signals were returned/i)).toBeVisible();
});

test("sorts result rows by column", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(
    screen.getByLabelText(/natural-language question/i),
    "Show gross revenue by product category"
  );
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(await screen.findByRole("cell", { name: "Hardware" })).toBeVisible();

  await user.click(screen.getByRole("button", { name: /category_name/i }));

  const cells = screen.getAllByRole("cell");
  expect(cells[0]).toHaveTextContent("Books");
  expect(screen.getByRole("columnheader", { name: /category_name/i })).toHaveAttribute(
    "aria-sort",
    "ascending"
  );
});

test("exposes keyboard focus and accessible names for the scrollable results table", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(
    screen.getByLabelText(/natural-language question/i),
    "Show gross revenue by product category"
  );
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(await screen.findByRole("cell", { name: "Hardware" })).toBeVisible();

  const resultsRegion = screen.getByRole("region", { name: /scrollable query results/i });
  resultsRegion.focus();

  expect(resultsRegion).toHaveFocus();
  expect(screen.getByRole("table", { name: /query result rows/i })).toBeVisible();
  expect(screen.getByRole("button", { name: /sort gross_revenue_cents ascending/i })).toBeVisible();
});

test("keeps a wide result table inside a keyboard-reachable overflow region", async () => {
  server.use(
    http.post("*/v1/query", () =>
      HttpResponse.json<QueryResponse>({
        ...mockQueryExecutionResponse,
        request_id: "req-wide-table",
        columns: Array.from({ length: 12 }, (_, index) => ({
          name: `metric_${String(index + 1)}`,
          type_code: "int8"
        })),
        rows: [
          Object.fromEntries(
            Array.from({ length: 12 }, (_, index) => [`metric_${String(index + 1)}`, index + 1])
          )
        ],
        row_count: 1
      })
    )
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show many metrics");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(await screen.findByRole("columnheader", { name: "metric_12" })).toBeVisible();
  const resultsRegion = screen.getByRole("region", { name: /scrollable query results/i });
  resultsRegion.focus();
  expect(resultsRegion).toHaveFocus();
});

test("shows a clear zero-row success state", async () => {
  server.use(
    http.post("*/v1/query", () =>
      HttpResponse.json<QueryResponse>({
        ...mockQueryExecutionResponse,
        request_id: "req-zero",
        rows: [],
        row_count: 0,
        execution_metadata: {
          ...mockQueryExecutionResponse.execution_metadata,
          row_count: 0
        }
      })
    )
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show empty categories");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(await screen.findByText(/returned zero rows/i)).toBeVisible();
});

test("preserves the last successful result while a new request is loading and marks it stale", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.type(
    screen.getByLabelText(/natural-language question/i),
    "Show gross revenue by product category"
  );
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(await screen.findByRole("cell", { name: "Hardware" })).toBeVisible();

  server.use(
    http.post("*/v1/query", async () => {
      await delay(200);
      return HttpResponse.json<QueryResponse>({
        ...mockQueryExecutionResponse,
        request_id: "req-next",
        question: "Show orders by status"
      });
    })
  );

  await user.clear(screen.getByLabelText(/natural-language question/i));
  await user.type(screen.getByLabelText(/natural-language question/i), "Show orders by status");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(screen.getByText(/previous successful result/i)).toBeVisible();
  expect(screen.getByRole("cell", { name: "Hardware" })).toBeVisible();
});

test("announces loading with a stable placeholder before the first result", async () => {
  server.use(
    http.post("*/v1/query", async () => {
      await delay(200);
      return HttpResponse.json<QueryResponse>(mockQueryExecutionResponse);
    })
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(
    screen.getByLabelText(/natural-language question/i),
    "Show gross revenue by product category"
  );
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(screen.getByRole("status", { name: /loading query/i })).toBeVisible();
  expect(screen.getByText(/running request/i)).toHaveAttribute("role", "status");
  expect(await screen.findByRole("cell", { name: "Hardware" })).toBeVisible();
});

test("renders blocked clarification responses separately from failures", async () => {
  server.use(
    http.post("*/v1/query", () =>
      HttpResponse.json<ClarificationRequiredResponse>({
        result_type: "clarification_required",
        request_id: "req-clarify",
        question: "Show revenue",
        message: "The question is materially ambiguous.",
        clarification_options: [
          {
            interpretation: "Gross revenue before refunds",
            example: "Show gross revenue by ordered month"
          }
        ]
      })
    )
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show revenue");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(await screen.findByRole("heading", { name: /clarification required/i })).toBeVisible();
  expect(screen.getAllByText(/not executed/i).length).toBeGreaterThan(0);
  expect(screen.getByText("clarification_required")).toBeVisible();
  expect(screen.getByText(/gross revenue before refunds/i)).toBeVisible();
});

test("resubmits a selectable clarification without losing the original question", async () => {
  let requestCount = 0;
  server.use(
    http.post("*/v1/query", () => {
      requestCount += 1;
      if (requestCount === 1) {
        return HttpResponse.json<ClarificationRequiredResponse>({
          result_type: "clarification_required",
          request_id: "req-clarify",
          question: "Show revenue",
          message: "The question is materially ambiguous.",
          clarification_options: [
            {
              interpretation: "Gross revenue before refunds",
              example: "Show gross revenue by ordered month"
            },
            {
              interpretation: "Net revenue after refunds",
              example: "Show net revenue by ordered month"
            }
          ]
        });
      }

      return HttpResponse.json<QueryResponse>({
        ...mockQueryExecutionResponse,
        request_id: "req-clarified",
        question: "Show revenue (Show net revenue by ordered month)"
      });
    })
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show revenue");
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(await screen.findByText(/original question:/i)).toHaveTextContent("Show revenue");

  const options = screen.getAllByRole("button", { name: /use this interpretation/i });
  const netRevenueOption = options[1];
  if (netRevenueOption === undefined) {
    throw new Error("Expected a second clarification option.");
  }
  await user.click(netRevenueOption);

  expect(
    await screen.findByText(/show revenue \(show net revenue by ordered month\)/i)
  ).toBeVisible();
  expect(screen.getByLabelText(/natural-language question/i)).toHaveValue("Show revenue");
});

test("shows blocked query errors as not executed with blocked reasons", async () => {
  server.use(
    http.post("*/v1/query", () =>
      HttpResponse.json(
        {
          error: {
            code: "query_plan_cost_threshold_exceeded",
            message: "The generated query plan exceeded the configured cost threshold.",
            request_id: "req-blocked"
          }
        },
        { status: 422 }
      )
    )
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show every row");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(
    await screen.findByRole("heading", { name: /query blocked before execution/i })
  ).toBeVisible();
  expect(screen.getByText("query_plan_cost_threshold_exceeded")).toBeVisible();
  expect(screen.getByText(/exceeded the configured cost threshold/i)).toBeVisible();
});

test("renders failed API requests differently from blocked requests and supports retry", async () => {
  let requestCount = 0;
  server.use(
    http.post("*/v1/query", () => {
      requestCount += 1;
      if (requestCount === 1) {
        return HttpResponse.json(
          {
            error: {
              code: "query_execution_unavailable",
              message: "Query execution is unavailable.",
              request_id: "req-failed"
            }
          },
          { status: 503 }
        );
      }

      return HttpResponse.json<QueryResponse>({
        ...mockQueryExecutionResponse,
        request_id: "req-retried"
      });
    })
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show order count");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(await screen.findByRole("heading", { name: /could not be completed/i })).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent(/request failed/i);
  expect(screen.queryByText(/blocked reasons/i)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /retry request/i }));

  expect(await screen.findByText(/query executed/i)).toBeVisible();
  expect(screen.getByRole("cell", { name: "Hardware" })).toBeVisible();
});

test("submits feedback once and prevents repeated accidental submissions", async () => {
  let feedbackCount = 0;
  server.use(
    http.post("*/v1/feedback", async () => {
      feedbackCount += 1;
      await delay(50);
      return HttpResponse.json(
        {
          id: 2,
          request_id: "req-test-query",
          rating: "correct",
          comment: "Looks right",
          created_at: "2026-08-10T00:01:00Z"
        },
        { status: 201 }
      );
    })
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(
    screen.getByLabelText(/natural-language question/i),
    "Show gross revenue by product category"
  );
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(await screen.findByRole("heading", { name: /result feedback/i })).toBeVisible();

  await user.click(screen.getByLabelText("correct"));
  await user.type(screen.getByLabelText(/optional comment/i), "Looks right");
  await user.dblClick(screen.getByRole("button", { name: /send feedback/i }));

  expect(await screen.findByText(/feedback recorded/i)).toBeVisible();
  expect(screen.getByRole("button", { name: /send feedback/i })).toBeDisabled();
  expect(feedbackCount).toBe(1);
});

test("shows query history empty state", async () => {
  server.use(
    http.get("*/v1/history", () =>
      HttpResponse.json({
        records: [],
        limit: 5,
        offset: 0,
        total: 0,
        retention_policy: {
          status: "placeholder",
          query_history_retention_days: 30,
          query_feedback_retention_days: 90
        },
        privacy_limitations: ["Raw result rows are not stored."]
      })
    )
  );

  render(<App />);

  expect(await screen.findByText(/no query history yet/i)).toBeVisible();
});

test("shows query history loading failures", async () => {
  server.use(
    http.get("*/v1/history", () =>
      HttpResponse.json(
        {
          error: {
            code: "query_history_unavailable",
            message: "Query history is unavailable.",
            request_id: "req-history-failed"
          }
        },
        { status: 503 }
      )
    )
  );

  render(<App />);

  expect(await screen.findByRole("alert", { name: "" })).toHaveTextContent(
    /query history is unavailable/i
  );
});

test("renders a resilient fallback when a frontend child throws", () => {
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
  function BrokenChild() {
    throw new Error("render failed");
    return null;
  }

  render(
    <AppErrorBoundary>
      <BrokenChild />
    </AppErrorBoundary>
  );

  expect(screen.getByRole("alert")).toHaveTextContent(/workspace could not be rendered/i);
  expect(screen.getByText(/no query was submitted/i)).toBeVisible();
  consoleError.mockRestore();
});
