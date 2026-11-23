<script setup lang="ts">
import { computed } from 'vue'

interface ProviderBadgeProps {
  kind: string
  color?: string
  size?: number
}

const props = withDefaults(defineProps<ProviderBadgeProps>(), {
  color: '#8B6CE8',
  size: 28,
})

const normalized = computed(() => (props.kind || 'mail').toLowerCase())

const badgeBg = computed(() => {
  const map: Record<string, string> = {
    github: '#24292F',
    bilibili: '#FB7299',
    gmail: '#FFFFFF',
    google: '#FFFFFF',
    '163': '#FFE4E8',
    '126': '#FFE4E8',
    qq: '#EBF3FF',
    outlook: '#0078D4',
    school: '#6366F1',
    steam: '#1B2838',
  }
  return map[normalized.value] ?? props.color ?? '#8B6CE8'
})

const badgeColor = computed(() => {
  const map: Record<string, string> = {
    github: '#FFFFFF',
    bilibili: '#FFFFFF',
    gmail: '#EA4335',
    google: '#4285F4',
    '163': '#E11D48',
    '126': '#DC2626',
    qq: '#1E293B',
    outlook: '#FFFFFF',
    school: '#FFFFFF',
    steam: '#66C0F4',
  }
  return map[normalized.value] ?? '#FFFFFF'
})
</script>

<template>
  <span
    class="provider-badge"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      background: badgeBg,
      color: badgeColor,
    }"
    aria-hidden="true"
  >
    <svg v-if="normalized === 'github'" viewBox="0 0 24 24" width="64%" height="64%" fill="currentColor">
      <path
        d="M12 2C6.48 2 2 6.58 2 12.24c0 4.53 2.87 8.37 6.84 9.72.5.09.68-.22.68-.49 0-.24-.01-.88-.01-1.73-2.78.62-3.37-1.37-3.37-1.37-.45-1.18-1.11-1.5-1.11-1.5-.91-.64.07-.63.07-.63 1 .07 1.53 1.05 1.53 1.05.9 1.57 2.35 1.12 2.92.85.09-.66.35-1.12.64-1.37-2.22-.26-4.55-1.14-4.55-5.08 0-1.12.39-2.04 1.03-2.76-.1-.26-.45-1.31.1-2.73 0 0 .84-.27 2.75 1.05a9.35 9.35 0 0 1 5 0c1.91-1.32 2.75-1.05 2.75-1.05.55 1.42.2 2.47.1 2.73.64.72 1.03 1.64 1.03 2.76 0 3.95-2.34 4.82-4.57 5.07.36.32.68.94.68 1.9 0 1.37-.01 2.48-.01 2.82 0 .27.18.59.69.49A10.25 10.25 0 0 0 22 12.24C22 6.58 17.52 2 12 2Z"
      />
    </svg>
    <span v-else-if="normalized === 'bilibili'" class="text-mark" style="font-size: 9px">bili</span>
    <span v-else-if="normalized === 'gmail' || normalized === 'google'" class="google-g">G</span>
    <span v-else-if="normalized === '163' || normalized === '126'" class="text-mark" style="font-size: 10px">
      {{ normalized }}
    </span>
    <svg v-else-if="normalized === 'qq'" viewBox="0 0 24 24" width="62%" height="62%" fill="currentColor">
      <path
        d="M12 2c3.5 0 5.5 2.7 5.5 6.3 0 .8-.1 1.6-.4 2.3 1.1 1.4 1.7 3 1.7 4.4 0 1-.4 1.7-1 1.7-.3 0-.6-.2-.9-.7-.5 1.4-1.5 2.5-2.8 3.1.4.4.7.8.7 1.3 0 .8-1.1 1.4-2.8 1.4s-2.8-.6-2.8-1.4c0-.5.3-.9.7-1.3-1.3-.6-2.3-1.7-2.8-3.1-.3.5-.6.7-.9.7-.6 0-1-.7-1-1.7 0-1.4.6-3 1.7-4.4-.3-.7-.4-1.5-.4-2.3C6.5 4.7 8.5 2 12 2Z"
      />
    </svg>
    <span v-else-if="normalized === 'outlook'" class="text-mark" style="font-size: 12px">O</span>
    <svg v-else-if="normalized === 'school'" viewBox="0 0 24 24" width="60%" height="60%" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M22 10v6M2 10l10-5 10 5-10 5z" />
      <path d="M6 12v5c3 3 9 3 12 0v-5" />
    </svg>
    <svg v-else-if="normalized === 'steam'" viewBox="0 0 24 24" width="60%" height="60%" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="15" cy="9" r="4" />
      <circle cx="8" cy="17" r="3" />
      <path d="M12.2 11.8 9.6 14.7" />
    </svg>
    <span v-else class="text-mark" style="font-size: 12px">{{ normalized.slice(0, 1).toUpperCase() }}</span>
  </span>
</template>

<style scoped>
.provider-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  flex-shrink: 0;
  font-weight: 800;
  box-shadow: 0 2px 8px rgba(42, 24, 62, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.65);
}

.text-mark {
  line-height: 1;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.google-g {
  font-size: 14px;
  font-weight: 800;
  background: conic-gradient(#ea4335 0 90deg, #4285f4 90deg 180deg, #34a853 180deg 270deg, #fbbc05 270deg 360deg);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
</style>
