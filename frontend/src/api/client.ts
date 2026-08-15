import type {
  APIErrorBody,
  DatabaseSchemaResponse,
  FeedbackRequest,
  HealthResponse,
  QueryFeedbackResponse,
  QueryHistoryResponse,
  QueryRequest,
  QueryResponse
} from "../types/api";

const DEFAULT_API_BASE_URL = "";

export class APIClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(message: string, status: number, code: string, requestId: string | null) {
    super(message);
    this.name = "APIClientError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export interface APIClientOptions {
  baseUrl?: string;
  fetcher?: typeof fetch;
}

export class APIClient {
  private readonly baseUrl: string;
  private readonly fetcher: typeof fetch;

  constructor(options: APIClientOptions = {}) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? getConfiguredBaseUrl());
    this.fetcher = options.fetcher ?? ((input, init) => fetch(input, init));
  }

  getHealth(): Promise<HealthResponse> {
    return this.request<HealthResponse>("/health");
  }

  query(payload: QueryRequest): Promise<QueryResponse> {
    return this.request<QueryResponse>("/v1/query", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  }

  getSchema(options: { refresh?: boolean } = {}): Promise<DatabaseSchemaResponse> {
    const params = new URLSearchParams();
    if (options.refresh === true) {
      params.set("refresh", "true");
    }
    return this.request<DatabaseSchemaResponse>(`/v1/schema${queryString(params)}`);
  }

  getHistory(options: { limit?: number; offset?: number } = {}): Promise<QueryHistoryResponse> {
    const params = new URLSearchParams();
    if (options.limit !== undefined) {
      params.set("limit", String(options.limit));
    }
    if (options.offset !== undefined) {
      params.set("offset", String(options.offset));
    }
    return this.request<QueryHistoryResponse>(`/v1/history${queryString(params)}`);
  }

  submitFeedback(payload: FeedbackRequest): Promise<QueryFeedbackResponse> {
    return this.request<QueryFeedbackResponse>("/v1/feedback", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }

    const response = await this.fetcher(resolveUrl(this.baseUrl, path), {
      ...init,
      headers
    });

    if (!response.ok) {
      throw await toAPIClientError(response);
    }

    return (await response.json()) as T;
  }
}

export const apiClient = new APIClient();

function getConfiguredBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/$/, "");
}

function resolveUrl(baseUrl: string, path: string): string {
  if (baseUrl.length > 0) {
    return `${baseUrl}${path}`;
  }

  if ("location" in globalThis) {
    return new URL(path, globalThis.location.origin).toString();
  }

  return path;
}

function queryString(params: URLSearchParams): string {
  const value = params.toString();
  return value.length > 0 ? `?${value}` : "";
}

async function toAPIClientError(response: Response): Promise<APIClientError> {
  const fallbackMessage = `Request failed with status ${String(response.status)}`;

  try {
    const body = (await response.json()) as Partial<APIErrorBody>;
    const error = body.error;
    if (error !== undefined) {
      return new APIClientError(error.message, response.status, error.code, error.request_id);
    }
  } catch {
    // Fall through to the stable client-side error when the server body is not JSON.
  }

  return new APIClientError(fallbackMessage, response.status, "http_error", null);
}
