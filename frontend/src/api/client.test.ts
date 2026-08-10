import { http, HttpResponse } from "msw";

import { APIClient } from "./client";
import {
  mockFeedbackResponse,
  mockHistoryResponse,
  mockQueryResponse,
  mockSchemaResponse
} from "../test/mocks/handlers";
import { server } from "../test/mocks/server";

test("calls query, schema, history, and feedback endpoints through MSW", async () => {
  const client = new APIClient();

  await expect(client.query({ question: "Show order count" })).resolves.toEqual(mockQueryResponse);
  await expect(client.getSchema()).resolves.toEqual(mockSchemaResponse);
  await expect(client.getHistory({ limit: 25, offset: 0 })).resolves.toEqual(mockHistoryResponse);
  await expect(
    client.submitFeedback({ request_id: "req-test-query", rating: "correct" })
  ).resolves.toEqual(mockFeedbackResponse);
});

test("converts stable backend error responses into APIClientError", async () => {
  server.use(
    http.post("*/v1/query", () =>
      HttpResponse.json(
        {
          error: {
            code: "empty_question",
            message: "Question must not be empty.",
            request_id: "req-error"
          }
        },
        { status: 422 }
      )
    )
  );

  await expect(new APIClient().query({ question: "" })).rejects.toMatchObject({
    status: 422,
    code: "empty_question",
    requestId: "req-error"
  });
});
