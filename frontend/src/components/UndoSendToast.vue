<script setup lang="ts">
import { useMailStore } from '@/stores/mailStore'

const store = useMailStore()
</script>

<template>
  <div v-if="store.pendingUndoSend" class="undo-toast" role="status" aria-live="polite">
    <div class="undo-info">
      <span class="undo-text">
        正在准备发送「{{ store.pendingUndoSend.subject }}」({{ store.pendingUndoSend.remainingSeconds }}s)…
      </span>
      <div class="undo-progress-track">
        <div
          class="undo-progress-fill"
          :style="{
            transform: `scaleX(${Math.max(0, store.pendingUndoSend.remainingSeconds / store.pendingUndoSend.totalSeconds)})`,
          }"
        />
      </div>
    </div>
    <div class="undo-actions">
      <button type="button" class="undo-btn" @click="store.cancelPendingSend()">撤销发送</button>
      <button type="button" class="send-now-btn" @click="store.flushPendingSendNow()">立即发出</button>
    </div>
  </div>
</template>

<style scoped>
.undo-toast {
  position: fixed;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  z-index: 95;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  border-radius: 16px;
  background: var(--modal-bg);
  border: 1.5px solid var(--selected-mail-border);
  box-shadow: 0 16px 38px rgba(32, 16, 48, 0.28);
  backdrop-filter: blur(14px);
}

.undo-info {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.undo-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.undo-progress-track {
  width: 220px;
  height: 4px;
  border-radius: 999px;
  background: var(--divider);
  overflow: hidden;
}

.undo-progress-fill {
  width: 100%;
  height: 100%;
  transform-origin: left center;
  background: var(--accent-gradient);
  transition: transform 0.9s linear;
}

.undo-actions {
  display: flex;
  gap: 8px;
}

.undo-btn {
  padding: 6px 12px;
  border-radius: 999px;
  border: none;
  background: var(--badge-pink);
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.send-now-btn {
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
}
</style>
