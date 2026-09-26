import type { Catalog, Mode, State } from "./types";

const SESSION_KEY = "agentgate-session";
let memorySession: string | null = null;
let starting: Promise<State> | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function sessionId(): string | null {
  if (memorySession) return memorySession;
  try {
    return sessionStorage.getItem(SESSION_KEY);
  } catch {
    return memorySession;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const id = sessionId();
  if (id) headers["X-Session-Id"] = id;
  let response: Response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Cannot reach the AgentGate server. Is the backend running?");
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = "The request was not valid.";
    } catch { /* keep the generic message */ }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

async function startSession(): Promise<State> {
  if (sessionId()) {
    try {
      return await request<State>("GET", "/api/state");
    } catch (e) {
      // A backend restart clears sessions; create a fresh one below.
      if (!(e instanceof ApiError) || e.status !== 401) throw e;
    }
  }
  const created = await request<{ session_id: string; state: State }>("POST", "/api/sessions");
  memorySession = created.session_id;
  try {
    sessionStorage.setItem(SESSION_KEY, created.session_id);
  } catch { /* Keep using memory until this page reloads. */ }
  return created.state;
}

export const api = {
  catalog: () => request<Catalog>("GET", "/api/catalog"),

  start(): Promise<State> {
    // StrictMode can mount twice; both callers should get the same session.
    starting ??= startSession().finally(() => { starting = null; });
    return starting;
  },

  state: () => request<State>("GET", "/api/state"),

  reset: (runId: number, scenario_id: string, variant_id: string, mode: Mode, attack_text?: string) =>
    request<State>("POST", "/api/reset", { expected_run_id: runId, scenario_id, variant_id, mode, attack_text: attack_text || null }),

  step: (runId: number) => request<State>("POST", "/api/step", { expected_run_id: runId }),

  approve: (runId: number, actionId: string, approve: boolean) =>
    request<State>("POST", `/api/actions/${encodeURIComponent(actionId)}/approval`, { approve, expected_run_id: runId }),

  updatePolicy: (runId: number, p: { allowed_documents: string[]; allowed_recipients: string[]; always_require_approval: boolean }) =>
    request<State>("PATCH", "/api/policy", { ...p, expected_run_id: runId }),
};
