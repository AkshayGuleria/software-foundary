import type { ApiResponse, ErrorEnvelope } from "./types";

export class ApiClientError extends Error {
  code: string;
  statusCode: number;
  details: unknown;

  constructor(code: string, message: string, statusCode: number, details: unknown) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.statusCode = statusCode;
    this.details = details;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<ApiResponse<T>> {
  const response = await fetch(path, init);
  const body = await response.json();

  if (!response.ok) {
    const errBody = (body as ErrorEnvelope).error;
    throw new ApiClientError(errBody.code, errBody.message, errBody.status_code, errBody.details);
  }

  return body as ApiResponse<T>;
}
