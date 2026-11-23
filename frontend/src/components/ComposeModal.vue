<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { motion } from 'motion-v'
import { Paperclip, Save, Send, X } from 'lucide-vue-next'
import { mailApi } from '@/api/client'
import { useMailStore } from '@/stores/mailStore'
import { useBookMotion } from '@/composables/useBookMotion'

const store = useMailStore()
const { motionMode } = useBookMotion()

const draftId = ref<number | null>(null)
const fromAccountId = ref<number>(0)
const toInput = ref('')
const ccInput = ref('')
const bccInput = ref('')
const showCcBcc = ref(false)
const subject = ref('')
const bodyText = ref('')
const files = ref<File[]>([])
const sending = ref(false)
const savingDraft = ref(false)

function hydrateFromSeed(): void {
  const seed = store.composeSeed
  draftId.value = seed?.draftId ?? null
  fromAccountId.value =
    seed?.accountId ??
    store.selectedAccountId ??
    store.settings.default_account_id ??
    store.accounts[0]?.id ??
    0
  toInput.value = seed?.to ?? ''
  ccInput.value = seed?.cc ?? ''
  bccInput.value = ''
  showCcBcc.value = Boolean(seed?.cc)
  subject.value = seed?.subject ?? ''
  bodyText.value = seed?.textBody ?? ''
  files.value = []
}

watch(
  () => store.composeOpen,
  (isOpen) => {
    if (isOpen) {
      hydrateFromSeed()
    }
  },
)

function parseAddresses(raw: string): string[] {
  return raw
    .replace(/;/g, ',')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function handleFileAdd(event: Event): void {
  const input = event.target as HTMLInputElement
  if (!input.files) return
  files.value = [...files.value, ...Array.from(input.files)]
  input.value = ''
}

function removeFile(idx: number): void {
  files.value = files.value.filter((_, i) => i !== idx)
}

async function handleSaveDraft(): Promise<void> {
  if (!fromAccountId.value) return
  savingDraft.value = true
  try {
    const escaped = bodyText.value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br/>')
    const saved = await mailApi.saveDraft({
      draft_id: draftId.value,
      account_id: fromAccountId.value,
      to_addresses: parseAddresses(toInput.value),
      cc_addresses: parseAddresses(ccInput.value),
      subject: subject.value,
      html_body: `<div>${escaped}</div>`,
      text_body: bodyText.value,
    })
    draftId.value = saved.id
    store.pushToast('草稿已保存至草稿箱', 'success')
    await store.fetchEmails()
  } catch (err) {
    store.pushToast((err as Error).message, 'error')
  } finally {
    savingDraft.value = false
  }
}

async function handleSend(): Promise<void> {
  const toList = parseAddresses(toInput.value)
  if (toList.length === 0) {
    store.pushToast('请输入收件人邮箱地址', 'error')
    return
  }
  sending.value = true
  try {
    const escaped = bodyText.value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br/>')

    await store.queueOrSendEmail({
      accountId: fromAccountId.value,
      toAddresses: toList,
      ccAddresses: parseAddresses(ccInput.value),
      bccAddresses: parseAddresses(bccInput.value),
      subject: subject.value || '(无主题)',
      htmlBody: `<div>${escaped}</div>`,
      textBody: bodyText.value,
      draftId: draftId.value,
      files: files.value,
    })
    store.composeOpen = false
  } catch (err) {
    store.pushToast((err as Error).message, 'error')
  } finally {
    sending.value = false
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && store.composeOpen) {
    store.composeOpen = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div
    v-if="store.composeOpen"
    class="modal-backdrop"
    role="dialog"
    aria-modal="true"
    aria-label="撰写新邮件"
    @click.self="store.composeOpen = false"
  >
    <motion.div
      class="compose-modal"
      :initial="motionMode === 'off' ? false : { opacity: 0, scale: 0.96, y: 14 }"
      :animate="{ opacity: 1, scale: 1, y: 0 }"
      :transition="motionMode === 'off' ? { duration: 0 } : { duration: 0.22 }"
    >
      <div class="airmail-stripe" />

      <div class="compose-header">
        <h3>撰写新邮件</h3>
        <button type="button" class="close-btn" aria-label="关闭写邮件窗口" @click="store.composeOpen = false">
          <X :size="18" />
        </button>
      </div>

      <div class="compose-fields">
        <label class="field-line">
          <span class="field-name">发件邮箱</span>
          <select v-model="fromAccountId">
            <option v-for="acc in store.accounts" :key="acc.id" :value="acc.id">
              {{ acc.label }} &lt;{{ acc.email }}&gt; {{ acc.is_demo ? '(演示)' : '' }}
            </option>
          </select>
        </label>

        <div class="field-line">
          <span class="field-name">收件人</span>
          <input v-model="toInput" type="text" placeholder="输入收件人邮箱，多个请用逗号分隔" />
          <button type="button" class="cc-toggle" @click="showCcBcc = !showCcBcc">
            {{ showCcBcc ? '隐藏抄送' : '抄送/密送' }}
          </button>
        </div>

        <label v-if="showCcBcc" class="field-line">
          <span class="field-name">抄送</span>
          <input v-model="ccInput" type="text" placeholder="抄送邮箱（可选）" />
        </label>

        <label v-if="showCcBcc" class="field-line">
          <span class="field-name">密送</span>
          <input v-model="bccInput" type="text" placeholder="密送邮箱（可选）" />
        </label>

        <label class="field-line">
          <span class="field-name">主题</span>
          <input v-model="subject" type="text" placeholder="填写邮件主题..." />
        </label>
      </div>

      <textarea
        v-model="bodyText"
        class="compose-editor soft-scroll"
        rows="10"
        placeholder="在此倾诉你的文字…（系统将按账号自动附带签名）"
      />

      <div v-if="files.length > 0" class="compose-files">
        <span v-for="(file, idx) in files" :key="`${file.name}-${idx}`" class="file-tag">
          <span>{{ file.name }}</span>
          <button type="button" @click="removeFile(idx)">
            <X :size="12" />
          </button>
        </span>
      </div>

      <div class="compose-footer">
        <div class="footer-left">
          <label class="tool-pill">
            <Paperclip :size="14" />
            <span>添加附件</span>
            <input type="file" multiple hidden @change="handleFileAdd" />
          </label>
          <button type="button" class="tool-pill" :disabled="savingDraft" @click="handleSaveDraft">
            <Save :size="14" />
            <span>{{ savingDraft ? '保存中…' : '存草稿' }}</span>
          </button>
        </div>

        <div class="footer-right">
          <button type="button" class="cancel-btn" @click="store.composeOpen = false">取消</button>
          <button type="button" class="submit-btn" :disabled="sending" @click="handleSend">
            <Send :size="14" />
            <span>{{ store.settings.undo_send_seconds > 0 ? '发送' : '立即发送' }}</span>
          </button>
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
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.compose-modal {
  width: min(720px, 95vw);
  max-height: 88vh;
  border-radius: 20px;
  overflow: hidden;
  background: var(--modal-bg);
  border: 1.5px solid var(--glass-panel-border);
  box-shadow: 0 28px 70px rgba(32, 16, 48, 0.35);
  display: flex;
  flex-direction: column;
}

.compose-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--divider);
}

.compose-header h3 {
  margin: 0;
  font-size: 16.5px;
  font-weight: 700;
}

.close-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.compose-fields {
  padding: 12px 20px 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.field-name {
  width: 64px;
  flex-shrink: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
}

.field-line input,
.field-line select {
  flex: 1;
  padding: 7px 11px;
  border-radius: 10px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.cc-toggle {
  border: none;
  background: transparent;
  color: var(--accent-text);
  font-size: 12px;
  cursor: pointer;
  flex-shrink: 0;
}

.compose-editor {
  margin: 8px 20px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.7;
  resize: vertical;
  min-height: 210px;
  outline: none;
}

.compose-editor:focus {
  border-color: var(--accent-primary);
}

.compose-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 20px 8px;
}

.file-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-text);
  font-size: 12px;
}

.file-tag button {
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  display: inline-flex;
}

.compose-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--divider);
}

.footer-left,
.footer-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 13px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: var(--surface-elevated);
  color: var(--text-secondary);
  font-size: 12.5px;
  cursor: pointer;
}

.cancel-btn {
  padding: 7px 16px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}

.submit-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 18px;
  border-radius: 999px;
  border: none;
  background: var(--accent-gradient);
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
</style>
