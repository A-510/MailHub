import type {
  AppSettings,
  ClassificationRule,
  EmailAccount,
  EmailDetail,
  EmailListResponse,
  ProviderPreset,
  StorageInfo,
  SyncLogItem,
} from '@/types/mail'

const API_BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(init?.headers ?? {}),
    },
  })
  if (!resp.ok) {
    let detail = `请求失败 (${resp.status})`
    try {
      const payload = await resp.json()
      if (payload?.detail) detail = String(payload.detail)
    } catch {
      // 忽略非 JSON 错误体
    }
    throw new Error(detail)
  }
  return (await resp.json()) as T
}

export const mailApi = {
  getProviders: () => request<ProviderPreset[]>('/providers'),
  detectProvider: (email: string) =>
    request<ProviderPreset>(`/providers/detect?email=${encodeURIComponent(email)}`),

  listAccounts: () => request<EmailAccount[]>('/accounts'),
  testAccount: (payload: Record<string, unknown>) =>
    request<{
      ok: boolean
      imap_ok: boolean
      smtp_ok: boolean
      message: string
      resolved_smtp_port?: number | null
      resolved_smtp_ssl?: boolean | null
    }>('/accounts/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  createAccount: (payload: Record<string, unknown>) =>
    request<EmailAccount>('/accounts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateAccount: (id: number, payload: Record<string, unknown>) =>
    request<EmailAccount>(`/accounts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteAccount: (id: number) =>
    request<{ ok: boolean }>(`/accounts/${id}`, { method: 'DELETE' }),
  reorderAccounts: (orderedIds: number[]) =>
    request<EmailAccount[]>('/accounts/reorder', {
      method: 'PUT',
      body: JSON.stringify({ ordered_ids: orderedIds }),
    }),
  syncAllAccounts: () =>
    request<{ ok: boolean; fetched: number; results: Array<{ message: string; ok: boolean }> }>(
      '/accounts/sync-all',
      { method: 'POST' },
    ),
  syncSingleAccount: (id: number) =>
    request<{ ok: boolean; fetched: number; message: string }>(`/accounts/${id}/sync`, {
      method: 'POST',
    }),

  startOAuth: (payload: { provider: 'gmail' | 'outlook'; label?: string; email_hint?: string }) =>
    request<{ state: string; auth_url: string; browser_opened: boolean }>('/oauth/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getOAuthStatus: (state: string) =>
    request<{
      state: string
      status: 'pending' | 'completed' | 'failed' | 'expired'
      message: string
      account: EmailAccount | null
    }>(`/oauth/status/${encodeURIComponent(state)}`),

  listEmails: (params: Record<string, string | number | boolean | undefined>) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') {
        qs.set(key, String(value))
      }
    })
    return request<EmailListResponse>(`/emails?${qs.toString()}`)
  },
  getEmail: (id: number) => request<EmailDetail>(`/emails/${id}`),
  patchEmail: (id: number, payload: Record<string, unknown>) =>
    request<EmailDetail>(`/emails/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteEmail: (id: number) =>
    request<{ ok: boolean }>(`/emails/${id}`, { method: 'DELETE' }),
  batchEmails: (emailIds: number[], action: string) =>
    request<{ affected: number }>('/emails/batch', {
      method: 'POST',
      body: JSON.stringify({ email_ids: emailIds, action }),
    }),
  saveDraft: (payload: Record<string, unknown>) =>
    request<EmailDetail>('/emails/drafts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  sendEmail: (formData: FormData) =>
    request<EmailDetail>('/emails/send', {
      method: 'POST',
      body: formData,
    }),

  getSettings: () => request<AppSettings>('/settings'),
  patchSettings: (payload: Partial<AppSettings>) =>
    request<AppSettings>('/settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  uploadMascot: (side: 'left' | 'right', file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<AppSettings>(`/settings/mascot/${side}`, {
      method: 'POST',
      body: form,
    })
  },
  resetMascot: (side: 'left' | 'right') =>
    request<AppSettings>(`/settings/mascot/${side}`, { method: 'DELETE' }),

  listRules: () => request<ClassificationRule[]>('/rules'),
  createRule: (payload: Omit<ClassificationRule, 'id'>) =>
    request<ClassificationRule>('/rules', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateRule: (id: number, payload: Partial<ClassificationRule>) =>
    request<ClassificationRule>(`/rules/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteRule: (id: number) =>
    request<{ ok: boolean }>(`/rules/${id}`, { method: 'DELETE' }),

  getStorageInfo: () => request<StorageInfo>('/system/storage'),
  clearCache: () => request<{ freed_bytes: number }>('/system/clear-cache', { method: 'POST' }),
  resetDemo: () => request<{ ok: boolean }>('/system/demo/reset', { method: 'POST' }),
  clearDemo: () => request<{ removed_accounts: number }>('/system/demo/clear', { method: 'POST' }),
  getNotifications: () => request<SyncLogItem[]>('/notifications'),
}
