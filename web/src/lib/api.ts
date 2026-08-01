export type JobStatus =
  | "pending"
  | "running"
  | "completed"
  | "denied"
  | "failed"
  | "blocked"
  | "killed"

export type FileChange = {
  path: string
  size?: number
  sha256?: string
  unified_diff?: string
  binary_or_large?: boolean
}

export type FsDiff = {
  added: FileChange[]
  modified: FileChange[]
  deleted: FileChange[]
}

export type SyscallStat = {
  syscall: string
  calls: number
  errors: number
  time_pct: number
}

export type KernelEvent = {
  ts: string
  pid: string
  syscall: string
  args: string
  path: string | null
  endpoint: string | null
  ret: string | null
  category: "file" | "net" | "process" | "other"
}

export type JobResult = {
  stdout: string
  stderr: string
  exit_code: number | null
  fs_diff: FsDiff | null
  error: string | null
  operator_feedback?: string | null
  syscall_profile?: SyscallStat[] | null
  kernel_events?: KernelEvent[] | null
}

export type Job = {
  id: string
  command: string
  timeout: number
  status: JobStatus
  risk_level: string | null
  risk_reason: string | null
  container_id: string | null
  checkpoint_ref?: string | null
  shadow_path?: string | null
  created_at: string
  updated_at: string
  result: JobResult | null
}

export type EgressEvent = {
  action: "allowed" | "blocked"
  host: string
  port: number
  timestamp: string
  detail: string
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    throw new Error(`${path} → ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => json<{ status: string }>("/health"),
  pending: () => json<Job[]>("/v1/pending"),
  jobs: (limit = 30) => json<Job[]>(`/v1/jobs?limit=${limit}`),
  job: (id: string) => json<Job>(`/v1/commands/${id}`),
  egress: (limit = 40) => json<EgressEvent[]>(`/v1/egress/events?limit=${limit}`),
  approve: (id: string) =>
    json<Job>(`/v1/commands/${id}/approve`, { method: "POST" }),
  deny: (id: string, reason: string, revert = true) =>
    json<Job>(`/v1/commands/${id}/deny`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, revert }),
    }),
  revert: (id: string) =>
    json<{ ok: boolean; checkpoint_ref: string }>(
      `/v1/commands/${id}/revert`,
      { method: "POST" },
    ),
  promote: (id: string) =>
    json<{ ok: boolean; promoted: string[] }>(`/v1/commands/${id}/promote`, {
      method: "POST",
    }),
  kill: (id: string) =>
    json<Job>(`/v1/commands/${id}/kill`, { method: "POST" }),
  estop: () =>
    json<{ killed: string[]; count: number }>("/v1/estop", { method: "POST" }),
}
