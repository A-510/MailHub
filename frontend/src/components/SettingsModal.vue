<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { motion } from 'motion-v'
import {
  ArrowDown,
  ArrowUp,
  Bell,
  Bug,
  CheckCircle2,
  Copy,
  Database,
  ExternalLink,
  Globe,
  HardDriveDownload,
  Info,
  MailPlus,
  Palette,
  RefreshCw,
  Shield,
  Sliders,
  Trash2,
  Upload,
  X,
} from 'lucide-vue-next'
import ProviderBadge from '@/components/ProviderBadge.vue'
import { mailApi } from '@/api/client'
import { useMailStore } from '@/stores/mailStore'
import { useTheme } from '@/composables/useTheme'
import { useBookMotion } from '@/composables/useBookMotion'
import type { DiagnosticsInfo, EmailAccount, ProviderType, StorageInfo } from '@/types/mail'

const store = useMailStore()
const { setThemeWithTransition } = useTheme()
const { motionMode } = useBookMotion()

const tabs = [
  { id: 'accounts', label: '邮箱渠道', icon: MailPlus },
  { id: 'appearance', label: '外观与氛围', icon: Palette },
  { id: 'sync', label: '收发与规则', icon: Sliders },
  { id: 'notifications', label: '通知提醒', icon: Bell },
  { id: 'privacy', label: '隐私与数据', icon: Shield },
  { id: 'diagnostics', label: '关于与诊断', icon: Info },
] as const

// 添加邮箱表单状态
const authMode = ref<'password' | 'oauth2'>('password')
const newForm = reactive({
  label: '',
  email: '',
  provider: 'custom' as ProviderType,
  secret: '',
  imap_host: '',
  imap_port: 993,
  imap_ssl: true,
  smtp_host: '',
  smtp_port: 465,
  smtp_ssl: true,
  badge_color: '#8B6CE8',
  signature: '',
})
const showAdvancedServer = ref(false)
const testStatus = ref<{ ok: boolean; text: string } | null>(null)
const testingConn = ref(false)
const creatingAccount = ref(false)

// OAuth 轮询状态
const oauthPendingState = ref<string | null>(null)
const oauthUrl = ref('')
const oauthStatusText = ref('')
let oauthPollTimer: number | null = null

// 正在编辑签名或更新授权码的账号
const editingSignatureId = ref<number | null>(null)
const editingSignatureText = ref('')
const editingSecretId = ref<number | null>(null)
const editingSecretText = ref('')
const updatingSecret = ref(false)
const secretUpdateErr = ref('')
const syncingAccountId = ref<number | null>(null)

// OAuth2 Client ID 局部草稿
const oauthDraft = reactive({
  googleId: '',
  googleSecret: '',
  msId: '',
})

// 新规则表单
const newRule = reactive({
  name: '',
  field: 'sender_email' as 'sender_email' | 'sender_name' | 'subject',
  pattern: '',
  target_category: 'work' as 'work' | 'study' | 'social' | 'subscription',
})

const storageInfo = ref<StorageInfo | null>(null)
const diagnosticsInfo = ref<DiagnosticsInfo | null>(null)
const loadingDiagnostics = ref(false)
const diagnosticsError = ref('')

const GITHUB_REPO_URL = 'https://github.com/A-510/MailHub'
const GITHUB_ISSUES_URL = 'https://github.com/A-510/MailHub/issues/new/choose'
const GITHUB_FAQ_URL = 'https://github.com/A-510/MailHub#%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98'
const GITHUB_PROVIDER_GUIDE_URL =
  'https://github.com/A-510/MailHub/blob/main/docs/guide/email-providers-and-oauth2.md'

const currentPreset = computed(() =>
  store.providers.find((p) => p.id === newForm.provider) ?? null,
)

const passwordFieldLabel = computed(() => {
  if (newForm.provider === 'gmail') {
    return 'Google 16 位应用专用密码（非 Google 账户登录密码，含空格将自动去除）'
  }
  if (newForm.provider === 'qq' || newForm.provider === '163' || newForm.provider === '126') {
    return '客户端授权码（Fernet 加密保存）'
  }
  return '邮箱密码 / 客户端授权码（Fernet 加密保存）'
})

const passwordFieldPlaceholder = computed(() => {
  if (newForm.provider === 'gmail') {
    return '请填入 Google 16 位应用专用密码（如 abcd efgh ijkl mnop）'
  }
  if (newForm.provider === 'qq' || newForm.provider === '163' || newForm.provider === '126') {
    return '请填入网页端生成的客户端授权码（非邮箱登录密码）'
  }
  return '请输入邮箱密码或客户端授权码'
})

function applyPresetDefaults(providerId: ProviderType): void {
  newForm.provider = providerId
  testStatus.value = null
  const preset = store.providers.find((p) => p.id === providerId)
  if (!preset) return
  newForm.imap_host = preset.imap_host
  newForm.imap_port = preset.imap_port
  newForm.imap_ssl = preset.imap_ssl
  newForm.smtp_host = preset.smtp_host
  newForm.smtp_port = preset.smtp_port
  newForm.smtp_ssl = preset.smtp_ssl
  newForm.badge_color = preset.badge_color
  if (!preset.imap_host || !preset.smtp_host) {
    showAdvancedServer.value = true
  }
  const trimmedLabel = newForm.label.trim()
  const isAutoLabel = !trimmedLabel || store.providers.some((p) => p.name === trimmedLabel)
  if (isAutoLabel) {
    newForm.label = preset.name
  }
}

function resetNewAccountForm(): void {
  newForm.label = ''
  newForm.email = ''
  newForm.secret = ''
  newForm.signature = ''
  applyPresetDefaults('custom')
  showAdvancedServer.value = false
}

async function handleEmailAutoDetect(): Promise<void> {
  if (!newForm.email.includes('@')) return
  try {
    const detected = await mailApi.detectProvider(newForm.email)
    applyPresetDefaults(detected.id)
    // 若当前在 OAuth2 标签页但识别出不支持 OAuth2 的邮箱（如 QQ/163/iCloud），切回密码授权码表单；
    // 若用户主动在密码表单使用 Gmail 应用专用密码，保持在密码模式避免打断输入。
    if (!detected.supports_oauth && authMode.value === 'oauth2') {
      authMode.value = 'password'
    }
  } catch {
    // 忽略局部输入错误
  }
}

async function handleTestConnection(): Promise<void> {
  if (!newForm.email || !newForm.secret) {
    testStatus.value = { ok: false, text: '请先填写邮箱地址和授权码/密码。' }
    return
  }
  testingConn.value = true
  testStatus.value = null
  try {
    const res = await mailApi.testAccount({
      email: newForm.email,
      provider: newForm.provider,
      secret: newForm.secret,
      imap_host: newForm.imap_host,
      imap_port: newForm.imap_port,
      imap_ssl: newForm.imap_ssl,
      smtp_host: newForm.smtp_host,
      smtp_port: newForm.smtp_port,
      smtp_ssl: newForm.smtp_ssl,
    })
    if (res.ok && res.resolved_smtp_port != null && res.resolved_smtp_ssl != null) {
      newForm.smtp_port = res.resolved_smtp_port
      newForm.smtp_ssl = res.resolved_smtp_ssl
    }
    testStatus.value = { ok: res.ok, text: res.message }
  } catch (err) {
    testStatus.value = { ok: false, text: (err as Error).message }
  } finally {
    testingConn.value = false
  }
}

async function handleAddPasswordAccount(): Promise<void> {
  if (!newForm.email || !newForm.secret) {
    testStatus.value = { ok: false, text: '请先填写完整邮箱地址与授权码/密码。' }
    store.pushToast('请填写完整邮箱地址和密码/授权码', 'error')
    return
  }
  creatingAccount.value = true
  testStatus.value = null
  try {
    const created = await mailApi.createAccount({
      label: newForm.label.trim() || newForm.email.split('@')[0],
      email: newForm.email.trim(),
      provider: newForm.provider,
      auth_type: 'password',
      secret: newForm.secret,
      imap_host: newForm.imap_host,
      imap_port: newForm.imap_port,
      imap_ssl: newForm.imap_ssl,
      smtp_host: newForm.smtp_host,
      smtp_port: newForm.smtp_port,
      smtp_ssl: newForm.smtp_ssl,
      badge_color: newForm.badge_color,
      signature: newForm.signature,
      verify_connection: true,
    })
    resetNewAccountForm()
    testStatus.value = { ok: true, text: `「${created.label}」连接验证通过，正在首次收信…` }
    await store.refreshAccounts()
    const syncRes = await mailApi.syncSingleAccount(created.id)
    await Promise.all([store.refreshAccounts(), store.fetchEmails({ selectFirst: true })])
    if (syncRes.ok) {
      store.pushToast(`已添加「${created.label}」，同步获取 ${syncRes.fetched} 封邮件`, 'success')
    } else {
      testStatus.value = { ok: false, text: syncRes.message }
      store.pushToast(syncRes.message, 'error')
    }
  } catch (err) {
    const errMsg = (err as Error).message
    testStatus.value = { ok: false, text: errMsg }
    store.pushToast(errMsg, 'error')
  } finally {
    creatingAccount.value = false
  }
}

function stopOAuthPoll(): void {
  if (oauthPollTimer !== null) {
    window.clearInterval(oauthPollTimer)
    oauthPollTimer = null
  }
}

async function handleStartOAuth(provider: 'gmail' | 'outlook'): Promise<void> {
  stopOAuthPoll()
  try {
    const res = await mailApi.startOAuth({
      provider,
      label: newForm.label.trim() || (provider === 'gmail' ? 'Gmail' : 'Outlook'),
      email_hint: newForm.email.trim(),
    })
    oauthPendingState.value = res.state
    oauthUrl.value = res.auth_url
    oauthStatusText.value = res.browser_opened
      ? '已自动唤起系统浏览器，请在浏览器完成登录后返回此页面…'
      : '请点击下方链接在浏览器中完成登录授权…'

    oauthPollTimer = window.setInterval(async () => {
      if (!oauthPendingState.value) return
      try {
        const status = await mailApi.getOAuthStatus(oauthPendingState.value)
        oauthStatusText.value = status.message
        if (status.status === 'completed') {
          stopOAuthPoll()
          oauthPendingState.value = null
          oauthUrl.value = ''
          oauthStatusText.value = ''
          store.pushToast(status.message, 'success')
          await store.refreshAccounts()
          if (status.account?.id) {
            const syncRes = await mailApi.syncSingleAccount(status.account.id)
            await Promise.all([store.refreshAccounts(), store.fetchEmails({ selectFirst: true })])
            if (!syncRes.ok) {
              store.pushToast(syncRes.message, 'error')
            }
          }
        } else if (status.status === 'failed' || status.status === 'expired') {
          stopOAuthPoll()
          store.pushToast(status.message, 'error')
        }
      } catch (err) {
        stopOAuthPoll()
        store.pushToast((err as Error).message, 'error')
      }
    }, 1500)
  } catch (err) {
    store.pushToast((err as Error).message, 'error')
  }
}

async function saveOAuthClientConfig(): Promise<void> {
  await store.updateSettings({
    oauth_google_client_id: oauthDraft.googleId.trim(),
    oauth_google_client_secret: oauthDraft.googleSecret.trim(),
    oauth_microsoft_client_id: oauthDraft.msId.trim(),
  })
  store.pushToast('OAuth2 客户端配置已保存', 'success')
}

async function moveAccountOrder(index: number, delta: -1 | 1): Promise<void> {
  const list = [...store.accounts]
  const targetIdx = index + delta
  if (targetIdx < 0 || targetIdx >= list.length) return
  const [moved] = list.splice(index, 1)
  list.splice(targetIdx, 0, moved)
  store.accounts = await mailApi.reorderAccounts(list.map((a) => a.id))
}

async function handleDeleteAccount(acc: EmailAccount): Promise<void> {
  await mailApi.deleteAccount(acc.id)
  if (store.selectedAccountId === acc.id) {
    store.selectedAccountId = null
  }
  store.pushToast(`已删除邮箱「${acc.label}」`, 'success')
  await Promise.all([store.refreshAccounts(), store.fetchEmails({ selectFirst: true })])
}

function beginEditSignature(acc: EmailAccount): void {
  editingSecretId.value = null
  editingSignatureId.value = acc.id
  editingSignatureText.value = acc.signature
}

async function saveSignature(acc: EmailAccount): Promise<void> {
  await mailApi.updateAccount(acc.id, { signature: editingSignatureText.value })
  acc.signature = editingSignatureText.value
  editingSignatureId.value = null
  store.pushToast('邮箱签名已保存', 'success')
}

function getProviderGuideUrl(provider: string): string {
  return store.providers.find((p) => p.id === provider)?.auth_guide_url ?? ''
}

function beginEditSecret(acc: EmailAccount): void {
  editingSignatureId.value = null
  editingSecretId.value = acc.id
  editingSecretText.value = ''
  secretUpdateErr.value = ''
}

async function handleSyncSingleAccount(acc: EmailAccount): Promise<void> {
  syncingAccountId.value = acc.id
  try {
    const res = await mailApi.syncSingleAccount(acc.id)
    await Promise.all([store.refreshAccounts(), store.fetchEmails()])
    store.notifications = await mailApi.getNotifications()
    if (res.ok) {
      store.pushToast(res.message, 'success')
    } else {
      store.pushToast(res.message, 'error')
    }
  } catch (err) {
    store.pushToast((err as Error).message, 'error')
  } finally {
    syncingAccountId.value = null
  }
}

async function saveUpdatedSecret(acc: EmailAccount): Promise<void> {
  if (!editingSecretText.value.trim()) {
    secretUpdateErr.value = '请输入新的授权码或应用专用密码。'
    return
  }
  updatingSecret.value = true
  secretUpdateErr.value = ''
  try {
    const testRes = await mailApi.testAccount({
      email: acc.email,
      provider: acc.provider,
      secret: editingSecretText.value,
      imap_host: acc.imap_host,
      imap_port: acc.imap_port,
      imap_ssl: acc.imap_ssl,
      smtp_host: acc.smtp_host,
      smtp_port: acc.smtp_port,
      smtp_ssl: acc.smtp_ssl,
    })
    if (!testRes.ok) {
      secretUpdateErr.value = testRes.message
      return
    }
    const updatePayload: Record<string, unknown> = { secret: editingSecretText.value }
    if (
      testRes.resolved_smtp_port != null &&
      testRes.resolved_smtp_ssl != null &&
      (testRes.resolved_smtp_port !== acc.smtp_port || testRes.resolved_smtp_ssl !== acc.smtp_ssl)
    ) {
      updatePayload.smtp_port = testRes.resolved_smtp_port
      updatePayload.smtp_ssl = testRes.resolved_smtp_ssl
    }
    await mailApi.updateAccount(acc.id, updatePayload)
    editingSecretId.value = null
    editingSecretText.value = ''
    await handleSyncSingleAccount(acc)
  } catch (err) {
    secretUpdateErr.value = (err as Error).message
  } finally {
    updatingSecret.value = false
  }
}

async function handleUploadMascot(side: 'left' | 'right', event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    store.settings = await mailApi.uploadMascot(side, file)
    store.pushToast('已更新自定义立绘', 'success')
  } catch (err) {
    store.pushToast((err as Error).message, 'error')
  } finally {
    input.value = ''
  }
}

async function handleResetMascot(side: 'left' | 'right'): Promise<void> {
  store.settings = await mailApi.resetMascot(side)
  store.pushToast('已恢复默认立绘', 'info')
}

async function handleAddRule(): Promise<void> {
  if (!newRule.name.trim() || !newRule.pattern.trim()) {
    store.pushToast('请填写规则名称与匹配关键词', 'error')
    return
  }
  const created = await mailApi.createRule({
    name: newRule.name.trim(),
    field: newRule.field,
    pattern: newRule.pattern.trim(),
    target_category: newRule.target_category,
    is_enabled: true,
  })
  store.rules.push(created)
  newRule.name = ''
  newRule.pattern = ''
  store.pushToast('已新增自动分类规则', 'success')
}

async function handleDeleteRule(id: number): Promise<void> {
  await mailApi.deleteRule(id)
  store.rules = store.rules.filter((r) => r.id !== id)
}

async function loadStorage(): Promise<void> {
  storageInfo.value = await mailApi.getStorageInfo()
}

async function loadDiagnostics(): Promise<void> {
  loadingDiagnostics.value = true
  diagnosticsError.value = ''
  try {
    diagnosticsInfo.value = await mailApi.getDiagnostics()
  } catch (err) {
    diagnosticsError.value = (err as Error).message
  } finally {
    loadingDiagnostics.value = false
  }
}

async function copyTextSafe(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 回退至隐藏文本域复制
  }
  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const copied = document.execCommand('copy')
    document.body.removeChild(area)
    return copied
  } catch {
    return false
  }
}

async function handleCopyEventId(): Promise<void> {
  if (!diagnosticsInfo.value) return
  const ok = await copyTextSafe(diagnosticsInfo.value.event_id)
  store.pushToast(ok ? `已复制 Event ID：${diagnosticsInfo.value.event_id}` : '复制失败，请手动选中复制', ok ? 'success' : 'error')
}

async function handleCopyDiagnosticReport(): Promise<void> {
  if (!diagnosticsInfo.value) return
  const ok = await copyTextSafe(diagnosticsInfo.value.markdown_report)
  store.pushToast(
    ok ? '已复制脱敏诊断报告（Markdown），可直接粘贴到 GitHub Issue' : '复制失败，请展开下方预览手动复制',
    ok ? 'success' : 'error',
  )
}

const diagnosticBundleUrl = computed(() =>
  mailApi.getDiagnosticBundleUrl(diagnosticsInfo.value?.event_id),
)

const secretModeLabel = computed(() => {
  const mode = diagnosticsInfo.value?.secret_key_mode
  if (mode === 'env') return '环境变量 (MAILHUB_SECRET_KEY)'
  if (mode === 'file') return '本地密钥文件 (data/.secret.key)'
  return '尚未初始化'
})

async function handleClearCache(): Promise<void> {
  const res = await mailApi.clearCache()
  await loadStorage()
  store.pushToast(`已清理 ${(res.freed_bytes / 1024).toFixed(1)} KB 附件缓存`, 'success')
}

async function handleClearDemo(): Promise<void> {
  const res = await mailApi.clearDemo()
  store.selectedAccountId = null
  await Promise.all([store.refreshAccounts(), store.fetchEmails({ selectFirst: true }), loadStorage()])
  store.pushToast(`已清空 ${res.removed_accounts} 个演示邮箱及示例邮件`, 'success')
}

function handleResetDemo(): Promise<void> {
  return mailApi.resetDemo().then(async () => {
    store.selectedAccountId = null
    await Promise.all([store.refreshAccounts(), store.fetchEmails({ selectFirst: true }), loadStorage()])
    store.pushToast('已恢复默认演示邮箱与示例邮件', 'success')
  })
}

function handleToggleDesktopNotifications(): void {
  const next = !store.settings.desktop_notifications
  void store.updateSettings({ desktop_notifications: next })
  if (next && typeof Notification !== 'undefined' && Notification.permission === 'default') {
    void Notification.requestPermission().catch(() => {})
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

watch(
  () => [store.settingsOpen, store.settingsTab],
  ([open, tab]) => {
    if (open) {
      oauthDraft.googleId = store.settings.oauth_google_client_id
      oauthDraft.googleSecret = store.settings.oauth_google_client_secret
      oauthDraft.msId = store.settings.oauth_microsoft_client_id
      if (tab === 'privacy') {
        void loadStorage()
      } else if (tab === 'diagnostics') {
        void loadDiagnostics()
      }
    } else {
      stopOAuthPoll()
    }
  },
)

function handleKeydown(event: KeyboardEvent): void {
  if (store.onboardingOpen) return
  if (event.key === 'Escape' && store.settingsOpen) {
    store.settingsOpen = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  stopOAuthPoll()
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div
    v-if="store.settingsOpen"
    class="modal-backdrop"
    role="dialog"
    aria-modal="true"
    aria-label="MailHub 设置中心"
    @click.self="!store.onboardingOpen && (store.settingsOpen = false)"
  >
    <motion.div
      class="settings-modal"
      :initial="motionMode === 'off' ? false : { opacity: 0, scale: 0.96, y: 12 }"
      :animate="{ opacity: 1, scale: 1, y: 0 }"
      :transition="motionMode === 'off' ? { duration: 0 } : { duration: 0.22 }"
    >
      <!-- 左侧导航栏 -->
      <aside class="settings-nav">
        <div class="nav-title">设置中心</div>
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          class="nav-item"
          :class="{ active: store.settingsTab === tab.id }"
          @click="store.settingsTab = tab.id"
        >
          <component :is="tab.icon" :size="16" />
          <span>{{ tab.label }}</span>
        </button>
      </aside>

      <!-- 右侧内容区 -->
      <div class="settings-content-wrap">
        <div class="settings-top-header">
          <h3>{{ tabs.find((t) => t.id === store.settingsTab)?.label }}</h3>
          <button type="button" class="close-btn" aria-label="关闭设置" @click="store.settingsOpen = false">
            <X :size="18" />
          </button>
        </div>

        <div class="settings-body soft-scroll">
          <!-- TAB 1: 邮箱渠道管理 -->
          <div v-if="store.settingsTab === 'accounts'" class="tab-section">
            <div class="panel-card">
              <div class="card-heading">
                <span>添加新邮箱渠道</span>
                <div class="mode-switch">
                  <button
                    type="button"
                    :class="{ active: authMode === 'password' }"
                    @click="authMode = 'password'"
                  >
                    账号密码 / 授权码
                  </button>
                  <button
                    type="button"
                    :class="{ active: authMode === 'oauth2' }"
                    @click="authMode = 'oauth2'"
                  >
                    <Globe :size="13" />
                    <span>跳转浏览器登录</span>
                  </button>
                </div>
              </div>

              <!-- 快捷预设选择（新手引导锚点 3） -->
              <div class="tour-anchor-block" data-tour="provider-presets">
                <div class="preset-chips">
                  <button
                    v-for="preset in store.providers"
                    :key="preset.id"
                    type="button"
                    class="preset-chip"
                    :class="{ active: newForm.provider === preset.id }"
                    @click="applyPresetDefaults(preset.id)"
                  >
                    {{ preset.name }}
                  </button>
                </div>

                <div v-if="currentPreset" class="guide-tip">
                  <span>{{ currentPreset.auth_guide_tip }}</span>
                  <a
                    v-if="currentPreset.auth_guide_url"
                    :href="currentPreset.auth_guide_url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    前往官方获取授权 <ExternalLink :size="12" />
                  </a>
                </div>
              </div>

              <!-- 认证表单区域（新手引导锚点 4） -->
              <div class="tour-anchor-block" data-tour="account-auth-area">
              <!-- 密码/授权码登录表单 -->
              <div v-if="authMode === 'password'" class="form-grid">
                <label>
                  <span>邮箱地址</span>
                  <input
                    v-model="newForm.email"
                    type="email"
                    placeholder="例如 name@qq.com 或 name@163.com"
                    @blur="handleEmailAutoDetect"
                  />
                </label>
                <label>
                  <span>显示名称 / 别名</span>
                  <input v-model="newForm.label" type="text" placeholder="如：个人主邮箱、工作邮箱" />
                </label>
                <label class="span-2">
                  <span>{{ passwordFieldLabel }}</span>
                  <input
                    v-model="newForm.secret"
                    type="password"
                    :placeholder="passwordFieldPlaceholder"
                  />
                </label>

                <div class="span-2 server-toggle-row">
                  <button type="button" class="link-btn" @click="showAdvancedServer = !showAdvancedServer">
                    {{ showAdvancedServer ? '收起 IMAP / SMTP 服务器参数' : '展开自定义 IMAP / SMTP 服务器参数' }}
                  </button>
                  <label class="color-picker-label">
                    <span>徽标色</span>
                    <input v-model="newForm.badge_color" type="color" />
                  </label>
                </div>

                <template v-if="showAdvancedServer">
                  <label>
                    <span>IMAP 服务器</span>
                    <input v-model="newForm.imap_host" type="text" placeholder="imap.example.com" />
                  </label>
                  <label>
                    <span>IMAP 端口 / SSL</span>
                    <div class="port-ssl">
                      <input v-model.number="newForm.imap_port" type="number" />
                      <label><input v-model="newForm.imap_ssl" type="checkbox" /> SSL</label>
                    </div>
                  </label>
                  <label>
                    <span>SMTP 服务器</span>
                    <input v-model="newForm.smtp_host" type="text" placeholder="smtp.example.com" />
                  </label>
                  <label>
                    <span>SMTP 端口 / SSL</span>
                    <div class="port-ssl">
                      <input v-model.number="newForm.smtp_port" type="number" />
                      <label><input v-model="newForm.smtp_ssl" type="checkbox" /> SSL</label>
                    </div>
                  </label>
                </template>

                <div v-if="newForm.provider === 'outlook'" class="span-2 status-banner err">
                  微软 Outlook 已停用基础密码登录，请点击上方「跳转浏览器登录」使用 Microsoft OAuth2 授权。
                </div>

                <div v-if="testStatus" class="span-2 status-banner" :class="testStatus.ok ? 'ok' : 'err'">
                  {{ testStatus.text }}
                </div>

                <div class="span-2 form-actions">
                  <button type="button" class="btn-outline" :disabled="testingConn" @click="handleTestConnection">
                    {{ testingConn ? '正在连接测试…' : '测试 IMAP/SMTP 连接' }}
                  </button>
                  <button type="button" class="btn-primary" :disabled="creatingAccount" @click="handleAddPasswordAccount">
                    {{ creatingAccount ? '正在验证并保存…' : '验证并添加邮箱' }}
                  </button>
                </div>
              </div>

              <!-- 跳转浏览器 OAuth2 PKCE 登录面板 -->
              <div v-else class="oauth-box">
                <div class="form-grid">
                  <label>
                    <span>邮箱提示（可选）</span>
                    <input v-model="newForm.email" type="email" placeholder="yourname@gmail.com" />
                  </label>
                  <label>
                    <span>自定义别名</span>
                    <input v-model="newForm.label" type="text" placeholder="例如：我的 Gmail" />
                  </label>
                </div>

                <div class="oauth-btn-row">
                  <button type="button" class="btn-primary" @click="handleStartOAuth('gmail')">
                    <Globe :size="15" />
                    <span>打开浏览器登录 Google (Gmail)</span>
                  </button>
                  <button type="button" class="btn-outline" @click="handleStartOAuth('outlook')">
                    <Globe :size="15" />
                    <span>打开浏览器登录 Microsoft (Outlook)</span>
                  </button>
                </div>

                <div v-if="oauthStatusText" class="oauth-status">
                  <span>{{ oauthStatusText }}</span>
                  <a v-if="oauthUrl" :href="oauthUrl" target="_blank" rel="noopener noreferrer">
                    手动打开授权页 <ExternalLink :size="12" />
                  </a>
                </div>

                <details class="oauth-config-details">
                  <summary>OAuth2 Client ID 开发者配置（首次使用浏览器登录前填入）</summary>
                  <div class="form-grid" style="margin-top: 10px">
                    <label>
                      <span>Google Client ID (Desktop App)</span>
                      <input v-model="oauthDraft.googleId" type="text" placeholder="xxxx.apps.googleusercontent.com" />
                    </label>
                    <label>
                      <span>Google Client Secret (可选)</span>
                      <input v-model="oauthDraft.googleSecret" type="password" placeholder="如桌面端要求则填入" />
                    </label>
                    <label class="span-2">
                      <span>Microsoft Entra Client ID</span>
                      <input v-model="oauthDraft.msId" type="text" placeholder="Application (client) ID" />
                    </label>
                    <div class="span-2">
                      <button type="button" class="btn-outline" @click="saveOAuthClientConfig">
                        保存 OAuth2 客户端配置
                      </button>
                    </div>
                  </div>
                </details>
              </div>
              </div>
            </div>

            <!-- 已绑定账号列表 -->
            <div class="panel-card">
              <div class="card-heading">
                <span>已绑定的邮箱渠道（{{ store.accounts.length }}）</span>
              </div>

              <div v-if="store.accounts.length === 0" class="empty-tip">暂无绑定邮箱，请在上方添加</div>

              <div v-for="(acc, idx) in store.accounts" :key="acc.id" class="bound-account-row">
                <div class="bound-main">
                  <ProviderBadge :kind="acc.provider" :color="acc.badge_color" :size="30" />
                  <div class="bound-info">
                    <div class="bound-name">
                      <strong>{{ acc.label }}</strong>
                      <span v-if="acc.is_demo" class="mini-tag">演示账号</span>
                      <span v-else class="mini-tag auth">{{ acc.auth_type === 'oauth2' ? 'OAuth2' : '授权码' }}</span>
                    </div>
                    <div class="bound-email">{{ acc.email }} · {{ acc.imap_host }}</div>
                    <div v-if="acc.last_error" class="bound-err-box">
                      <span class="bound-err">最近错误：{{ acc.last_error }}</span>
                      <div class="bound-err-actions">
                        <button type="button" class="err-fix-btn" @click="beginEditSecret(acc)">
                          更新授权码
                        </button>
                        <a
                          v-if="getProviderGuideUrl(acc.provider)"
                          :href="getProviderGuideUrl(acc.provider)"
                          target="_blank"
                          rel="noopener noreferrer"
                          class="err-guide-link"
                        >
                          {{ acc.provider === 'gmail' ? '前往获取应用专用密码' : '获取授权码指引' }}
                          <ExternalLink :size="11" />
                        </a>
                      </div>
                    </div>
                  </div>

                  <div class="bound-ops">
                    <button type="button" title="上移" :disabled="idx === 0" @click="moveAccountOrder(idx, -1)">
                      <ArrowUp :size="14" />
                    </button>
                    <button
                      type="button"
                      title="下移"
                      :disabled="idx === store.accounts.length - 1"
                      @click="moveAccountOrder(idx, 1)"
                    >
                      <ArrowDown :size="14" />
                    </button>
                    <button
                      v-if="!acc.is_demo && acc.auth_type === 'password'"
                      type="button"
                      :class="{ warn: Boolean(acc.last_error) }"
                      title="更新密码或授权码"
                      @click="beginEditSecret(acc)"
                    >
                      改密码
                    </button>
                    <button type="button" title="编辑签名" @click="beginEditSignature(acc)">签名</button>
                    <button
                      type="button"
                      title="立即同步"
                      :disabled="syncingAccountId === acc.id"
                      @click="handleSyncSingleAccount(acc)"
                    >
                      <RefreshCw :size="14" :class="{ spinning: syncingAccountId === acc.id }" />
                    </button>
                    <button type="button" class="danger" title="删除此邮箱" @click="handleDeleteAccount(acc)">
                      <Trash2 :size="14" />
                    </button>
                  </div>
                </div>

                <div v-if="editingSecretId === acc.id" class="sig-editor secret-editor">
                  <div class="secret-tip">
                    <span v-if="acc.provider === 'gmail'">
                      请填入 Google 账号两步验证下生成的 <strong>16 位应用专用密码</strong>（复制带空格也可，系统将自动去除）。
                    </span>
                    <span v-else>请填入邮箱网页版开启 IMAP 后生成的客户端授权码或新密码。</span>
                  </div>
                  <input
                    v-model="editingSecretText"
                    type="password"
                    :placeholder="acc.provider === 'gmail' ? '例如：abcd efgh ijkl mnop' : '输入新的授权码或密码'"
                  />
                  <div v-if="secretUpdateErr" class="status-banner err">{{ secretUpdateErr }}</div>
                  <div class="sig-actions">
                    <button type="button" class="btn-outline" @click="editingSecretId = null">取消</button>
                    <button type="button" class="btn-primary" :disabled="updatingSecret" @click="saveUpdatedSecret(acc)">
                      {{ updatingSecret ? '正在验证并同步…' : '验证并保存' }}
                    </button>
                  </div>
                </div>

                <div v-if="editingSignatureId === acc.id" class="sig-editor">
                  <textarea v-model="editingSignatureText" rows="2" placeholder="输入该邮箱专属发信落款签名…" />
                  <div class="sig-actions">
                    <button type="button" class="btn-outline" @click="editingSignatureId = null">取消</button>
                    <button type="button" class="btn-primary" @click="saveSignature(acc)">保存签名</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 2: 外观与书房氛围 -->
          <div v-else-if="store.settingsTab === 'appearance'" class="tab-section">
            <div class="panel-card">
              <div class="card-heading"><span>书房主题模式</span></div>
              <div class="theme-cards">
                <button
                  type="button"
                  class="theme-option"
                  :class="{ active: store.settings.theme_mode === 'light' }"
                  @click="setThemeWithTransition('light', $event)"
                >
                  <div class="theme-preview light-prev" />
                  <div class="theme-name">
                    <span>明亮模式 · 樱花白日</span>
                    <CheckCircle2 v-if="store.settings.theme_mode === 'light'" :size="15" />
                  </div>
                </button>
                <button
                  type="button"
                  class="theme-option"
                  :class="{ active: store.settings.theme_mode === 'dark' }"
                  @click="setThemeWithTransition('dark', $event)"
                >
                  <div class="theme-preview dark-prev" />
                  <div class="theme-name">
                    <span>暗黑模式 · 星夜书房</span>
                    <CheckCircle2 v-if="store.settings.theme_mode === 'dark'" :size="15" />
                  </div>
                </button>
                <button
                  type="button"
                  class="theme-option"
                  :class="{ active: store.settings.theme_mode === 'system' }"
                  @click="setThemeWithTransition('system', $event)"
                >
                  <div class="theme-preview sys-prev" />
                  <div class="theme-name">
                    <span>跟随系统明暗</span>
                    <CheckCircle2 v-if="store.settings.theme_mode === 'system'" :size="15" />
                  </div>
                </button>
              </div>
            </div>

            <div class="panel-card">
              <div class="card-heading"><span>装饰立绘与氛围特效（精简模式可一键隐藏）</span></div>
              <div class="setting-row">
                <div>
                  <strong>显示左右角色立绘</strong>
                  <p>关闭后立即进入纯书本精简专注视图</p>
                </div>
                <input
                  type="checkbox"
                  class="toggle-switch"
                  :checked="store.settings.show_mascots"
                  @change="store.updateSettings({ show_mascots: !store.settings.show_mascots })"
                />
              </div>

              <div v-if="store.settings.show_mascots" class="setting-row">
                <div>
                  <strong>立绘透明度 ({{ Math.round(store.settings.mascot_opacity * 100) }}%)</strong>
                  <p>调节角色立绘与桌面的融合通透度</p>
                </div>
                <input
                  type="range"
                  min="0.2"
                  max="1"
                  step="0.05"
                  :value="store.settings.mascot_opacity"
                  @input="store.updateSettings({ mascot_opacity: Number(($event.target as HTMLInputElement).value) })"
                />
              </div>

              <div class="setting-row">
                <div>
                  <strong>自定义左右立绘替换</strong>
                  <p>支持上传透明 PNG 图片替换左下角或书侧探头立绘</p>
                </div>
                <div class="mascot-upload-btns">
                  <label class="btn-outline upload-label">
                    <Upload :size="13" />
                    <span>换左立绘</span>
                    <input type="file" accept="image/*" hidden @change="handleUploadMascot('left', $event)" />
                  </label>
                  <button
                    v-if="store.settings.custom_mascot_left"
                    type="button"
                    class="btn-outline"
                    @click="handleResetMascot('left')"
                  >
                    恢复左图
                  </button>
                  <label class="btn-outline upload-label">
                    <Upload :size="13" />
                    <span>换右立绘</span>
                    <input type="file" accept="image/*" hidden @change="handleUploadMascot('right', $event)" />
                  </label>
                  <button
                    v-if="store.settings.custom_mascot_right"
                    type="button"
                    class="btn-outline"
                    @click="handleResetMascot('right')"
                  >
                    恢复右图
                  </button>
                </div>
              </div>

              <div class="setting-row">
                <div>
                  <strong>飘落樱花 / 星尘光斑粒子</strong>
                  <p>明亮模式飘落樱花花瓣，暗黑模式漂浮星光微粒</p>
                </div>
                <input
                  type="checkbox"
                  class="toggle-switch"
                  :checked="store.settings.show_particles"
                  @change="store.updateSettings({ show_particles: !store.settings.show_particles })"
                />
              </div>
            </div>

            <div class="panel-card">
              <div class="card-heading"><span>动效手感与阅读排版</span></div>
              <div class="setting-row">
                <div><strong>翻页与切换动效强度</strong></div>
                <select
                  :value="store.settings.motion_level"
                  @change="store.updateSettings({ motion_level: ($event.target as HTMLSelectElement).value as any })"
                >
                  <option value="full">完整 3D 翻页动效</option>
                  <option value="gentle">轻柔淡入淡出</option>
                  <option value="off">关闭动效（极速响应）</option>
                </select>
              </div>
              <div class="setting-row">
                <div><strong>邮件正文字号</strong></div>
                <select
                  :value="store.settings.font_size"
                  @change="store.updateSettings({ font_size: ($event.target as HTMLSelectElement).value as any })"
                >
                  <option value="sm">紧凑小号 (13px)</option>
                  <option value="md">标准适中 (14.5px)</option>
                  <option value="lg">舒适大号 (16px)</option>
                </select>
              </div>
              <div class="setting-row">
                <div><strong>邮件列表密度</strong></div>
                <select
                  :value="store.settings.list_density"
                  @change="store.updateSettings({ list_density: ($event.target as HTMLSelectElement).value as any })"
                >
                  <option value="comfortable">舒适留白</option>
                  <option value="compact">紧凑高密度</option>
                </select>
              </div>
            </div>
          </div>

          <!-- TAB 3: 收发与规则 -->
          <div v-else-if="store.settingsTab === 'sync'" class="tab-section">
            <div class="panel-card">
              <div class="card-heading"><span>收发与后台同步习惯</span></div>

              <div class="setting-row">
                <div>
                  <strong>智能原路回复</strong>
                  <p>在聚合视图回复邮件时，自动选用收信时的同一邮箱发出</p>
                </div>
                <input
                  type="checkbox"
                  class="toggle-switch"
                  :checked="store.settings.smart_send_from"
                  @change="store.updateSettings({ smart_send_from: !store.settings.smart_send_from })"
                />
              </div>

              <div class="setting-row">
                <div>
                  <strong>撤销发送缓冲时间</strong>
                  <p>点击发送后预留反悔窗口，防止手误发错</p>
                </div>
                <select
                  :value="store.settings.undo_send_seconds"
                  @change="store.updateSettings({ undo_send_seconds: Number(($event.target as HTMLSelectElement).value) })"
                >
                  <option :value="0">关闭（立即发送）</option>
                  <option :value="5">5 秒</option>
                  <option :value="10">10 秒</option>
                </select>
              </div>

              <div class="setting-row">
                <div>
                  <strong>实时推送收信（IMAP IDLE 极速接收验证码）</strong>
                  <p>保持加密长连接，新邮件与验证码秒级到达（不支持的邮箱自动 5 秒极速检测）</p>
                </div>
                <input
                  type="checkbox"
                  class="toggle-switch"
                  :checked="store.settings.realtime_push"
                  @change="store.updateSettings({ realtime_push: !store.settings.realtime_push })"
                />
              </div>

              <div class="setting-row">
                <div>
                  <strong>后台自动同步频率</strong>
                  <p>控制定时全量文件夹与已读/星标同步；选「仅手动同步」将同时暂停实时推送</p>
                </div>
                <select
                  :value="store.settings.sync_interval_minutes"
                  @change="store.updateSettings({ sync_interval_minutes: Number(($event.target as HTMLSelectElement).value) })"
                >
                  <option :value="0">仅手动同步</option>
                  <option :value="1">每 1 分钟</option>
                  <option :value="5">每 5 分钟</option>
                  <option :value="15">每 15 分钟</option>
                </select>
              </div>

              <div class="setting-row">
                <div>
                  <strong>拉取历史邮件范围</strong>
                </div>
                <select
                  :value="store.settings.sync_days"
                  @change="store.updateSettings({ sync_days: Number(($event.target as HTMLSelectElement).value) })"
                >
                  <option :value="7">最近 7 天</option>
                  <option :value="30">最近 30 天</option>
                  <option :value="90">最近 90 天</option>
                  <option :value="0">全部邮件</option>
                </select>
              </div>
            </div>

            <div class="panel-card">
              <div class="card-heading"><span>智能分类规则（同步新邮件时自动匹配左页标签）</span></div>
              <div class="rule-add-row">
                <input v-model="newRule.name" type="text" placeholder="规则名称" />
                <select v-model="newRule.field">
                  <option value="sender_email">发件邮箱包含</option>
                  <option value="sender_name">发件人名称包含</option>
                  <option value="subject">主题包含</option>
                </select>
                <input v-model="newRule.pattern" type="text" placeholder="关键词如 github.com" />
                <select v-model="newRule.target_category">
                  <option value="work">工作</option>
                  <option value="study">学习</option>
                  <option value="social">社交</option>
                  <option value="subscription">订阅</option>
                </select>
                <button type="button" class="btn-primary" @click="handleAddRule">添加</button>
              </div>

              <div class="rules-list">
                <div v-for="rule in store.rules" :key="rule.id" class="rule-row">
                  <span><strong>{{ rule.name }}</strong> · 匹配「{{ rule.pattern }}」 → {{ rule.target_category }}</span>
                  <button type="button" class="icon-del" @click="handleDeleteRule(rule.id)">
                    <Trash2 :size="14" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- TAB 4: 通知提醒 -->
          <div v-else-if="store.settingsTab === 'notifications'" class="tab-section">
            <div class="panel-card">
              <div class="card-heading"><span>新邮件通知开关</span></div>
              <div class="setting-row">
                <div>
                  <strong>启用新邮件桌面通知</strong>
                  <p>后台同步到未读新邮件时在顶部与桌面提醒</p>
                </div>
                <input
                  type="checkbox"
                  class="toggle-switch"
                  :checked="store.settings.desktop_notifications"
                  @change="handleToggleDesktopNotifications"
                />
              </div>

              <div v-for="acc in store.accounts" :key="acc.id" class="setting-row">
                <div>
                  <strong>{{ acc.label }}</strong>
                  <p>{{ acc.email }}</p>
                </div>
                <input
                  type="checkbox"
                  class="toggle-switch"
                  :checked="acc.notify_enabled"
                  @change="mailApi.updateAccount(acc.id, { notify_enabled: !acc.notify_enabled }).then(() => store.refreshAccounts())"
                />
              </div>
            </div>
          </div>

          <!-- TAB 5: 隐私与本地数据 -->
          <div v-else-if="store.settingsTab === 'privacy'" class="tab-section">
            <div class="panel-card">
              <div class="card-heading"><span>隐私与追踪保护</span></div>
              <div class="setting-row">
                <div>
                  <strong>拦截外链追踪图片（隐私保护模式）</strong>
                  <p>开启后将隐藏远程图片防止像素追踪，阅读时支持单封一键放行</p>
                </div>
                <input
                  type="checkbox"
                  class="toggle-switch"
                  :checked="store.settings.block_remote_images"
                  @change="store.updateSettings({ block_remote_images: !store.settings.block_remote_images })"
                />
              </div>
            </div>

            <div class="panel-card">
              <div class="card-heading">
                <span>SQLite 本地存储与演示数据管理</span>
                <Database :size="15" />
              </div>

              <div v-if="storageInfo" class="storage-grid">
                <div class="stat-box">
                  <span>数据库体积</span>
                  <strong>{{ formatBytes(storageInfo.db_size_bytes) }}</strong>
                </div>
                <div class="stat-box">
                  <span>附件缓存</span>
                  <strong>{{ formatBytes(storageInfo.attachments_size_bytes) }}</strong>
                </div>
                <div class="stat-box">
                  <span>本地邮件数</span>
                  <strong>{{ storageInfo.emails_count }} 封</strong>
                </div>
                <div class="stat-box">
                  <span>演示账号数</span>
                  <strong>{{ storageInfo.demo_accounts_count }} 个</strong>
                </div>
              </div>

              <div class="privacy-actions">
                <button type="button" class="btn-outline" @click="handleClearCache">
                  清理附件缓存
                </button>
                <a class="btn-outline link-as-btn" href="/api/v1/system/backup-db" download>
                  <HardDriveDownload :size="14" />
                  <span>导出 SQLite 数据库备份</span>
                </a>
                <button type="button" class="btn-outline" @click="handleClearDemo">
                  清空演示邮箱数据
                </button>
                <button type="button" class="btn-primary" @click="handleResetDemo">
                  重新生成演示数据
                </button>
              </div>
            </div>
          </div>

          <!-- TAB 6: 关于与诊断 -->
          <div v-else-if="store.settingsTab === 'diagnostics'" class="tab-section">
            <div class="panel-card">
              <div class="card-heading">
                <span>关于 MailHub 与运行环境</span>
                <span class="mini-tag auth">
                  v{{ diagnosticsInfo?.app_version ?? '1.1.0' }}
                  <template v-if="diagnosticsInfo?.git_commit"> · {{ diagnosticsInfo.git_commit }}</template>
                </span>
              </div>

              <div v-if="diagnosticsError" class="status-banner err">{{ diagnosticsError }}</div>

              <div v-if="diagnosticsInfo" class="diag-meta-grid">
                <div class="stat-box">
                  <span>操作系统 / 架构</span>
                  <strong class="diag-small-val">{{ diagnosticsInfo.os_info }} ({{ diagnosticsInfo.arch }})</strong>
                </div>
                <div class="stat-box">
                  <span>Python / 本地端口</span>
                  <strong class="diag-small-val">{{ diagnosticsInfo.python_version }} · {{ diagnosticsInfo.host }}:{{ diagnosticsInfo.port }}</strong>
                </div>
                <div class="stat-box">
                  <span>主密钥来源</span>
                  <strong class="diag-small-val">{{ secretModeLabel }}</strong>
                </div>
                <div class="stat-box">
                  <span>前端静态产物</span>
                  <strong class="diag-small-val">{{ diagnosticsInfo.frontend_dist_ready ? '已就绪 (frontend/dist)' : '未构建（开发代理模式）' }}</strong>
                </div>
              </div>

              <div class="privacy-actions" style="margin-top: 12px">
                <a class="btn-primary link-as-btn" :href="GITHUB_ISSUES_URL" target="_blank" rel="noopener noreferrer">
                  <Bug :size="14" />
                  <span>前往 GitHub 提交 Issue</span>
                  <ExternalLink :size="12" />
                </a>
                <a class="btn-outline link-as-btn" :href="GITHUB_FAQ_URL" target="_blank" rel="noopener noreferrer">
                  <span>查看 README 常见问题</span>
                  <ExternalLink :size="12" />
                </a>
                <a class="btn-outline link-as-btn" :href="GITHUB_PROVIDER_GUIDE_URL" target="_blank" rel="noopener noreferrer">
                  <span>邮箱渠道与 OAuth2 指南</span>
                  <ExternalLink :size="12" />
                </a>
                <a class="btn-outline link-as-btn" :href="GITHUB_REPO_URL" target="_blank" rel="noopener noreferrer">
                  <span>项目主页</span>
                  <ExternalLink :size="12" />
                </a>
              </div>
            </div>

            <div class="panel-card">
              <div class="card-heading">
                <span>Issue 精准排障 · 脱敏诊断报告与诊断包</span>
                <button
                  type="button"
                  class="btn-outline"
                  :disabled="loadingDiagnostics"
                  @click="loadDiagnostics"
                >
                  <RefreshCw :size="13" :class="{ spinning: loadingDiagnostics }" />
                  <span>{{ loadingDiagnostics ? '采集中…' : '刷新快照' }}</span>
                </button>
              </div>

              <div class="guide-tip">
                <span>
                  诊断报告与诊断包采用尽力脱敏：自动遮罩邮箱前缀、用户主目录路径、主机名、Fernet 密文与 OAuth/授权码凭据，且<strong>绝不包含邮件正文或数据库文件</strong>。分享至公开 Issue 前仍请展开预览自行复核。
                </span>
              </div>

              <div v-if="diagnosticsInfo" class="diag-event-bar">
                <div>
                  <span class="diag-event-label">本次诊断 Event ID：</span>
                  <code class="diag-event-code">{{ diagnosticsInfo.event_id }}</code>
                </div>
                <span class="diag-log-stats">
                  同步记录 {{ diagnosticsInfo.recent_sync_logs.length }} 条 · 后端日志 {{ diagnosticsInfo.backend_log_lines.length }} 行 · 启动器日志 {{ diagnosticsInfo.launcher_log_lines.length }} 行
                </span>
              </div>

              <div class="privacy-actions">
                <button
                  type="button"
                  class="btn-outline"
                  :disabled="!diagnosticsInfo"
                  @click="handleCopyEventId"
                >
                  <Copy :size="14" />
                  <span>复制 Event ID</span>
                </button>
                <button
                  type="button"
                  class="btn-primary"
                  :disabled="!diagnosticsInfo"
                  @click="handleCopyDiagnosticReport"
                >
                  <Copy :size="14" />
                  <span>复制脱敏诊断报告 (Markdown)</span>
                </button>
                <a
                  class="btn-outline link-as-btn"
                  :href="diagnosticBundleUrl"
                  download
                >
                  <HardDriveDownload :size="14" />
                  <span>导出脱敏诊断包 (.zip)</span>
                </a>
              </div>

              <details v-if="diagnosticsInfo" class="diag-preview-details">
                <summary>展开预览将要复制的脱敏 Markdown 诊断报告（建议分享前检查）</summary>
                <pre class="diag-preview-pre soft-scroll">{{ diagnosticsInfo.markdown_report }}</pre>
              </details>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: var(--modal-backdrop);
  backdrop-filter: blur(7px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.settings-modal {
  width: min(920px, 95vw);
  height: min(640px, 88vh);
  border-radius: 22px;
  overflow: hidden;
  background: var(--modal-bg);
  border: 1.5px solid var(--glass-panel-border);
  box-shadow: 0 30px 76px rgba(24, 12, 42, 0.38);
  display: grid;
  grid-template-columns: 190px 1fr;
}

.settings-nav {
  padding: 20px 12px;
  background: var(--letter-card-bg);
  border-right: 1px solid var(--divider);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-title {
  padding: 0 10px 12px;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 12px;
  border-radius: 11px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}

.nav-item:hover {
  background: var(--accent-soft);
}

.nav-item.active {
  background: var(--accent-gradient);
  color: #ffffff;
}

.settings-content-wrap {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.settings-top-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 22px;
  border-bottom: 1px solid var(--divider);
}

.settings-top-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
}

.close-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.settings-body {
  flex: 1;
  min-height: 0;
  padding: 16px 22px 24px;
}

.tab-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-card {
  padding: 16px;
  border-radius: 16px;
  background: var(--surface-elevated);
  border: 1px solid var(--divider);
}

.tour-anchor-block {
  display: block;
}

.card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 12px;
}

.mode-switch {
  display: flex;
  gap: 4px;
  padding: 3px;
  border-radius: 999px;
  background: var(--letter-card-bg);
}

.mode-switch button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: 999px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.mode-switch button.active {
  background: var(--accent-gradient);
  color: #ffffff;
}

.preset-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.preset-chip {
  padding: 5px 11px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: var(--input-bg);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
}

.preset-chip.active {
  background: var(--accent-soft);
  border-color: var(--accent-primary);
  color: var(--accent-text);
  font-weight: 700;
}

.guide-tip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 11px;
  background: var(--accent-soft);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
  margin-bottom: 12px;
}

.guide-tip a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--accent-text);
  font-weight: 700;
  flex-shrink: 0;
  text-decoration: none;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 12px;
}

.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.form-grid input,
.form-grid select {
  padding: 8px 10px;
  border-radius: 9px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.span-2 {
  grid-column: 1 / -1;
}

.server-toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.link-btn {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--accent-text);
  font-size: 12px;
  cursor: pointer;
}

.color-picker-label {
  display: inline-flex !important;
  flex-direction: row !important;
  align-items: center;
  gap: 6px;
}

.port-ssl {
  display: flex;
  align-items: center;
  gap: 10px;
}

.port-ssl input[type='number'] {
  width: 90px;
}

.port-ssl label {
  flex-direction: row;
  align-items: center;
  gap: 4px;
}

.status-banner {
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 12.5px;
}

.status-banner.ok {
  background: rgba(16, 185, 129, 0.14);
  color: var(--success);
}

.status-banner.err {
  background: rgba(225, 29, 72, 0.14);
  color: var(--danger);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 999px;
  border: none;
  background: var(--accent-gradient);
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}

.btn-outline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 12.5px;
  cursor: pointer;
}

.link-as-btn {
  text-decoration: none;
}

.oauth-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.oauth-btn-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.oauth-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  border-radius: 10px;
  background: var(--accent-soft);
  font-size: 12.5px;
  color: var(--accent-text);
}

.oauth-config-details summary {
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}

.bound-account-row {
  padding: 10px 0;
  border-top: 1px solid var(--divider);
}

.bound-main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bound-info {
  flex: 1;
  min-width: 0;
}

.bound-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.mini-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-text);
}

.bound-email {
  font-size: 11.5px;
  color: var(--text-muted);
}

.bound-err-box {
  margin-top: 4px;
  padding: 6px 9px;
  border-radius: 9px;
  background: rgba(225, 29, 72, 0.08);
  border: 1px solid rgba(225, 29, 72, 0.2);
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.bound-err {
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--danger);
}

.bound-err-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.err-fix-btn {
  padding: 2px 9px;
  border-radius: 999px;
  border: 1px solid rgba(225, 29, 72, 0.35);
  background: var(--surface-elevated);
  color: var(--danger);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.err-guide-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent-text);
  text-decoration: none;
}

.bound-ops button.warn {
  border-color: rgba(225, 29, 72, 0.4);
  color: var(--danger);
  font-weight: 600;
}

.secret-editor input {
  padding: 8px 10px;
  border-radius: 9px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 12.5px;
}

.secret-tip {
  font-size: 12px;
  color: var(--text-secondary);
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.bound-ops {
  display: flex;
  align-items: center;
  gap: 4px;
}

.bound-ops button {
  padding: 5px 8px;
  border-radius: 8px;
  border: 1px solid var(--divider);
  background: transparent;
  color: var(--text-secondary);
  font-size: 11.5px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
}

.bound-ops button.danger {
  color: var(--danger);
}

.sig-editor {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sig-editor textarea {
  padding: 8px 10px;
  border-radius: 9px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 12.5px;
}

.sig-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.theme-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.theme-option {
  padding: 8px;
  border-radius: 13px;
  border: 1.5px solid var(--divider);
  background: var(--input-bg);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.theme-option.active {
  border-color: var(--accent-primary);
  background: var(--accent-soft);
}

.theme-preview {
  height: 54px;
  border-radius: 9px;
}

.light-prev {
  background: linear-gradient(135deg, #ffdbe9, #efe6ff);
}

.dark-prev {
  background: linear-gradient(135deg, #1b162a, #412d60);
}

.sys-prev {
  background: linear-gradient(135deg, #ffdbe9 50%, #241b38 50%);
}

.theme-name {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid var(--divider);
}

.setting-row:first-of-type {
  border-top: none;
}

.setting-row p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.setting-row select {
  padding: 6px 10px;
  border-radius: 9px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 12.5px;
}

.toggle-switch {
  width: 18px;
  height: 18px;
  accent-color: var(--accent-primary);
  cursor: pointer;
}

.mascot-upload-btns {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.rule-add-row {
  display: grid;
  grid-template-columns: 1fr 110px 1fr 80px auto;
  gap: 6px;
  margin-bottom: 10px;
}

.rule-add-row input,
.rule-add-row select {
  padding: 6px 9px;
  border-radius: 8px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 12px;
}

.rules-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rule-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  border-radius: 9px;
  background: var(--letter-card-bg);
  font-size: 12.5px;
}

.icon-del {
  border: none;
  background: transparent;
  color: var(--danger);
  cursor: pointer;
}

.storage-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}

.stat-box {
  padding: 10px;
  border-radius: 11px;
  background: var(--letter-card-bg);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-box span {
  font-size: 11.5px;
  color: var(--text-muted);
}

.stat-box strong {
  font-size: 15px;
  color: var(--text-primary);
}

.privacy-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.diag-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.diag-small-val {
  font-size: 13px !important;
  word-break: break-word;
}

.diag-event-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding: 9px 12px;
  margin-bottom: 12px;
  border-radius: 10px;
  background: var(--letter-card-bg);
  font-size: 12px;
}

.diag-event-label {
  color: var(--text-secondary);
}

.diag-event-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 700;
  color: var(--accent-text);
}

.diag-log-stats {
  color: var(--text-muted);
  font-size: 11.5px;
}

.diag-preview-details {
  margin-top: 12px;
}

.diag-preview-details summary {
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}

.diag-preview-pre {
  margin: 10px 0 0;
  padding: 12px;
  max-height: 240px;
  overflow: auto;
  border-radius: 10px;
  border: 1px solid var(--divider);
  background: var(--letter-card-bg);
  color: var(--text-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
