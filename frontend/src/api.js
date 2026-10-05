const BASE_URL = "http://127.0.0.1:8000/api";

export function getToken() {
  return localStorage.getItem("token");
}

export function getUser() {
  const raw = localStorage.getItem("user");
  return raw ? JSON.parse(raw) : null;
}

export function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
}

/**
 * Core request helper. Attaches the token automatically once logged in.
 * Throws an Error with a readable message on any non-2xx response so
 * pages can just try/catch and show err.message.
 */
export async function apiFetch(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Token ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    // DRF error bodies vary in shape ({"detail": "..."} vs field errors) — flatten whatever we got.
    const message =
      (data && (data.detail || JSON.stringify(data))) || `Request failed (${res.status})`;
    throw new Error(message);
  }

  return data;
}

/** Logs in against /token-auth/, then fetches /me/ to get the role, and stores both. */
export async function login(username, password) {
  const tokenRes = await fetch(`${BASE_URL}/token-auth/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!tokenRes.ok) {
    throw new Error("Invalid username or password.");
  }

  const { token } = await tokenRes.json();
  localStorage.setItem("token", token);

  const me = await apiFetch("/me/");
  localStorage.setItem("user", JSON.stringify(me));

  return me;
}