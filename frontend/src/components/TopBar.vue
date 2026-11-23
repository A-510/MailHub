<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import {
  Bell,
  HelpCircle,
  Maximize2,
  Minimize2,
  Moon,
  RefreshCw,
  Settings,
  Sparkles,
  Sun,
} from 'lucide-vue-next'
import { useMailStore } from '@/stores/mailStore'
import { useTheme } from '@/composables/useTheme'

const store = useMailStore()
const { resolvedTheme, setThemeWithTransition } = useTheme()

const bellOpen = ref(false)
const isFullscreen = ref(false)
const bellBoxRef = ref<HTMLElement | null>(null)

function handleToggleTheme(event: MouseEvent): void {
  const next = resolvedTheme.value === 'light' ? 'dark' : 'light'
  void setThemeWithTransition(next, event)
}

async function handleToggleFullscreen(): Promise<void> {
  try {
    if (!document.fullscreenElement) {
      await document.documentElement.requestFullscreen()
      isFullscreen.value = true
    } else {
      await document.exitFullscreen()
      isFullscreen.value = false
    }
  } catch {
    // 浏览器阻止全屏时切换专注阅读模式
    store.readingFullscreen = !store.readingFullscreen
  }
}

function handleDocClick(event: MouseEvent): void {
  if (bellOpen.value && bellBoxRef.value && !bellBoxRef.value.contains(event.target as Node)) {
    bellOpen.value = false
  }
}

function formatLogTime(iso: string): string {
  try {
    const dt = new Date(iso)
    return dt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return ''
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocClick)
})

onUnmounted(() => {
  document.removeEventListener('click', handleDocClick)
})
</script>

<template>
  <header class="top-bar">
    <!-- 左上品牌标识，严格对照界面框架图 -->
    <div class="brand-lockup">
      <div class="brand-emblem" aria-hidden="true">
        <svg viewBox="0 0 40 40" width="38" height="38">
          <defs>
            <linearGradient id="mailhub-grad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#FF9DC4" />
              <stop offset="100%" stop-color="#9A7DF4" />
            </linearGradient>
          </defs>
          <rect x="3" y="6" width="34" height="28" rx="9" fill="url(#mailhub-grad)" stroke="#fff" stroke-width="1.5" />
          <path d="M9 14l11 8.5L31 14" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
          <rect x="9" y="13" width="22" height="15" rx="3" fill="none" stroke="#fff" stroke-width="2" />
        </svg>
      </div>
      <div class="brand-text">
        <div class="brand-title-row">
          <span class="brand-title">MailHub</span>
          <Sparkles class="brand-sparkle" :size="16" />
        </div>
        <div class="brand-subtitle">多邮箱聚合 · 一站收发</div>
      </div>
    </div>

    <!-- 右上悬浮磨砂胶囊工具栏 -->
    <div class="top-actions-pill" data-tour="topbar-actions">
      <div ref="bellBoxRef" class="bell-wrapper">
        <button
          type="button"
          class="pill-btn"
          title="同步日志与通知提醒"
          aria-label="同步日志与通知提醒"
          @click="bellOpen = !bellOpen"
        >
          <Bell :size="17" />
          <span v-if="store.folderCounts.inbox_unread > 0" class="bell-dot" />
        </button>

        <div v-if="bellOpen" class="notif-dropdown">
          <div class="notif-header">
            <span>最近同步与提醒</span>
            <button
              type="button"
              class="notif-sync-btn"
              :disabled="store.syncing"
              @click="store.syncAll()"
            >
              <RefreshCw :size="13" :class="{ spinning: store.syncing }" />
              <span>立即同步</span>
            </button>
          </div>
          <div class="notif-list soft-scroll">
            <div v-if="store.notifications.length === 0" class="notif-empty">
              暂无同步记录
            </div>
            <div v-for="log in store.notifications" :key="log.id" class="notif-item">
              <span class="notif-status-dot" :class="log.status" />
              <div class="notif-body">
                <div class="notif-msg">{{ log.message }}</div>
                <div class="notif-time">{{ formatLogTime(log.created_at) }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <button
        type="button"
        class="pill-btn"
        :title="resolvedTheme === 'light' ? '切换至暗黑星夜模式' : '切换至明亮樱花模式'"
        aria-label="切换明暗主题"
        @click="handleToggleTheme"
      >
        <Moon v-if="resolvedTheme === 'light'" :size="17" />
        <Sun v-else :size="17" />
      </button>

      <button
        type="button"
        class="pill-btn"
        data-tour="replay-onboarding-btn"
        title="新手引导：查看添加邮箱与使用教程"
        aria-label="打开新手引导"
        @click="store.startOnboarding(0)"
      >
        <HelpCircle :size="17" />
      </button>

      <button
        type="button"
        class="pill-btn"
        title="打开设置中心"
        aria-label="打开设置中心"
        @click="store.openSettings('accounts')"
      >
        <Settings :size="17" />
      </button>

      <div class="pill-divider" />

      <button
        type="button"
        class="pill-btn"
        :title="isFullscreen ? '退出全屏' : '全屏窗口'"
        aria-label="切换全屏"
        @click="handleToggleFullscreen"
      >
        <Minimize2 v-if="isFullscreen" :size="16" />
        <Maximize2 v-else :size="16" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.top-bar {
  position: relative;
  z-index: 30;
  height: 54px;
  padding: 6px 24px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.brand-lockup {
  display: flex;
  align-items: center;
  gap: 11px;
  user-select: none;
}

.brand-emblem {
  display: flex;
  align-items: center;
  justify-content: center;
  filter: drop-shadow(0 4px 10px rgba(82, 46, 108, 0.28));
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-title-row {
  display: flex;
  align-items: center;
  gap: 5px;
}

.brand-title {
  font-family: var(--font-serif);
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 0.01em;
  color: var(--topbar-title-color);
  text-shadow: 0 2px 10px rgba(64, 34, 82, 0.78), 0 0 3px rgba(64, 34, 82, 0.65);
  line-height: 1.05;
}

.brand-sparkle {
  color: #ffe39b;
  filter: drop-shadow(0 1px 4px rgba(0, 0, 0, 0.35));
}

.brand-subtitle {
  font-size: 11.5px;
  color: rgba(255, 255, 255, 0.96);
  text-shadow: 0 2px 10px rgba(64, 34, 82, 0.78), 0 0 3px rgba(64, 34, 82, 0.65);
  letter-spacing: 0.06em;
  margin-top: 1px;
}

.top-actions-pill {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border-radius: 999px;
  background: var(--topbar-pill-bg);
  border: 1px solid var(--topbar-pill-border);
  backdrop-filter: blur(14px);
  box-shadow: 0 8px 24px rgba(32, 16, 48, 0.22);
}

.pill-btn {
  position: relative;
  width: 34px;
  height: 32px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.18s ease, transform 0.18s ease;
}

.pill-btn:hover {
  background: rgba(255, 255, 255, 0.18);
  transform: translateY(-1px);
}

.pill-divider {
  width: 1px;
  height: 16px;
  margin: 0 2px;
  background: rgba(255, 255, 255, 0.24);
}

.bell-wrapper {
  position: relative;
}

.bell-dot {
  position: absolute;
  top: 6px;
  right: 7px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #ff77a9;
  box-shadow: 0 0 0 2px rgba(88, 65, 105, 0.8);
}

.notif-dropdown {
  position: absolute;
  top: 44px;
  right: -40px;
  width: 320px;
  border-radius: 16px;
  background: var(--modal-bg);
  border: 1px solid var(--glass-panel-border);
  box-shadow: var(--glass-panel-shadow);
  backdrop-filter: blur(18px);
  overflow: hidden;
  z-index: 60;
}

.notif-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  font-size: 13px;
  font-weight: 700;
  border-bottom: 1px solid var(--divider);
}

.notif-sync-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: var(--accent-soft);
  color: var(--accent-text);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.notif-list {
  max-height: 260px;
  padding: 8px 10px;
}

.notif-empty {
  padding: 20px;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-muted);
}

.notif-item {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 8px 6px;
  border-radius: 10px;
}

.notif-item + .notif-item {
  border-top: 1px solid var(--divider);
}

.notif-status-dot {
  width: 8px;
  height: 8px;
  margin-top: 5px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--accent-primary);
}

.notif-status-dot.success {
  background: var(--success);
}

.notif-status-dot.error {
  background: var(--danger);
}

.notif-msg {
  font-size: 12.5px;
  line-height: 1.45;
  color: var(--text-primary);
}

.notif-time {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
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
