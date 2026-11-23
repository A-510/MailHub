import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { mailApi } from '@/api/client'
import type {
  AppSettings,
  CategoryType,
  ClassificationRule,
  EmailAccount,
  EmailDetail,
  EmailSummary,
  FolderCounts,
  FolderType,
  ProviderPreset,
  SyncLogItem,
} from '@/types/mail'

export interface ToastMessage {
  id: number
  text: string
  type: 'info' | 'success' | 'error'
}

export interface PendingUndoSend {
  id: number
  accountId: number
  toAddresses: string[]
  ccAddresses: string[]
  bccAddresses: string[]
  subject: string
  htmlBody: string
  textBody: string
  inReplyTo: string
  draftId: number | null
  files: File[]
  remainingSeconds: number
  totalSeconds: number
  onRestored?: () => void
}

const DEFAULT_COUNTS: FolderCounts = {
  inbox: 0,
  inbox_unread: 0,
  unread: 0,
  starred: 0,
  sent: 0,
  drafts: 0,
  archive: 0,
  spam: 0,
  trash: 0,
}

export const useMailStore = defineStore('mailhub', () => {
  const accounts = ref<EmailAccount[]>([])
  const providers = ref<ProviderPreset[]>([])
  const rules = ref<ClassificationRule[]>([])
  const notifications = ref<SyncLogItem[]>([])
  const settings = ref<AppSettings>({
    theme_mode: 'light',
    show_mascots: true,
    mascot_opacity: 0.96,
    custom_mascot_left: null,
    custom_mascot_right: null,
    show_particles: true,
    motion_level: 'full',
    font_size: 'md',
    list_density: 'comfortable',
    default_account_id: null,
    smart_send_from: true,
    undo_send_seconds: 5,
    sync_interval_minutes: 5,
    sync_days: 30,
    desktop_notifications: true,
    block_remote_images: false,
    oauth_google_client_id: '',
    oauth_google_client_secret: '',
    oauth_microsoft_client_id: '',
  })

  // 导航与筛选状态
  const selectedAccountId = ref<number | null>(null) // null 表示全部聚合视图
  const activeFolder = ref<FolderType>('inbox')
  const activeCategory = ref<CategoryType>('all')
  const searchQuery = ref('')
  const filterUnreadOnly = ref(false)
  const filterHasAttachments = ref(false)
  const currentPage = ref(1)
  const pageSize = ref(8)
  const totalPages = ref(1)
  const totalEmails = ref(0)
  const hasInitialFetch = ref(false)
  const folderCounts = ref<FolderCounts>({ ...DEFAULT_COUNTS })

  // 邮件列表与详情
  const emails = ref<EmailSummary[]>([])
  const selectedEmailId = ref<number | null>(null)
  const currentEmail = ref<EmailDetail | null>(null)
  const checkedEmailIds = ref<number[]>([])
  const loadingList = ref(false)
  const loadingDetail = ref(false)
  const syncing = ref(false)

  // 全局 UI 浮层状态
  const composeOpen = ref(false)
  const composeSeed = ref<{
    draftId?: number | null
    accountId?: number | null
    to?: string
    cc?: string
    subject?: string
    htmlBody?: string
    textBody?: string
  } | null>(null)
  const settingsOpen = ref(false)
  const settingsTab = ref<'accounts' | 'appearance' | 'sync' | 'notifications' | 'privacy' | 'diagnostics'>('accounts')
  const readingFullscreen = ref(false)

  // 首次使用新手引导状态
  const ONBOARDING_STORAGE_KEY = 'mailhub_onboarding_v1_done'
  const onboardingOpen = ref(false)
  const onboardingStep = ref(0)

  /**
   * 检查是否应在当前页面自动弹出新手引导（首次使用或 URL 带 ?tour=1）
   */
  function shouldAutoStartOnboarding(): boolean {
    try {
      const params = new URLSearchParams(window.location.search)
      if (params.get('tour') === '1') return true
      return window.localStorage.getItem(ONBOARDING_STORAGE_KEY) !== '1'
    } catch {
      return false
    }
  }

  /**
   * 启动新手引导浮层
   * @param stepIndex 起始步骤下标（默认从第 0 步开始）
   */
  function startOnboarding(stepIndex = 0): void {
    onboardingStep.value = stepIndex
    onboardingOpen.value = true
  }

  /**
   * 关闭新手引导并根据需要持久化已完成标记
   * @param markCompleted 是否记录为已完成（默认 true）
   */
  function closeOnboarding(markCompleted = true): void {
    onboardingOpen.value = false
    if (markCompleted) {
      try {
        window.localStorage.setItem(ONBOARDING_STORAGE_KEY, '1')
      } catch {
        // 忽略受限隐私模式下 localStorage 写入异常
      }
    }
  }

  // 翻页与动效方向令牌
  const bookFlipTick = ref(0)
  const bookFlipDirection = ref<'forward' | 'backward'>('forward')
  const pageTurnDirection = ref<'next' | 'prev'>('next')

  // 全局 Toast 与撤销发送
  const toasts = ref<ToastMessage[]>([])
  const pendingUndoSend = ref<PendingUndoSend | null>(null)
  let undoTimerId: number | null = null
  let toastSeq = 1

  function pushToast(text: string, type: ToastMessage['type'] = 'info'): void {
    const id = toastSeq++
    toasts.value.push({ id, text, type })
    window.setTimeout(() => {
      toasts.value = toasts.value.filter((t) => t.id !== id)
    }, 3600)
  }

  const unifiedCheckedIds = computed(() =>
    accounts.value.filter((a) => a.include_in_unified).map((a) => a.id),
  )

  const currentAccount = computed(() =>
    selectedAccountId.value === null
      ? null
      : accounts.value.find((a) => a.id === selectedAccountId.value) ?? null,
  )

  async function bootstrap(): Promise<void> {
    const [loadedSettings, loadedProviders, loadedAccounts, loadedRules, loadedLogs] =
      await Promise.all([
        mailApi.getSettings(),
        mailApi.getProviders(),
        mailApi.listAccounts(),
        mailApi.listRules(),
        mailApi.getNotifications(),
      ])
    settings.value = loadedSettings
    providers.value = loadedProviders
    accounts.value = loadedAccounts
    rules.value = loadedRules
    notifications.value = loadedLogs
    await fetchEmails({ selectFirst: true })
  }

  async function refreshAccounts(): Promise<void> {
    accounts.value = await mailApi.listAccounts()
  }

  async function fetchEmails(opts?: { selectFirst?: boolean; keepSelection?: boolean }): Promise<void> {
    loadingList.value = true
    try {
      const res = await mailApi.listEmails({
        folder: activeFolder.value,
        category: activeCategory.value,
        account_id: selectedAccountId.value ?? undefined,
        account_ids:
          selectedAccountId.value === null ? unifiedCheckedIds.value.join(',') : undefined,
        q: searchQuery.value.trim(),
        unread_only: filterUnreadOnly.value,
        has_attachments: filterHasAttachments.value,
        page: currentPage.value,
        page_size: pageSize.value,
      })
      hasInitialFetch.value = true
      emails.value = res.items
      totalEmails.value = res.total
      totalPages.value = res.total_pages
      currentPage.value = res.page
      folderCounts.value = res.folder_counts
      checkedEmailIds.value = checkedEmailIds.value.filter((id) =>
        res.items.some((m) => m.id === id),
      )

      if (opts?.selectFirst) {
        if (res.items.length > 0) {
          await selectEmail(res.items[0].id, { skipMarkRead: true })
        } else {
          selectedEmailId.value = null
          currentEmail.value = null
        }
      } else if (opts?.keepSelection && currentEmail.value !== null && res.items.length > 0) {
        // 窗口尺寸变化引起分页容量重算时，尽量保持右侧正在阅读的邮件不被意外切走
      } else if (
        selectedEmailId.value !== null &&
        !res.items.some((m) => m.id === selectedEmailId.value) &&
        res.items.length > 0
      ) {
        await selectEmail(res.items[0].id, { skipMarkRead: true })
      } else if (res.items.length === 0) {
        selectedEmailId.value = null
        currentEmail.value = null
      }
    } finally {
      loadingList.value = false
    }
  }

  /**
   * 根据左侧书页可用高度动态更新每页展示条数，并在已完成首次拉取后同步刷新列表。
   * @param nextSize 计算得到的单页条数
   */
  async function setPageSize(nextSize: number): Promise<void> {
    const clamped = Math.min(50, Math.max(3, Math.round(nextSize)))
    if (clamped === pageSize.value) return
    pageSize.value = clamped
    if (hasInitialFetch.value) {
      await fetchEmails({ keepSelection: true })
    }
  }

  async function selectEmail(
    emailId: number,
    options?: { skipMarkRead?: boolean },
  ): Promise<void> {
    selectedEmailId.value = emailId
    loadingDetail.value = true
    try {
      const detail = await mailApi.getEmail(emailId)
      // 防止连续快切邮件时旧请求返回覆盖最新选择（TR-06）
      if (selectedEmailId.value !== emailId) return
      currentEmail.value = detail

      if (!options?.skipMarkRead && !detail.is_read) {
        const updated = await mailApi.patchEmail(emailId, { is_read: true })
        if (selectedEmailId.value === emailId) {
          currentEmail.value = updated
        }
        const row = emails.value.find((m) => m.id === emailId)
        if (row && !row.is_read) {
          row.is_read = true
          folderCounts.value.unread = Math.max(0, folderCounts.value.unread - 1)
          folderCounts.value.inbox_unread = Math.max(0, folderCounts.value.inbox_unread - 1)
          const acc = accounts.value.find((a) => a.id === row.account_id)
          if (acc && acc.unread_count > 0) acc.unread_count -= 1
        }
      }
    } finally {
      if (selectedEmailId.value === emailId) {
        loadingDetail.value = false
      }
    }
  }

  async function switchAccount(accountId: number | null): Promise<void> {
    if (selectedAccountId.value === accountId) return
    const prevIdx =
      selectedAccountId.value === null
        ? -1
        : accounts.value.findIndex((a) => a.id === selectedAccountId.value)
    const nextIdx =
      accountId === null ? -1 : accounts.value.findIndex((a) => a.id === accountId)

    bookFlipDirection.value = nextIdx >= prevIdx ? 'forward' : 'backward'
    bookFlipTick.value += 1
    selectedAccountId.value = accountId
    currentPage.value = 1
    checkedEmailIds.value = []
    await fetchEmails({ selectFirst: true })
  }

  async function toggleIncludeInUnified(account: EmailAccount): Promise<void> {
    const nextVal = !account.include_in_unified
    account.include_in_unified = nextVal
    await mailApi.updateAccount(account.id, { include_in_unified: nextVal })
    if (selectedAccountId.value === null) {
      currentPage.value = 1
      await fetchEmails({ selectFirst: true })
    }
  }

  async function setFolder(folder: FolderType): Promise<void> {
    if (activeFolder.value === folder) return
    activeFolder.value = folder
    // 切换文件夹时重置分类筛选，避免残留的分类条件屏蔽垃圾邮件/回收站/发件箱/草稿箱内容
    activeCategory.value = 'all'
    currentPage.value = 1
    checkedEmailIds.value = []
    await fetchEmails({ selectFirst: true })
  }

  async function setCategory(category: CategoryType): Promise<void> {
    if (activeCategory.value === category) return
    activeCategory.value = category
    currentPage.value = 1
    await fetchEmails({ selectFirst: true })
  }

  async function setPage(nextPage: number): Promise<void> {
    const clamped = Math.min(Math.max(1, nextPage), totalPages.value)
    if (clamped === currentPage.value) return
    pageTurnDirection.value = clamped > currentPage.value ? 'next' : 'prev'
    currentPage.value = clamped
    await fetchEmails({ selectFirst: true })
  }

  async function toggleStar(emailId: number): Promise<void> {
    const item = emails.value.find((m) => m.id === emailId)
    const currentStar = item ? item.is_starred : currentEmail.value?.is_starred ?? false
    const nextStar = !currentStar
    if (item) item.is_starred = nextStar
    if (currentEmail.value?.id === emailId) currentEmail.value.is_starred = nextStar
    await mailApi.patchEmail(emailId, { is_starred: nextStar })
    await fetchEmails()
  }

  async function moveEmailFolder(
    emailId: number,
    targetFolder: Exclude<FolderType, 'unread' | 'starred'>,
  ): Promise<void> {
    await mailApi.patchEmail(emailId, { folder: targetFolder })
    const labelMap: Record<string, string> = {
      archive: '已归档邮件',
      trash: '已移至回收站',
      spam: '已标记为垃圾邮件',
      inbox: '已移回收件箱',
    }
    pushToast(labelMap[targetFolder] ?? '邮件已移动', 'success')
    await fetchEmails({ selectFirst: true })
    await refreshAccounts()
  }

  async function toggleEmailRead(emailId: number): Promise<void> {
    const item = emails.value.find((m) => m.id === emailId)
    const nextRead = !(item?.is_read ?? currentEmail.value?.is_read ?? true)
    await mailApi.patchEmail(emailId, { is_read: nextRead })
    if (item) item.is_read = nextRead
    if (currentEmail.value?.id === emailId) currentEmail.value.is_read = nextRead
    await fetchEmails()
    await refreshAccounts()
  }

  async function runBatchAction(action: string): Promise<void> {
    if (checkedEmailIds.value.length === 0) return
    const res = await mailApi.batchEmails(checkedEmailIds.value, action)
    checkedEmailIds.value = []
    pushToast(`已批量处理 ${res.affected} 封邮件`, 'success')
    await fetchEmails({ selectFirst: true })
    await refreshAccounts()
  }

  async function syncAll(): Promise<void> {
    if (syncing.value) return
    syncing.value = true
    try {
      const res = await mailApi.syncAllAccounts()
      await Promise.all([refreshAccounts(), fetchEmails()])
      notifications.value = await mailApi.getNotifications()
      pushToast(
        res.fetched > 0 ? `同步完成，共收取 ${res.fetched} 封新邮件` : '邮箱已是最新状态',
        'success',
      )
    } catch (err) {
      pushToast((err as Error).message, 'error')
    } finally {
      syncing.value = false
    }
  }

  /**
   * 同步当前选中邮箱（单邮箱视图）或全部已启用邮箱（全部聚合视图）。
   */
  async function syncCurrentOrAll(): Promise<void> {
    if (selectedAccountId.value === null) {
      await syncAll()
      return
    }
    if (syncing.value) return
    syncing.value = true
    try {
      const res = await mailApi.syncSingleAccount(selectedAccountId.value)
      await Promise.all([refreshAccounts(), fetchEmails()])
      notifications.value = await mailApi.getNotifications()
      pushToast(res.message, res.ok ? 'success' : 'error')
    } catch (err) {
      pushToast((err as Error).message, 'error')
    } finally {
      syncing.value = false
    }
  }

  async function updateSettings(patch: Partial<AppSettings>): Promise<void> {
    settings.value = await mailApi.patchSettings(patch)
  }

  async function queueOrSendEmail(payload: {
    accountId: number
    toAddresses: string[]
    ccAddresses?: string[]
    bccAddresses?: string[]
    subject: string
    htmlBody: string
    textBody: string
    inReplyTo?: string
    draftId?: number | null
    files?: File[]
    onRestored?: () => void
  }): Promise<void> {
    const delaySec = settings.value.undo_send_seconds
    if (delaySec <= 0) {
      await executeSendNow(payload)
      return
    }

    // 若之前仍有待发送邮件，先立即发出前一条，确保新请求不阻塞（TR-06）
    if (pendingUndoSend.value) {
      await flushPendingSendNow()
    }

    const job: PendingUndoSend = {
      id: Date.now(),
      accountId: payload.accountId,
      toAddresses: payload.toAddresses,
      ccAddresses: payload.ccAddresses ?? [],
      bccAddresses: payload.bccAddresses ?? [],
      subject: payload.subject,
      htmlBody: payload.htmlBody,
      textBody: payload.textBody,
      inReplyTo: payload.inReplyTo ?? '',
      draftId: payload.draftId ?? null,
      files: payload.files ?? [],
      remainingSeconds: delaySec,
      totalSeconds: delaySec,
      onRestored: payload.onRestored,
    }
    pendingUndoSend.value = job

    undoTimerId = window.setInterval(() => {
      if (!pendingUndoSend.value) return
      pendingUndoSend.value.remainingSeconds -= 1
      if (pendingUndoSend.value.remainingSeconds <= 0) {
        void flushPendingSendNow()
      }
    }, 1000)
  }

  async function flushPendingSendNow(): Promise<void> {
    if (undoTimerId !== null) {
      window.clearInterval(undoTimerId)
      undoTimerId = null
    }
    const job = pendingUndoSend.value
    pendingUndoSend.value = null
    if (!job) return
    await executeSendNow(job)
  }

  function cancelPendingSend(): void {
    if (undoTimerId !== null) {
      window.clearInterval(undoTimerId)
      undoTimerId = null
    }
    const job = pendingUndoSend.value
    pendingUndoSend.value = null
    if (!job) return
    if (job.onRestored) {
      job.onRestored()
    } else {
      composeSeed.value = {
        draftId: job.draftId,
        accountId: job.accountId,
        to: job.toAddresses.join(', '),
        cc: job.ccAddresses.join(', '),
        subject: job.subject,
        htmlBody: job.htmlBody,
        textBody: job.textBody,
      }
      composeOpen.value = true
    }
    pushToast('已撤销发送，返回继续编辑', 'info')
  }

  async function executeSendNow(payload: {
    accountId: number
    toAddresses: string[]
    ccAddresses?: string[]
    bccAddresses?: string[]
    subject: string
    htmlBody: string
    textBody: string
    inReplyTo?: string
    draftId?: number | null
    files?: File[]
  }): Promise<void> {
    const form = new FormData()
    form.append('account_id', String(payload.accountId))
    form.append('to_addresses', JSON.stringify(payload.toAddresses))
    form.append('cc_addresses', JSON.stringify(payload.ccAddresses ?? []))
    form.append('bcc_addresses', JSON.stringify(payload.bccAddresses ?? []))
    form.append('subject', payload.subject)
    form.append('html_body', payload.htmlBody)
    form.append('text_body', payload.textBody)
    form.append('in_reply_to', payload.inReplyTo ?? '')
    if (payload.draftId) {
      form.append('draft_id', String(payload.draftId))
    }
    for (const file of payload.files ?? []) {
      form.append('files', file)
    }

    await mailApi.sendEmail(form)
    pushToast('邮件发送成功 ✨', 'success')
    await fetchEmails()
    await refreshAccounts()
  }

  function openCompose(seed?: typeof composeSeed.value): void {
    composeSeed.value = seed ?? null
    composeOpen.value = true
  }

  function openSettings(tab: typeof settingsTab.value = 'accounts'): void {
    settingsTab.value = tab
    settingsOpen.value = true
  }

  return {
    accounts,
    providers,
    rules,
    notifications,
    settings,
    selectedAccountId,
    activeFolder,
    activeCategory,
    searchQuery,
    filterUnreadOnly,
    filterHasAttachments,
    currentPage,
    pageSize,
    totalPages,
    totalEmails,
    folderCounts,
    emails,
    selectedEmailId,
    currentEmail,
    checkedEmailIds,
    loadingList,
    loadingDetail,
    syncing,
    composeOpen,
    composeSeed,
    settingsOpen,
    settingsTab,
    readingFullscreen,
    onboardingOpen,
    onboardingStep,
    shouldAutoStartOnboarding,
    startOnboarding,
    closeOnboarding,
    bookFlipTick,
    bookFlipDirection,
    pageTurnDirection,
    toasts,
    pendingUndoSend,
    unifiedCheckedIds,
    currentAccount,
    pushToast,
    bootstrap,
    refreshAccounts,
    fetchEmails,
    selectEmail,
    switchAccount,
    toggleIncludeInUnified,
    setFolder,
    setCategory,
    setPage,
    setPageSize,
    toggleStar,
    moveEmailFolder,
    toggleEmailRead,
    runBatchAction,
    syncAll,
    syncCurrentOrAll,
    updateSettings,
    queueOrSendEmail,
    flushPendingSendNow,
    cancelPendingSend,
    openCompose,
    openSettings,
  }
})
