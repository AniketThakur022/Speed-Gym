import { useAuthStore } from "@/stores/auth-store";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
const API_PREFIX = "/api/v1";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function getAuthHeaders(): Record<string, string> {
  const token = useAuthStore.getState().token;
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { headers: extraHeaders, ...restOptions } = options;
  const res = await fetch(`${BASE_URL}${API_PREFIX}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
      ...(extraHeaders as Record<string, string>),
    },
    ...restOptions,
  });
  if (res.status === 401) {
    const { refreshToken, setToken } = useAuthStore.getState();
    if (refreshToken) {
      try {
        const refreshRes = await fetch(`${BASE_URL}${API_PREFIX}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refreshToken }),
        });
        if (refreshRes.ok) {
          const { token: newToken } = await refreshRes.json();
          setToken(newToken);
          options.headers = {
            "Content-Type": "application/json",
            Authorization: `Bearer ${newToken}`,
            ...(extraHeaders as Record<string, string>),
          };
          const retryRes = await fetch(`${BASE_URL}${API_PREFIX}${path}`, options);
          if (!retryRes.ok) throw new ApiError(retryRes.status, `API error: ${retryRes.status}`);
          return retryRes.json();
        }
      } catch {
        throw new ApiError(401, "Session expired");
      }
    }
    throw new ApiError(401, "Unauthorized");
  }
  if (!res.ok) {
    throw new ApiError(res.status, `API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function apiGet<T>(path: string, options?: RequestInit): Promise<T> {
  return request<T>(path, { ...options, method: "GET" });
}

export async function apiPost<T>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
  return request<T>(path, {
    ...options,
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function apiPut<T>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
  return request<T>(path, {
    ...options,
    method: "PUT",
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function apiDelete<T>(path: string, options?: RequestInit): Promise<T> {
  return request<T>(path, { ...options, method: "DELETE" });
}
