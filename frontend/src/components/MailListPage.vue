<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { motion } from 'motion-v'
import {
  ChevronLeft,
  ChevronRight,
  Filter,
  Mail,
  Paperclip,
  PenLine,
  RefreshCw,
  Search,
  Star,
  X,
} from 'lucide-vue-next'
import ProviderBadge from '@/components/ProviderBadge.vue'
import BookScrollArea from '@/components/BookScrollArea.vue'
import { useMailStore } from '@/stores/mailStore'
import { useBookMotion } from '@/composables/useBookMotion'
import type { CategoryType, EmailSummary } from '@/types/mail'

const store = useMailStore()
const { motionMode, springTransition } = useBookMotion()

const searchOpen = ref(false)
const filterOpen = ref(false)
const localQuery = ref('')
let searchDebounce: number | null = null
let resizeDebounce: number | null = null
let layoutObserver: ResizeObserver | null = null
let hasMeasuredCard = false

const listPageRef = ref<HTMLElement | null>(null)
const searchDrawerRef = ref<HTMLElement | null>(null)
const batchBarRef = ref<HTMLElement | null>(null)
const listScrollRef = ref<InstanceType<typeof BookScrollArea> | null>(null)

const shouldFillPage = computed(
  () => store.emails.length > 0 && store.emails.length >= store.pageSize,
)

const folderTitleMap: Record<string, string> = {
  inbox: '收件箱',
  unread: '未读邮件',
  starred: '星标邮件',
  sent: '发件箱',
  drafts: '草稿箱',
  archive: '归档',
  spam: '垃圾邮件',
  trash: '回收站',
}

const folderSubtitleMap: Record<string, string> = {
  inbox: '收件箱邮件',
  unread: '未读邮件',
  starred: '星标邮件',
  sent: '发件箱邮件',
  drafts: '草稿箱邮件',
  archive: '归档邮件',
  spam: '垃圾邮件',
  trash: '回收站邮件',
}

const categories: Array<{ id: CategoryType; label: string }> = [
  { id: 'all', label: '全部邮箱' },
  { id: 'work', label: '工作' },
  { id: 'study', label: '学习' },
  { id: 'social', label: '社交' },
  { id: 'subscription', label: '订阅' },
]

const currentFolderLabel = computed(() => folderTitleMap[store.activeFolder] ?? '收件箱')

const headerTitle = computed(() => {
  const folderName = currentFolderLabel.value
  if (store.currentAccount) {
    return `${store.currentAccount.label} · ${folderName}`
  }
  return folderName
})

const headerSubtitle = computed(() => {
  if (store.currentAccount) {
    return store.currentAccount.email
  }
  const folderSub = folderSubtitleMap[store.activeFolder] ?? '最新邮件'
  return `已勾选聚合邮箱的${folderSub}`
})

watch(localQuery, (val) => {
  if (searchDebounce !== null) {
    window.clearTimeout(searchDebounce)
  }
  searchDebounce = window.setTimeout(() => {
    store.searchQuery = val
    store.currentPage = 1
    void store.fetchEmails({ selectFirst: true })
  }, 260)
})

function toggleSearch(): void {
  searchOpen.value = !searchOpen.value
  if (!searchOpen.value && localQuery.value) {
    localQuery.value = ''
  }
}

function toggleChecked(emailId: number): void {
  if (store.checkedEmailIds.includes(emailId)) {
    store.checkedEmailIds = store.checkedEmailIds.filter((id) => id !== emailId)
  } else {
    store.checkedEmailIds = [...store.checkedEmailIds, emailId]
  }
}

function handleCardClick(mail: EmailSummary): void {
  void store.selectEmail(mail.id)
}

function formatShortTime(iso: string): string {
  const dt = new Date(iso)
  const now = new Date()
  if (
    dt.getFullYear() === now.getFullYear() &&
    dt.getMonth() === now.getMonth() &&
    dt.getDate() === now.getDate()
  ) {
    return dt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  return `${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
}

function resolveBadgeKind(mail: EmailSummary): string {
  if (mail.sender_avatar_key) return mail.sender_avatar_key
  const lower = mail.sender_email.toLowerCase()
  if (lower.includes('github')) return 'github'
  if (lower.includes('bilibili')) return 'bilibili'
  if (lower.includes('google') || lower.includes('gmail')) return 'gmail'
  if (lower.includes('163')) return '163'
  if (lower.includes('qq.com')) return 'qq'
  if (lower.includes('steam')) return 'steam'
  if (lower.includes('edu')) return 'school'
  return 'mail'
}

/**
 * 基于左侧书页列表视口高度与当前密度/字号估算每页最适邮件数，保证不同尺寸下列表沾满书页。
 */
function calculateIdealPageSize(): number | null {
  const viewport = listScrollRef.value?.viewportRef
  if (!viewport || viewport.clientHeight <= 0) return null

  // 还原不受临时搜索抽屉或批量操作条挤压的基准列表高度，避免开关浮条引发分页跳变
  let baseHeight = viewport.clientHeight
  if (searchDrawerRef.value) {
    baseHeight += searchDrawerRef.value.offsetHeight
  }
  if (batchBarRef.value) {
    const batchStyle = getComputedStyle(batchBarRef.value)
    baseHeight += batchBarRef.value.offsetHeight + (parseFloat(batchStyle.marginTop) || 0)
  }

  const content = listScrollRef.value?.contentRef
  const listStyle = content ? getComputedStyle(content) : null
  const rowGap = listStyle ? parseFloat(listStyle.rowGap) || 8 : 8
  const listPadY = listStyle
    ? (parseFloat(listStyle.paddingTop) || 0) + (parseFloat(listStyle.paddingBottom) || 0)
    : 8

  const rootStyle = getComputedStyle(document.documentElement)
  const itemPy = parseFloat(rootStyle.getPropertyValue('--mail-item-py')) || 11
  let cardHeight = store.settings.list_density === 'compact' ? 65 : 73
  if (store.settings.font_size === 'sm') cardHeight -= 3
  if (store.settings.font_size === 'lg') cardHeight += 4

  const firstCard = content?.querySelector<HTMLElement>('.mail-card')
  if (firstCard) {
    const mainCol = firstCard.querySelector<HTMLElement>('.card-main-col')
    const leftCol = firstCard.querySelector<HTMLElement>('.card-left-col')
    const innerHeight = Math.max(
      mainCol?.getBoundingClientRect().height ?? 0,
      leftCol?.getBoundingClientRect().height ?? 0,
    )
    if (innerHeight > 0) {
      // NOTE: 使用内芯实际高度推算单卡自然高度，避免受到 fill-page 弹性伸展的影响
      cardHeight = Math.ceil(innerHeight + itemPy * 2 + 2)
      hasMeasuredCard = true
    }
  }

  const innerAvailable = Math.max(120, baseHeight - listPadY)
  const count = Math.floor((innerAvailable + rowGap) / (cardHeight + rowGap))
  return Math.min(50, Math.max(3, count))
}

function schedulePageSizeSync(immediate = false): void {
  if (resizeDebounce !== null) {
    window.clearTimeout(resizeDebounce)
    resizeDebounce = null
  }

  const runSync = (): void => {
    const ideal = calculateIdealPageSize()
    if (ideal !== null && ideal !== store.pageSize) {
      void store.setPageSize(ideal)
    }
  }

  if (immediate) {
    runSync()
    return
  }

  resizeDebounce = window.setTimeout(runSync, 140)
}

watch(
  () => [store.settings.list_density, store.settings.font_size],
  async () => {
    hasMeasuredCard = false
    await nextTick()
    window.requestAnimationFrame(() => schedulePageSizeSync(true))
  },
)

watch(
  () => store.emails.length,
  async (len) => {
    if (len > 0 && !hasMeasuredCard) {
      await nextTick()
      window.requestAnimationFrame(() => schedulePageSizeSync(true))
    }
  },
)

onMounted(() => {
  schedulePageSizeSync(true)
  if (typeof ResizeObserver !== 'undefined' && listPageRef.value) {
    layoutObserver = new ResizeObserver(() => {
      schedulePageSizeSync(false)
    })
    layoutObserver.observe(listPageRef.value)
  }
})

onUnmounted(() => {
  layoutObserver?.disconnect()
  if (resizeDebounce !== null) {
    window.clearTimeout(resizeDebounce)
  }
  if (searchDebounce !== null) {
    window.clearTimeout(searchDebounce)
  }
})
</script>

<template>
  <section ref="listPageRef" class="list-page" aria-label="邮件列表">
    <!-- 顶部标题与写邮件 -->
    <div class="list-header">
      <div class="list-title-group">
        <div class="list-icon-box" aria-hidden="true">
          <Mail :size="18" />
        </div>
        <div class="list-title-texts">
          <h2 class="list-title">{{ headerTitle }}</h2>
          <p class="list-subtitle">{{ headerSubtitle }}</p>
        </div>
      </div>

      <div class="list-header-actions" data-tour="mail-list-actions">
        <button
          type="button"
          class="icon-circle-btn"
          :title="store.currentAccount ? `同步刷新 ${store.currentAccount.label}` : '同步刷新全部邮箱'"
          aria-label="同步刷新"
          :disabled="store.syncing"
          @click="store.syncCurrentOrAll()"
        >
          <RefreshCw :size="15" :class="{ spinning: store.syncing }" />
        </button>

        <button
          type="button"
          class="compose-cta-btn"
          @click="store.openCompose()"
        >
          <PenLine :size="14" />
          <span>写邮件</span>
        </button>
      </div>
    </div>

    <!-- 分类标签栏与搜索筛选 -->
    <div class="category-bar">
      <div class="category-pills">
        <button
          v-for="cat in categories"
          :key="cat.id"
          type="button"
          class="cat-pill"
          :class="{ active: store.activeCategory === cat.id }"
          @click="store.setCategory(cat.id)"
        >
          <motion.span
            v-if="store.activeCategory === cat.id && motionMode !== 'off'"
            layout-id="category-active-bg"
            class="cat-pill-bg"
            :transition="springTransition"
          />
          <span
            v-else-if="store.activeCategory === cat.id"
            class="cat-pill-bg"
          />
          <span class="cat-pill-text">{{ cat.label }}</span>
        </button>
      </div>

      <div class="search-filter-group">
        <button
          type="button"
          class="mini-tool-btn"
          :class="{ active: searchOpen || localQuery.length > 0 }"
          title="搜索邮件（支持全文检索）"
          aria-label="搜索邮件"
          @click="toggleSearch"
        >
          <Search :size="15" />
        </button>
        <button
          type="button"
          class="mini-tool-btn"
          :class="{ active: filterOpen || store.filterUnreadOnly || store.filterHasAttachments }"
          title="条件筛选"
          aria-label="条件筛选"
          @click="filterOpen = !filterOpen"
        >
          <Filter :size="15" />
        </button>
      </div>
    </div>

    <!-- 展开的搜索框或筛选条件栏 -->
    <div v-if="searchOpen || filterOpen" ref="searchDrawerRef" class="search-drawer">
      <div v-if="searchOpen" class="search-input-wrap">
        <Search :size="14" class="search-prefix-icon" />
        <input
          v-model="localQuery"
          type="text"
          class="search-input"
          placeholder="搜索主题、发件人、邮件正文..."
          aria-label="全文搜索邮件"
        />
        <button v-if="localQuery" type="button" class="clear-search-btn" @click="localQuery = ''">
          <X :size="13" />
        </button>
      </div>
      <div v-if="filterOpen" class="filter-chips">
        <label class="filter-check">
          <input
            v-model="store.filterUnreadOnly"
            type="checkbox"
            @change="store.fetchEmails({ selectFirst: true })"
          />
          <span>仅看未读</span>
        </label>
        <label class="filter-check">
          <input
            v-model="store.filterHasAttachments"
            type="checkbox"
            @change="store.fetchEmails({ selectFirst: true })"
          />
          <span>含附件</span>
        </label>
      </div>
    </div>

    <!-- 批量操作浮动条 -->
    <div v-if="store.checkedEmailIds.length > 0" ref="batchBarRef" class="batch-bar">
      <span>已选 {{ store.checkedEmailIds.length }} 封</span>
      <div class="batch-actions">
        <button type="button" @click="store.runBatchAction('mark_read')">标为已读</button>
        <button type="button" @click="store.runBatchAction('archive')">归档</button>
        <button type="button" class="danger" @click="store.runBatchAction('trash')">删除</button>
        <button type="button" @click="store.checkedEmailIds = []">取消</button>
      </div>
    </div>

    <!-- 邮件列表丝带滚动区 -->
    <BookScrollArea
      ref="listScrollRef"
      class="mail-list-area"
      :content-class="shouldFillPage ? 'mail-list fill-page' : 'mail-list'"
    >
      <div v-if="store.loadingList && store.emails.length === 0" class="empty-state">
        正在翻阅邮件…
      </div>

      <div v-else-if="store.emails.length === 0" class="empty-state">
        <p v-if="store.currentAccount">
          「{{ store.currentAccount.label }}」的{{ currentFolderLabel }}暂无邮件
        </p>
        <p v-else>这一页暂没有匹配的邮件</p>
        <div class="empty-actions">
          <button
            v-if="store.currentAccount && !store.currentAccount.is_demo"
            type="button"
            class="empty-reset-btn"
            :disabled="store.syncing"
            @click="store.syncCurrentOrAll()"
          >
            {{ store.syncing ? '正在同步…' : '立即同步该邮箱' }}
          </button>
          <button type="button" class="empty-reset-btn" @click="store.openCompose()">
            写一封新邮件
          </button>
        </div>
      </div>

      <motion.div
        v-for="(mail, idx) in store.emails"
        :key="mail.id"
        class="mail-card"
        :class="{
          selected: store.selectedEmailId === mail.id,
          unread: !mail.is_read,
        }"
        :initial="motionMode === 'full' ? { opacity: 0, y: 8 } : false"
        :animate="{ opacity: 1, y: 0 }"
        :transition="
          motionMode === 'full'
            ? { duration: 0.2, delay: Math.min(idx * 0.025, 0.14) }
            : { duration: 0 }
        "
        @click="handleCardClick(mail)"
      >
        <div class="card-left-col" @click.stop>
          <input
            type="checkbox"
            class="mail-checkbox"
            :checked="store.checkedEmailIds.includes(mail.id)"
            aria-label="选中邮件"
            @change="toggleChecked(mail.id)"
          />
          <ProviderBadge :kind="resolveBadgeKind(mail)" :color="mail.account_color" :size="30" />
        </div>

        <div class="card-main-col">
          <div class="card-top-line">
            <div class="sender-wrap">
              <span v-if="!mail.is_read" class="unread-dot" title="未读" />
              <span class="sender-name">{{ mail.sender_name }}</span>
              <span
                v-if="store.selectedAccountId === null && mail.account_label"
                class="origin-chip"
                :style="{ '--chip-color': mail.account_color }"
              >
                {{ mail.account_label }}
              </span>
            </div>
            <span class="mail-time">{{ formatShortTime(mail.received_at) }}</span>
          </div>

          <div class="card-subject-line">
            <span class="mail-subject">{{ mail.subject }}</span>
            <Paperclip v-if="mail.has_attachments" :size="12" class="attach-flag" />
          </div>

          <div class="card-bottom-line">
            <span class="mail-snippet">{{ mail.snippet || '(无正文预览)' }}</span>
            <button
              type="button"
              class="star-btn"
              :class="{ starred: mail.is_starred }"
              :title="mail.is_starred ? '取消星标' : '标为星标'"
              aria-label="切换星标"
              @click.stop="store.toggleStar(mail.id)"
            >
              <Star :size="14" :fill="mail.is_starred ? 'currentColor' : 'none'" />
            </button>
          </div>
        </div>
      </motion.div>
    </BookScrollArea>

    <!-- 底部分页条 -->
    <div class="list-footer">
      <button
        type="button"
        class="page-btn"
        :disabled="store.currentPage <= 1"
        aria-label="上一页"
        @click="store.setPage(store.currentPage - 1)"
      >
        <ChevronLeft :size="15" />
      </button>
      <span class="page-indicator">{{ store.currentPage }} / {{ store.totalPages }}</span>
      <button
        type="button"
        class="page-btn"
        :disabled="store.currentPage >= store.totalPages"
        aria-label="下一页"
        @click="store.setPage(store.currentPage + 1)"
      >
        <ChevronRight :size="15" />
      </button>
    </div>
  </section>
</template>

<style scoped>
.list-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px 18px 10px;
  min-height: 0;
}

.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.list-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.list-icon-box {
  width: 36px;
  height: 36px;
  border-radius: 11px;
  background: var(--accent-soft);
  color: var(--accent-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.list-title-texts {
  min-width: 0;
}

.list-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.list-subtitle {
  margin: 1px 0 0;
  font-size: 11.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.list-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.icon-circle-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--divider);
  background: var(--surface-elevated);
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 0.16s ease, background-color 0.16s ease;
}

.icon-circle-btn:hover {
  background: var(--accent-soft);
  color: var(--accent-text);
}

.compose-cta-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 999px;
  border: none;
  background: var(--accent-gradient);
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
  box-shadow: 0 6px 16px rgba(139, 108, 232, 0.34);
  transition: transform 0.16s ease, box-shadow 0.16s ease;
}

.compose-cta-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 20px rgba(139, 108, 232, 0.44);
}

.category-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--divider);
}

.category-pills {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.cat-pill {
  position: relative;
  border: none;
  background: transparent;
  padding: 5px 11px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  color: var(--text-secondary);
  cursor: pointer;
}

@media (max-width: 1400px) {
  .category-pills {
    gap: 2px;
  }

  .cat-pill {
    padding: 4px 8px;
    font-size: 12px;
  }
}

.cat-pill.active {
  color: #ffffff;
}

.cat-pill-bg {
  position: absolute;
  inset: 0;
  border-radius: 999px;
  background: var(--accent-gradient);
  z-index: 0;
}

.cat-pill-text {
  position: relative;
  z-index: 1;
}

.search-filter-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.mini-tool-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.mini-tool-btn:hover,
.mini-tool-btn.active {
  background: var(--accent-soft);
  color: var(--accent-text);
  border-color: var(--divider);
}

.search-drawer {
  padding: 8px 0 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-bottom: 1px solid var(--divider);
}

.search-input-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 10px;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
}

.search-prefix-icon {
  color: var(--text-muted);
}

.search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 12.5px;
  color: var(--text-primary);
}

.clear-search-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
}

.filter-chips {
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: var(--text-secondary);
}

.filter-check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
}

.batch-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  margin-top: 8px;
  border-radius: 10px;
  background: var(--accent-soft);
  font-size: 12px;
  font-weight: 600;
  color: var(--accent-text);
}

.batch-actions {
  display: flex;
  gap: 6px;
}

.batch-actions button {
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: var(--surface-elevated);
  color: var(--text-primary);
  font-size: 11.5px;
  cursor: pointer;
}

.batch-actions button.danger {
  color: var(--danger);
}

.mail-list-area {
  margin-top: 4px;
}

:deep(.mail-list) {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--mail-item-gap);
  padding: 4px 2px 4px 0;
}

.mail-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--mail-item-py) 12px;
  border-radius: 14px;
  background: var(--mail-card-bg);
  border: 1px solid var(--mail-card-border);
  cursor: pointer;
  transition: background-color 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
}

.mail-list-area :deep(.mail-list.fill-page .mail-card) {
  flex: 1 0 auto;
}

.mail-card:hover {
  background: var(--mail-card-hover);
}

.mail-card.selected {
  background: var(--selected-mail-bg);
  border-color: var(--selected-mail-border);
  box-shadow: 0 6px 16px rgba(226, 128, 174, 0.18);
}

.card-left-col {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mail-checkbox {
  width: 14px;
  height: 14px;
  accent-color: var(--accent-primary);
  cursor: pointer;
}

.card-main-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.card-top-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.sender-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
}

.unread-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--badge-pink);
  flex-shrink: 0;
}

.sender-name {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.origin-chip {
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--badge-soft-bg);
  color: var(--text-secondary);
  border-left: 3px solid var(--chip-color, var(--accent-primary));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
  min-width: 0;
}

.mail-time {
  font-size: 11.5px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  flex-shrink: 0;
}

.card-subject-line {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mail-subject {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mail-card:not(.unread) .mail-subject {
  font-weight: 500;
}

.attach-flag {
  color: var(--text-muted);
  flex-shrink: 0;
}

.card-bottom-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.mail-snippet {
  font-size: var(--mail-snippet-size);
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.star-btn {
  border: none;
  background: transparent;
  padding: 2px;
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.16s ease;
}

.star-btn:hover {
  transform: scale(1.22);
}

.star-btn.starred {
  color: var(--star-gold);
}

.list-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding-top: 6px;
  border-top: 1px solid var(--divider);
}

.page-btn {
  width: 28px;
  height: 26px;
  border-radius: 8px;
  border: 1px solid var(--divider);
  background: var(--surface-elevated);
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-indicator {
  font-size: 12.5px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted);
  font-size: 13.5px;
}

.empty-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}

.empty-reset-btn {
  padding: 7px 16px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: var(--accent-soft);
  color: var(--accent-text);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}

.empty-reset-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
