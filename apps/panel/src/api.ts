import { currentLocale, translate } from './i18n'
import type { Draft, Extraction, Turn } from './types'

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message)
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    const headers = new Headers(init?.headers)
    const token = sessionStorage.getItem('smartmed_token')
    if (token) headers.set('Authorization', `Bearer ${token}`)
    response = await fetch(path, { ...init, headers })
  } catch {
    throw new ApiError(translate('无法连接本地服务，请确认 API 已启动。', currentLocale()), 0)
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const message = typeof detail === 'string' ? detail : detail?.message
    const code = detail?.code
    if (code === 'resolve_conflicts_before_review') {
      throw new ApiError(translate('请先核对并解决冲突，再保存和审核病历。', currentLocale()), response.status)
    }
    if (code === 'model_busy') {
      throw new ApiError(translate('模型正忙，请稍后重试自动区分。', currentLocale()), response.status)
    }
    if (code === 'invalid_speaker_assignment' || code === 'model_timeout') {
      throw new ApiError(translate('自动区分角色失败，请重试。识别文字已保留。', currentLocale()), response.status)
    }
    if (code === 'invalid_transcript') {
      throw new ApiError(translate('自动分角色最多支持1200字；识别文字已保留。', currentLocale()), response.status)
    }
    if (code === 'review_required' || code === 'section_review_required') {
      throw new ApiError(translate('请先审核并确认已保存的病历。', currentLocale()), response.status)
    }
    if (response.status === 409) {
      throw new ApiError(translate('草稿已在其他页面更新，请刷新后重试。', currentLocale()), 409)
    }
    if (response.status === 422 && code === 'invalid_evidence') {
      const errors = detail.errors?.map((item: { msg: string }) => item.msg).join('; ')
      throw new ApiError(errors || translate('请检查引文，必须与患者原话完全一致。', currentLocale()), 422)
    }
    throw new ApiError(message || `${translate('服务请求失败', currentLocale())} (${response.status}${code ? `: ${code}` : ''})`, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function json(body: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const api = {
  login: (staff_id: string, passcode: string) => request<{ access_token: string }>('/v1/auth/login', json({ staff_id, passcode })),
  safety: (id: string) => request<{ alerts: {code: string; message: string; requires_acknowledgement: boolean}[]; required_acknowledgements: string[] }>(`/v1/drafts/${encodeURIComponent(id)}/safety`),
  health: () => request<{ status: string }>('/health'),
  createDraft: (turns: Turn[]) => request<Draft>('/v1/drafts', json({ turns })),
  getDraft: (id: string) => request<Draft>(`/v1/drafts/${encodeURIComponent(id)}`),
  saveDraft: (draft: Draft, document: Extraction, actor: string) =>
    request<Draft>(`/v1/drafts/${encodeURIComponent(draft.id)}`, {
      ...json({ expected_version: draft.version, actor, document }), method: 'PUT',
    }),
  confirmDraft: (draft: Draft, reviewer: string, acknowledged_alerts: string[]) =>
    request<Draft>(`/v1/drafts/${encodeURIComponent(draft.id)}/confirm`,
      json({ expected_version: draft.version, reviewer, reviewed: true, acknowledged_alerts })),
  exportDraft: (id: string) => request<Draft>(`/v1/drafts/${encodeURIComponent(id)}/export`),
  transcribe: (file: File) => request<{ text: string; speaker_labels?: string }>('/v1/audio/transcribe', {
    method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: file,
  }),
  assignSpeakers: (text: string) => request<{
    text: string
    turns: Turn[]
    uncertain_turn_ids: number[]
    speaker_labels: 'inferred_from_text'
  }>('/v1/audio/assign-speakers', json({ text })),
}
