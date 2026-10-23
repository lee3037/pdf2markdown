export interface Options {
  separator: string;
  target_size: number;
  include_source: boolean;
}
export interface Chunk {
  index: number;
  markdown: string;
  section: string;
  characters: number;
  oversized: boolean;
}
export interface Task {
  id: string;
  filename: string;
  pages: number;
  size: number;
  status: "queued" | "processing" | "completed" | "failed";
  stage: string;
  progress: number;
  created_at: string;
  updated_at: string;
  markdown: string | null;
  settings: Options;
  revision: number;
  edited: boolean;
  error: string | null;
  error_code: string | null;
  mode: "mock" | "remote";
  upstream_id: string | null;
  submission_started: boolean;
  metadata: {
    structured?: boolean;
    block_count?: number;
    producer_version?: string;
    backend?: string;
    cached?: boolean;
    elapsed_seconds?: number;
    warnings?: string[];
  };
  chunks?: Chunk[];
}
export interface Health {
  mode: string;
  max_upload_mb: number;
  max_pdf_pages: number;
}

export interface MinerUStatus {
  available: boolean;
  mode: string;
  version?: string;
  style?: string;
  message: string;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, init);
  } catch {
    throw new Error("无法连接本机后端，请检查 API 服务是否已启动。");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : "请求未完成，请检查输入或稍后重试。",
    );
  }
  return response.json();
}
