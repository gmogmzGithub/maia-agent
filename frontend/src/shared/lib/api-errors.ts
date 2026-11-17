export type ApiIssue = { message: string; code?: string; field?: string };

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly issues: ApiIssue[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Keep field identity and every failure while retaining the existing message. */
export function responseError(
  data: Record<string, unknown>,
  status: number,
): ApiError {
  const issues: ApiIssue[] = [];
  if (Array.isArray(data.errors)) {
    for (const value of data.errors) {
      if (
        value &&
        typeof value === "object" &&
        typeof value.message === "string"
      ) {
        issues.push({
          message: value.message,
          ...(typeof value.code === "string" ? { code: value.code } : {}),
          ...(typeof value.field === "string" ? { field: value.field } : {}),
        });
      }
    }
  } else if (data.errors && typeof data.errors === "object") {
    for (const [field, messages] of Object.entries(data.errors)) {
      for (const message of [messages].flat())
        if (typeof message === "string") issues.push({ field, message });
    }
  }
  const message =
    issues[0]?.message ||
    (typeof data.detail === "string"
      ? data.detail
      : "Revisa los datos e intenta de nuevo.");
  return new ApiError(message, status, issues);
}
