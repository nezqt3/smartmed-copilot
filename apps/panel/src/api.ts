import type { Draft, Extraction, Turn } from './types'

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError('无法连接本地服务，请确认 API 已启动。', 0)
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const message = typeof detail === 'string' ? detail : detail?.message
    const code = detail?.code
    if (response.status === 409) {
      throw new ApiError('草稿已在其他页面更新，请刷新后重试。', 409)
    }
    if (response.status === 422 && code === 'invalid_evidence') {
      const errors = detail.errors?.map((item: { msg: string }) => item.msg).join('; ')
      throw new ApiError(errors || '请检查引文，必须与患者原话完全一致。', 422)
    }
    throw new ApiError(message || `服务请求失败（${response.status}${code ? `：${code}` : ''}）。`, response.status)
  }
  return response.json() as Promise<T>
}

function json(body: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const api = {
  health: () => request<{ status: string }>('/health'),
  createDraft: (turns: Turn[]) => request<Draft>('/v1/drafts', json({ turns })),
  getDraft: (id: string) => request<Draft>(`/v1/drafts/${encodeURIComponent(id)}`),
  saveDraft: (draft: Draft, document: Extraction, actor: string) =>
    request<Draft>(`/v1/drafts/${encodeURIComponent(draft.id)}`, {
      ...json({ expected_version: draft.version, actor, document }), method: 'PUT',
    }),
  confirmDraft: (draft: Draft, reviewer: string) =>
    request<Draft>(`/v1/drafts/${encodeURIComponent(draft.id)}/confirm`,
      json({ expected_version: draft.version, reviewer, reviewed: true })),
  exportDraft: (id: string) => request<Draft>(`/v1/drafts/${encodeURIComponent(id)}/export`),
  transcribe: (file: File) => request<{ text: string; speaker_labels?: string }>('/v1/audio/transcribe', {
    method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: file,
  }),
}
