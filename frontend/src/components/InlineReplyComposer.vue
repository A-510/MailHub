<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { motion } from 'motion-v'
import { Paperclip, Send, X } from 'lucide-vue-next'
import { useMailStore } from '@/stores/mailStore'
import { useBookMotion } from '@/composables/useBookMotion'
import type { EmailDetail } from '@/types/mail'

interface InlineReplyProps {
  mode: 'reply' | 'reply_all' | 'forward'
  targetEmail: EmailDetail
}

const props = defineProps<InlineReplyProps>()
const emit = defineEmits<{ close: [] }>()

const store = useMailStore()
const { motionMode } = useBookMotion()

const fromAccountId = ref<number>(0)
const toInput = ref('')
const ccInput = ref('')
const subjectInput = ref('')
const bodyText = ref('')
const attachedFiles = ref<File[]>([])
const sending = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const modeTitleMap = {
  reply: '回复发件人',
  reply_all: '回复全部',
  forward: '转发邮件',
}

const selectedAccount = computed(() =>
  store.accounts.find((a) => a.id === fromAccountId.value) ?? store.accounts[0],
)

onMounted(() => {
  // 智能原路回复：优先选择当初收到这封邮件的账号
  if (store.settings.smart_send_from) {
    fromAccountId.value = props.targetEmail.account_id
  } else {
    fromAccountId.value =
      store.settings.default_account_id ?? store.accounts[0]?.id ?? props.targetEmail.account_id
  }

  if (props.mode === 'reply') {
    toInput.value = props.targetEmail.sender_email
    subjectInput.value = props.targetEmail.subject.startsWith('Re:')
      ? props.targetEmail.subject
      : `Re: ${props.targetEmail.subject}`
  } else if (props.mode === 'reply_all') {
    const selfEmail = selectedAccount.value?.email.toLowerCase() ?? ''
    const allRecipients = new Set<string>([
      props.targetEmail.sender_email,
      ...props.targetEmail.to_addresses,
    ])
    allRecipients.delete(selfEmail)
    toInput.value = Array.from(allRecipients).join(', ')
    ccInput.value = props.targetEmail.cc_addresses.filter((x) => !x.includes(selfEmail)).join(', ')
    subjectInput.value = props.targetEmail.subject.startsWith('Re:')
      ? props.targetEmail.subject
      : `Re: ${props.targetEmail.subject}`
  } else {
    toInput.value = ''
    subjectInput.value = props.targetEmail.subject.startsWith('Fwd:')
      ? props.targetEmail.subject
      : `Fwd: ${props.targetEmail.subject}`
    bodyText.value = `\n\n---------- 转发邮件 ----------\n发件人: ${props.targetEmail.sender_name} <${props.targetEmail.sender_email}>\n主题: ${props.targetEmail.subject}\n\n${props.targetEmail.text_body}`
  }

  window.setTimeout(() => textareaRef.value?.focus(), 80)
})

function handleFileSelect(event: Event): void {
  const input = event.target as HTMLInputElement
  if (!input.files) return
  attachedFiles.value = [...attachedFiles.value, ...Array.from(input.files)]
  input.value = ''
}

function removeFile(idx: number): void {
  attachedFiles.value = attachedFiles.value.filter((_, i) => i !== idx)
}

function parseAddressString(raw: string): string[] {
  return raw
    .replace(/;/g, ',')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

async function handleSend(): Promise<void> {
  const toList = parseAddressString(toInput.value)
  if (toList.length === 0) {
    store.pushToast('请填写至少一位收件人邮箱', 'error')
    return
  }
  sending.value = true
  const snapshotBody = bodyText.value
  try {
    const escapedHtml = snapshotBody
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br/>')

    await store.queueOrSendEmail({
      accountId: fromAccountId.value,
      toAddresses: toList,
      ccAddresses: parseAddressString(ccInput.value),
      subject: subjectInput.value,
      htmlBody: `<div>${escapedHtml}</div>`,
      textBody: snapshotBody,
      inReplyTo: props.targetEmail.message_id,
      files: attachedFiles.value,
    })
    emit('close')
  } catch (err) {
    store.pushToast((err as Error).message, 'error')
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <motion.div
    class="inline-reply-card"
    :initial="motionMode === 'off' ? false : { opacity: 0, y: 12 }"
    :animate="{ opacity: 1, y: 0 }"
    :transition="motionMode === 'off' ? { duration: 0 } : { duration: 0.22 }"
  >
    <div class="reply-head">
      <span class="reply-badge">{{ modeTitleMap[mode] }}</span>
      <button type="button" class="close-reply-btn" title="收起回复框" @click="emit('close')">
        <X :size="15" />
      </button>
    </div>

    <div class="reply-fields">
      <label class="field-row">
        <span>发件邮箱</span>
        <select v-model="fromAccountId">
          <option v-for="acc in store.accounts" :key="acc.id" :value="acc.id">
            {{ acc.label }} &lt;{{ acc.email }}&gt;
          </option>
        </select>
      </label>

      <label class="field-row">
        <span>收件人</span>
        <input v-model="toInput" type="text" placeholder="多个地址用英文逗号分隔" />
      </label>

      <label v-if="mode === 'reply_all' || ccInput" class="field-row">
        <span>抄送</span>
        <input v-model="ccInput" type="text" placeholder="抄送邮箱地址（可选）" />
      </label>

      <label class="field-row">
        <span>主题</span>
        <input v-model="subjectInput" type="text" />
      </label>
    </div>

    <textarea
      ref="textareaRef"
      v-model="bodyText"
      class="reply-textarea"
      rows="5"
      placeholder="在此书写回复内容…（发送时将自动附加当前邮箱签名）"
    />

    <div v-if="attachedFiles.length > 0" class="reply-files">
      <span v-for="(file, idx) in attachedFiles" :key="`${file.name}-${idx}`" class="file-chip">
        <span>{{ file.name }}</span>
        <button type="button" @click="removeFile(idx)">
          <X :size="12" />
        </button>
      </span>
    </div>

    <div class="reply-footer">
      <label class="attach-upload-btn">
        <Paperclip :size="14" />
        <span>添加附件</span>
        <input type="file" multiple hidden @change="handleFileSelect" />
      </label>

      <div class="reply-submit-group">
        <button type="button" class="cancel-btn" @click="emit('close')">取消</button>
        <button type="button" class="send-btn" :disabled="sending" @click="handleSend">
          <Send :size="14" />
          <span>{{ store.settings.undo_send_seconds > 0 ? '发送' : '立即发送' }}</span>
        </button>
      </div>
    </div>
  </motion.div>
</template>

<style scoped>
.inline-reply-card {
  flex-shrink: 0;
  min-width: 0;
  margin-top: 16px;
  padding: 14px 16px;
  border-radius: 16px;
  background: var(--surface-elevated);
  border: 1.5px solid var(--selected-mail-border);
  box-shadow: 0 10px 26px rgba(112, 74, 148, 0.12);
}

.reply-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.reply-badge {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-text);
}

.close-reply-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.reply-fields {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.field-row {
  display: grid;
  grid-template-columns: 64px 1fr;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.field-row input,
.field-row select {
  width: 100%;
  min-width: 0;
  padding: 6px 10px;
  border-radius: 9px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 12.5px;
  outline: none;
}

.reply-textarea {
  width: 100%;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text-primary);
  font-size: 13.5px;
  line-height: 1.6;
  resize: vertical;
  outline: none;
}

.reply-textarea:focus {
  border-color: var(--accent-primary);
}

.reply-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-text);
  font-size: 11.5px;
}

.file-chip button {
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  display: inline-flex;
}

.reply-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}

.attach-upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 11px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}

.attach-upload-btn:hover {
  background: var(--accent-soft);
  color: var(--accent-text);
}

.reply-submit-group {
  display: flex;
  gap: 8px;
}

.cancel-btn {
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  cursor: pointer;
}

.send-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  border-radius: 999px;
  border: none;
  background: var(--accent-gradient);
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
</style>
