const KEY = "seo_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(KEY);
}

export function setToken(token: string) {
  localStorage.setItem(KEY, token);
  // Also set as cookie so middleware can read it (30-day expiry)
  document.cookie = `${KEY}=${token}; path=/; max-age=2592000; SameSite=Lax`;
}

export function clearToken() {
  localStorage.removeItem(KEY);
  document.cookie = `${KEY}=; path=/; max-age=0`;
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Drop-in fetch replacement that injects the auth header. */
export function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = getToken();
  return fetch(url, {
    ...options,
    headers: {
      ...(options.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
}
