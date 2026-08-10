import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";

import { App } from "./App";
import { mockQueryExecutionResponse } from "./test/mocks/handlers";
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

test("renders failed API requests differently from blocked requests", async () => {
  server.use(
    http.post("*/v1/query", () =>
      HttpResponse.json(
        {
          error: {
            code: "query_execution_unavailable",
            message: "Query execution is unavailable.",
            request_id: "req-failed"
          }
        },
        { status: 503 }
      )
    )
  );
  const user = userEvent.setup();
  render(<App />);

  await user.type(screen.getByLabelText(/natural-language question/i), "Show order count");
  await user.click(screen.getByRole("button", { name: "Submit" }));

  expect(await screen.findByRole("heading", { name: /could not be completed/i })).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent(/request failed/i);
  expect(screen.queryByText(/blocked reasons/i)).not.toBeInTheDocument();
});
