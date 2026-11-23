<script setup lang="ts">
import { useMailStore } from '@/stores/mailStore'

const store = useMailStore()
</script>

<template>
  <div class="toast-stack" aria-live="polite">
    <div
      v-for="item in store.toasts"
      :key="item.id"
      class="toast-item"
      :class="item.type"
    >
      {{ item.text }}
    </div>
  </div>
</template>

<style scoped>
.toast-stack {
  position: fixed;
  top: 66px;
  right: 26px;
  z-index: 100;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.toast-item {
  padding: 9px 15px;
  border-radius: 12px;
  font-size: 12.5px;
  font-weight: 600;
  color: #ffffff;
  background: rgba(58, 45, 70, 0.9);
  box-shadow: 0 10px 24px rgba(24, 12, 38, 0.28);
  backdrop-filter: blur(10px);
}

.toast-item.success {
  background: rgba(16, 152, 108, 0.92);
}

.toast-item.error {
  background: rgba(215, 38, 78, 0.94);
}
</style>
