<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { motion } from 'motion-v'
import {
  Archive,
  ArrowLeft,
  ChevronDown,
  Download,
  Forward,
  Maximize2,
  Minimize2,
  MoreHorizontal,
  PenLine,
  Reply,
  ReplyAll,
  ShieldAlert,
  Star,
  Tag,
  Trash2,
} from 'lucide-vue-next'
import ProviderBadge from '@/components/ProviderBadge.vue'
import InlineReplyComposer from '@/components/InlineReplyComposer.vue'
import BookScrollArea from '@/components/BookScrollArea.vue'
import { mailApi } from '@/api/client'
import { useMailStore } from '@/stores/mailStore'
import { useBookMotion } from '@/composables/useBookMotion'
import { sanitizeEmailHtml } from '@/composables/useMailSanitizer'

const store = useMailStore()
const { motionMode } = useBookMotion()

const replyMode = ref<'reply' | 'reply_all' | 'forward' | null>(null)
const showRecipientDetails = ref(false)
const tagMenuOpen = ref(false)
const moreMenuOpen = ref(false)
const showRawHeaders = ref(false)
const allowedRemoteEmailIds = ref<Set<number>>(new Set())

const categoryLabels: Record<'work' | 'study' | 'social' | 'subscription', string> = {
  work: '工作',
  study: '学习',
  social: '社交',
  subscription: '订阅',
}

watch(
  () => store.currentEmail?.id,
  () => {
    replyMode.value = null
    tagMenuOpen.value = false
    moreMenuOpen.value = false
    showRawHeaders.value = false
  },
)

const shouldBlockRemote = computed(() => {
  const email = store.currentEmail
  if (!email) return false
  return (
    store.settings.block_remote_images &&
    email.has_remote_images &&
    !allowedRemoteEmailIds.value.has(email.id)
  )
})

function allowRemoteForEmail(emailId: number): void {
  const next = new Set(allowedRemoteEmailIds.value)
  next.add(emailId)
  allowedRemoteEmailIds.value = next
}

const safeHtml = computed(() => {
  const email = store.currentEmail
  if (!email) return ''
  return sanitizeEmailHtml(email.html_body || email.text_body, {
    blockRemoteImages: shouldBlockRemote.value,
  })
})

function resolveBadgeKind(avatarKey: string, senderEmail: string): string {
  if (avatarKey) return avatarKey
  const lower = senderEmail.toLowerCase()
  if (lower.includes('github')) return 'github'
  if (lower.includes('bilibili')) return 'bilibili'
  if (lower.includes('google') || lower.includes('gmail')) return 'gmail'
  if (lower.includes('163')) return '163'
  if (lower.includes('qq')) return 'qq'
  return 'mail'
}

function formatDetailTime(iso: string): string {
  const dt = new Date(iso)
  const now = new Date()
  const timeStr = dt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  if (dt.toDateString() === now.toDateString()) {
    return `今天 ${timeStr}`
  }
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')} ${timeStr}`
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function setEmailCategory(cat: 'work' | 'study' | 'social' | 'subscription'): Promise<void> {
  if (!store.currentEmail) return
  tagMenuOpen.value = false
  const updated = await mailApi.patchEmail(store.currentEmail.id, { category: cat })
  store.currentEmail = updated
  store.pushToast(`已将邮件归类为「${categoryLabels[cat]}」`, 'success')
  await store.fetchEmails()
}

function continueEditingDraft(): void {
  const email = store.currentEmail
  if (!email) return
  store.openCompose({
    draftId: email.id,
    accountId: email.account_id,
    to: email.to_addresses.join(', '),
    cc: email.cc_addresses.join(', '),
    subject: email.subject,
    htmlBody: email.html_body,
    textBody: email.text_body,
  })
}

async function deleteForever(): Promise<void> {
  if (!store.currentEmail) return
  await mailApi.deleteEmail(store.currentEmail.id)
  store.pushToast('已彻底删除邮件', 'success')
  await store.fetchEmails({ selectFirst: true })
}
</script>

<template>
  <section class="detail-page" aria-label="邮件正文详情">
    <!-- 顶部操作栏 -->
    <div class="detail-toolbar">
      <div class="toolbar-left">
        <button
          type="button"
          class="tool-circle-btn"
          :title="store.readingFullscreen ? '退出沉浸阅读' : '返回列表'"
          @click="store.readingFullscreen ? (store.readingFullscreen = false) : (store.selectedEmailId = null, store.currentEmail = null)"
        >
          <ArrowLeft :size="15" />
        </button>

        <button
          type="button"
          class="tool-circle-btn"
          title="归档邮件"
          :disabled="!store.currentEmail"
          @click="store.currentEmail && store.moveEmailFolder(store.currentEmail.id, 'archive')"
        >
          <Archive :size="15" />
        </button>

        <button
          type="button"
          class="tool-circle-btn"
          title="移至回收站"
          :disabled="!store.currentEmail"
          @click="store.currentEmail && store.moveEmailFolder(store.currentEmail.id, 'trash')"
        >
          <Trash2 :size="15" />
        </button>

        <!-- 分类标签下拉 -->
        <div class="menu-anchor">
          <button
            type="button"
            class="tool-circle-btn"
            title="修改邮件分类标签"
            :disabled="!store.currentEmail"
            @click="tagMenuOpen = !tagMenuOpen; moreMenuOpen = false"
          >
            <Tag :size="15" />
          </button>
          <div v-if="tagMenuOpen" class="pop-menu">
            <button
              v-for="(label, key) in categoryLabels"
              :key="key"
              type="button"
              :class="{ current: store.currentEmail?.category === key }"
              @click="setEmailCategory(key)"
            >
              {{ label }}
            </button>
          </div>
        </div>

        <!-- 更多操作菜单 -->
        <div class="menu-anchor">
          <button
            type="button"
            class="tool-circle-btn"
            title="更多操作"
            :disabled="!store.currentEmail"
            @click="moreMenuOpen = !moreMenuOpen; tagMenuOpen = false"
          >
            <MoreHorizontal :size="15" />
          </button>
          <div v-if="moreMenuOpen && store.currentEmail" class="pop-menu wide">
            <button type="button" @click="store.toggleEmailRead(store.currentEmail.id); moreMenuOpen = false">
              {{ store.currentEmail.is_read ? '标为未读' : '标为已读' }}
            </button>
            <button type="button" @click="store.moveEmailFolder(store.currentEmail.id, 'spam'); moreMenuOpen = false">
              <ShieldAlert :size="13" />
              <span>标记为垃圾邮件</span>
            </button>
            <button type="button" @click="showRawHeaders = !showRawHeaders; moreMenuOpen = false">
              {{ showRawHeaders ? '隐藏原始邮件头' : '查看原始邮件头' }}
            </button>
          </div>
        </div>
      </div>

      <div class="toolbar-right">
        <button
          type="button"
          class="tool-circle-btn star-tool"
          :class="{ starred: store.currentEmail?.is_starred }"
          title="星标"
          :disabled="!store.currentEmail"
          @click="store.currentEmail && store.toggleStar(store.currentEmail.id)"
        >
          <Star :size="15" :fill="store.currentEmail?.is_starred ? 'currentColor' : 'none'" />
        </button>

        <button
          type="button"
          class="tool-circle-btn"
          :title="store.readingFullscreen ? '还原双页阅读' : '单页沉浸阅读'"
          @click="store.readingFullscreen = !store.readingFullscreen"
        >
          <Minimize2 v-if="store.readingFullscreen" :size="15" />
          <Maximize2 v-else :size="15" />
        </button>
      </div>
    </div>

    <!-- 空态提示 -->
    <div v-if="!store.currentEmail" class="detail-empty">
      <div class="empty-stamp">✉️</div>
      <p>在书的左页挑选一封信笺，即可在此展开阅读与回复</p>
    </div>

    <!-- 正文丝带滚动内容 -->
    <BookScrollArea v-else class="detail-scroll" content-class="detail-scroll-inner">
      <motion.div
        :key="store.currentEmail.id"
        class="detail-body-motion"
        :initial="motionMode === 'off' ? false : { opacity: 0, x: 14 }"
        :animate="{ opacity: 1, x: 0 }"
        :transition="motionMode === 'off' ? { duration: 0 } : { duration: 0.22, ease: [0.22, 1, 0.36, 1] }"
      >
        <h1 class="detail-subject">{{ store.currentEmail.subject }}</h1>

        <div class="sender-meta-row">
          <div class="sender-left">
            <ProviderBadge
              :kind="resolveBadgeKind(store.currentEmail.sender_avatar_key, store.currentEmail.sender_email)"
              :color="store.currentEmail.account_color"
              :size="38"
            />
            <div class="sender-info">
              <div class="sender-name-line">
                <strong>{{ store.currentEmail.sender_name }}</strong>
                <span class="sender-addr">&lt;{{ store.currentEmail.sender_email }}&gt;</span>
              </div>
              <button
                type="button"
                class="recipient-toggle"
                @click="showRecipientDetails = !showRecipientDetails"
              >
                <span>收件人: {{ store.currentEmail.to_addresses[0] || store.currentEmail.account_email }}</span>
                <ChevronDown :size="12" :class="{ rotated: showRecipientDetails }" />
              </button>
              <div v-if="showRecipientDetails" class="recipient-detail-box">
                <div><strong>收件人：</strong>{{ store.currentEmail.to_addresses.join(', ') }}</div>
                <div v-if="store.currentEmail.cc_addresses.length">
                  <strong>抄送：</strong>{{ store.currentEmail.cc_addresses.join(', ') }}
                </div>
                <div><strong>归属渠道：</strong>{{ store.currentEmail.account_label }} ({{ store.currentEmail.account_email }})</div>
              </div>
            </div>
          </div>

          <div class="meta-right">
            <span class="detail-time">{{ formatDetailTime(store.currentEmail.received_at) }}</span>
            <span
              class="account-origin-pill"
              :style="{ borderColor: store.currentEmail.account_color }"
            >
              {{ store.currentEmail.account_label }}
            </span>
          </div>
        </div>

        <!-- 原始邮件头调试展示 -->
        <pre v-if="showRawHeaders" class="raw-headers-box soft-scroll">{{ store.currentEmail.raw_headers || '无原始邮件头记录' }}</pre>

        <!-- 航空信封风格信纸正文卡片 -->
        <div class="letter-card">
          <div class="airmail-stripe" />

          <div v-if="shouldBlockRemote" class="remote-img-banner">
            <span>出于隐私保护，已自动拦截该邮件中的外部追踪图片。</span>
            <div class="remote-img-actions">
              <button type="button" @click="allowRemoteForEmail(store.currentEmail!.id)">
                显示此邮件图片
              </button>
              <button
                type="button"
                class="secondary"
                @click="store.updateSettings({ block_remote_images: false })"
              >
                始终显示图片
              </button>
            </div>
          </div>

          <div class="letter-content-body">
            <!-- 已由 DOMPurify 严格净化后渲染 -->
            <div class="sanitized-html" v-html="safeHtml" />

            <!-- 附件区 -->
            <div v-if="store.currentEmail.attachments.length > 0" class="attachments-box">
              <div class="attach-heading">附件（{{ store.currentEmail.attachments.length }}）</div>
              <div class="attach-list">
                <a
                  v-for="att in store.currentEmail.attachments"
                  :key="att.id"
                  class="attach-item"
                  :href="`/api/v1/attachments/${att.id}/download`"
                  target="_blank"
                >
                  <Download :size="14" />
                  <span class="att-name">{{ att.filename }}</span>
                  <span class="att-size">{{ formatBytes(att.size_bytes) }}</span>
                </a>
              </div>
            </div>
          </div>

          <!-- 复古猫咪邮戳水印（纯装饰，不遮挡文字） -->
          <svg class="cat-postmark" viewBox="0 0 84 84" width="66" height="66" aria-hidden="true">
            <circle cx="42" cy="42" r="34" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="4 3" />
            <circle cx="42" cy="42" r="26" fill="none" stroke="currentColor" stroke-width="1.3" />
            <path d="M29 44c0-7 6-12 13-12s13 5 13 12c0 6-5 10-13 10s-13-4-13-10Z" fill="none" stroke="currentColor" stroke-width="1.8" />
            <path d="M31 35l-2-7 7 3M53 35l2-7-7 3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
            <circle cx="37" cy="43" r="1.6" fill="currentColor" />
            <circle cx="47" cy="43" r="1.6" fill="currentColor" />
          </svg>

          <div class="airmail-stripe" />
        </div>

        <!-- 底部快捷操作栏 -->
        <div class="detail-actions">
          <button type="button" class="action-pill" @click="replyMode = replyMode === 'reply' ? null : 'reply'">
            <Reply :size="14" />
            <span>回复</span>
          </button>
          <button type="button" class="action-pill" @click="replyMode = replyMode === 'reply_all' ? null : 'reply_all'">
            <ReplyAll :size="14" />
            <span>回复全部</span>
          </button>
          <button type="button" class="action-pill" @click="replyMode = replyMode === 'forward' ? null : 'forward'">
            <Forward :size="14" />
            <span>转发</span>
          </button>
          <button
            v-if="store.currentEmail.folder === 'drafts'"
            type="button"
            class="action-pill primary"
            @click="continueEditingDraft"
          >
            <PenLine :size="14" />
            <span>继续编辑草稿</span>
          </button>
          <button
            v-if="store.currentEmail.folder === 'trash'"
            type="button"
            class="action-pill danger"
            @click="deleteForever"
          >
            <Trash2 :size="14" />
            <span>彻底删除</span>
          </button>
        </div>

        <!-- 内联信纸回复框 -->
        <InlineReplyComposer
          v-if="replyMode"
          :mode="replyMode"
          :target-email="store.currentEmail"
          @close="replyMode = null"
        />
      </motion.div>
    </BookScrollArea>
  </section>
</template>

<style scoped>
.detail-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px 20px 12px;
  min-height: 0;
}

.detail-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--divider);
  margin-bottom: 12px;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-circle-btn {
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
  transition: background-color 0.16s ease, transform 0.16s ease;
}

.tool-circle-btn:hover:not(:disabled) {
  background: var(--accent-soft);
  color: var(--accent-text);
  transform: translateY(-1px);
}

.tool-circle-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tool-circle-btn.star-tool.starred {
  color: var(--star-gold);
}

.menu-anchor {
  position: relative;
}

.pop-menu {
  position: absolute;
  top: 38px;
  left: 0;
  min-width: 112px;
  padding: 6px;
  border-radius: 12px;
  background: var(--modal-bg);
  border: 1px solid var(--glass-panel-border);
  box-shadow: var(--glass-panel-shadow);
  display: flex;
  flex-direction: column;
  gap: 2px;
  z-index: 30;
}

.pop-menu.wide {
  min-width: 156px;
}

.pop-menu button {
  display: flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.pop-menu button:hover,
.pop-menu button.current {
  background: var(--accent-soft);
  color: var(--accent-text);
}

.detail-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 14px;
  gap: 10px;
}

.empty-stamp {
  font-size: 40px;
  opacity: 0.6;
}

.detail-scroll {
  min-height: 0;
}

:deep(.detail-scroll-inner) {
  padding-right: 4px;
}

.detail-body-motion {
  flex: 1 0 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.detail-subject {
  flex-shrink: 0;
  margin: 0 0 14px;
  font-size: 19px;
  font-weight: 800;
  line-height: 1.38;
  color: var(--text-primary);
}

.sender-meta-row {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.sender-left {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  min-width: 0;
}

.sender-info {
  min-width: 0;
}

.sender-name-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 13.5px;
}

.sender-addr {
  font-size: 12px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.recipient-toggle {
  margin-top: 3px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.recipient-toggle svg.rotated {
  transform: rotate(180deg);
}

.recipient-detail-box {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 10px;
  background: var(--letter-card-bg);
  border: 1px solid var(--letter-card-border);
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.meta-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 5px;
  flex-shrink: 0;
}

.detail-time {
  font-size: 12px;
  color: var(--text-muted);
}

.account-origin-pill {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-elevated);
  border: 1px solid var(--divider);
  color: var(--text-secondary);
}

.raw-headers-box {
  flex-shrink: 0;
  max-height: 150px;
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--input-bg);
  border: 1px solid var(--divider);
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

.letter-card {
  position: relative;
  flex: 1 0 auto;
  display: flex;
  flex-direction: column;
  min-height: 220px;
  border-radius: 16px;
  overflow: hidden;
  background: var(--letter-card-bg);
  border: 1px solid var(--letter-card-border);
  box-shadow: 0 6px 20px rgba(74, 48, 98, 0.06);
}

.letter-card :deep(.airmail-stripe) {
  flex-shrink: 0;
}

.remote-img-banner {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 16px;
  background: var(--accent-soft);
  color: var(--accent-text);
  font-size: 12px;
}

.remote-img-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.remote-img-banner button {
  border: none;
  border-radius: 999px;
  padding: 4px 10px;
  background: var(--accent-primary);
  color: #fff;
  font-size: 11.5px;
  cursor: pointer;
}

.remote-img-banner button.secondary {
  background: transparent;
  color: var(--accent-text);
  border: 1px solid rgba(140, 107, 232, 0.45);
}

.letter-content-body {
  position: relative;
  z-index: 2;
  flex: 1 0 auto;
  padding: 20px 22px;
  min-height: 200px;
}

.sanitized-html {
  font-size: var(--mail-body-size);
  line-height: 1.68;
  color: var(--text-primary);
  word-break: break-word;
}

.sanitized-html :deep(.mail-card-hero) {
  font-size: 13.5px;
}

.sanitized-html :deep(.mail-card-hero > div) {
  gap: 8px;
}

.sanitized-html :deep(.mail-card-hero > div > div) {
  flex-wrap: nowrap !important;
  font-size: 12px;
  gap: 6px;
}

.sanitized-html :deep(.mail-card-hero > div > div > span) {
  white-space: nowrap;
}

.sanitized-html :deep(a) {
  color: var(--accent-primary);
}

.sanitized-html :deep(code) {
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--accent-soft);
  font-family: var(--font-mono);
  font-size: 0.9em;
}

.sanitized-html :deep(img) {
  max-width: 100%;
  height: auto;
  vertical-align: middle;
  border-radius: 10px;
}

.sanitized-html :deep(.blocked-remote-img-chip) {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  margin: 2px 0;
  border-radius: 8px;
  border: 1px dashed rgba(140, 107, 232, 0.45);
  font-size: 12px;
  line-height: 1.45;
  color: var(--accent-text, #8c6be8);
  background: var(--accent-soft, rgba(140, 107, 232, 0.08));
  max-width: 100%;
  word-break: break-word;
}

.attachments-box {
  margin-top: 18px;
  padding-top: 12px;
  border-top: 1px dashed var(--divider);
}

.attach-heading {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.attach-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.attach-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px;
  border-radius: 10px;
  background: var(--surface-elevated);
  border: 1px solid var(--divider);
  color: var(--text-primary);
  font-size: 12.5px;
  text-decoration: none;
}

.attach-item:hover {
  border-color: var(--accent-primary);
}

.att-size {
  font-size: 11px;
  color: var(--text-muted);
}

.cat-postmark {
  position: absolute;
  right: 16px;
  bottom: 14px;
  color: var(--text-muted);
  opacity: 0.34;
  transform: rotate(-12deg);
  pointer-events: none;
  z-index: 1;
}

.detail-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.action-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 15px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: var(--surface-elevated);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.16s ease, background-color 0.16s ease, border-color 0.16s ease;
}

.action-pill:hover {
  background: var(--accent-soft);
  border-color: var(--accent-primary);
  transform: translateY(-1px);
}

.action-pill.primary {
  background: var(--accent-gradient);
  color: #ffffff;
  border-color: transparent;
}

.action-pill.danger {
  color: var(--danger);
}
</style>

<style>
/* 暗黑模式下同步适配邮件正文内联浅色卡片与色块 */
[data-theme='dark'] .letter-content-body .sanitized-html div[style*='border-radius'] {
  background: rgba(24, 18, 42, 0.82) !important;
  border-color: rgba(168, 139, 250, 0.28) !important;
}
</style>
