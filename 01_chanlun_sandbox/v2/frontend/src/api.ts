import type { AnalysisResponse, AnalyzePayload, StockInfo } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `请求失败 (${response.status})`);
  }
  return payload as T;
}

export const api = {
  stocks: async () => (await request<{ stocks: StockInfo[] }>("/api/v2/stocks")).stocks,
  analyze: (payload: AnalyzePayload) =>
    request<AnalysisResponse>("/api/v2/analyze", { method: "POST", body: JSON.stringify(payload) }),
  sync: (symbol: string) =>
    request<Record<string, unknown>>("/api/v2/sync", { method: "POST", body: JSON.stringify({ symbol }) }),
  snapshot: (analysis: AnalyzePayload, note = "") =>
    request<Record<string, unknown>>("/api/v2/snapshots", {
      method: "POST",
      body: JSON.stringify({ analysis, note }),
    }),
  export: (analysis: AnalyzePayload) =>
    request<{ path: string }>("/api/v2/export", {
      method: "POST",
      body: JSON.stringify({ analysis }),
    }),
};
