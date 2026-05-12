export type RunRequest = {
  blf_path: string;
  dbc_path: string;
  enable_ai?: boolean;
  config_path?: string;
  output_dir?: string;
};

export type RunResponse = { task_id: string };
export type UploadResponse = { file_id: string; path: string };

export type TaskStatus = {
  task_id: string;
  status: string;
  error?: any;
  logs?: any[];
  output_dir?: string;
};

// 优先使用同源，避免端口/host 不一致导致 404；可通过 VITE_API_BASE_URL 覆盖
const API_BASE = (typeof window !== "undefined" ? window.location.origin : "") || import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const headers: Record<string, string> = isForm
    ? { ...(init?.headers as Record<string, string> | undefined) }
    : { "Content-Type": "application/json", ...(init?.headers as Record<string, string> | undefined) };

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }

  return (await res.json()) as T;
}

export async function runTask(req: RunRequest): Promise<RunResponse> {
  return http<RunResponse>("/run", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function uploadBlf(file: File): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  return http<UploadResponse>("/upload/blf", { method: "POST", body: fd });
}

export async function uploadDbc(file: File): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  return http<UploadResponse>("/upload/dbc", { method: "POST", body: fd });
}

export async function getStatus(taskId: string): Promise<TaskStatus> {
  return http<TaskStatus>(`/status/${encodeURIComponent(taskId)}`);
}

export async function getReport(taskId: string): Promise<any> {
  return http<any>(`/report/${encodeURIComponent(taskId)}`);
}

export async function getAiReport(taskId: string): Promise<any> {
  return http<any>(`/ai_report/${encodeURIComponent(taskId)}`);
}

export async function downloadOutput(taskId: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}/download/${encodeURIComponent(taskId)}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return await res.blob();
}

export async function listSignals(taskId: string): Promise<any> {
  return http<any>(`/signals?task_id=${encodeURIComponent(taskId)}`);
}

export async function getSignal(taskId: string, signal: string): Promise<any> {
  return http<any>(
    `/signals?task_id=${encodeURIComponent(taskId)}&signal=${encodeURIComponent(signal)}`,
  );
}
