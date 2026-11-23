<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { motion } from 'motion-v'
import AmbientBackground from '@/components/AmbientBackground.vue'
import TopBar from '@/components/TopBar.vue'
import FolderBookmark from '@/components/FolderBookmark.vue'
import BookSpread from '@/components/BookSpread.vue'
import AccountSwitcher from '@/components/AccountSwitcher.vue'
import ComposeModal from '@/components/ComposeModal.vue'
import SettingsModal from '@/components/SettingsModal.vue'
import OnboardingGuide from '@/components/OnboardingGuide.vue'
import UndoSendToast from '@/components/UndoSendToast.vue'
import ToastContainer from '@/components/ToastContainer.vue'
import { useMailStore } from '@/stores/mailStore'
import { useTheme } from '@/composables/useTheme'
import { useBookMotion } from '@/composables/useBookMotion'

const store = useMailStore()
useTheme()
const { motionMode } = useBookMotion()

function handleGlobalShortcut(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null
  if (
    target &&
    (target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.tagName === 'SELECT' ||
      target.isContentEditable)
  ) {
    return
  }
  if (store.onboardingOpen || store.composeOpen || store.settingsOpen) return

  if (event.key === 'c' || event.key === 'C') {
    event.preventDefault()
    store.openCompose()
  } else if (event.key === 'j' || event.key === 'ArrowDown') {
    const idx = store.emails.findIndex((e) => e.id === store.selectedEmailId)
    const next = store.emails[idx + 1]
    if (next) void store.selectEmail(next.id)
  } else if (event.key === 'k' || event.key === 'ArrowUp') {
    const idx = store.emails.findIndex((e) => e.id === store.selectedEmailId)
    const prev = store.emails[idx - 1]
    if (prev) void store.selectEmail(prev.id)
  } else if ((event.key === 's' || event.key === 'S') && store.selectedEmailId) {
    void store.toggleStar(store.selectedEmailId)
  }
}

onMounted(async () => {
  window.addEventListener('keydown', handleGlobalShortcut)
  await store.bootstrap()
  if (store.shouldAutoStartOnboarding()) {
    window.setTimeout(() => {
      if (!store.composeOpen && !store.settingsOpen) {
        store.startOnboarding(0)
      }
    }, 450)
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalShortcut)
})
</script>

<template>
  <div class="app-root">
    <AmbientBackground />
    <TopBar />

    <motion.div
      class="workspace-grid"
      :initial="motionMode === 'off' ? false : { opacity: 0, scale: 0.97, y: 10 }"
      :animate="{ opacity: 1, scale: 1, y: 0 }"
      :transition="motionMode === 'off' ? { duration: 0 } : { duration: 0.45, ease: [0.22, 1, 0.36, 1] }"
    >
      <FolderBookmark />
      <BookSpread />
      <AccountSwitcher />
    </motion.div>

    <ComposeModal />
    <SettingsModal />
    <OnboardingGuide />
    <UndoSendToast />
    <ToastContainer />
  </div>
</template>

<style scoped>
.app-root {
  position: relative;
  width: 100vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.workspace-grid {
  position: relative;
  z-index: 10;
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: stretch;
  gap: 10px;
  padding: 6px 22px 18px;
}

@media (max-width: 1180px) {
  .workspace-grid {
    gap: 6px;
    padding: 4px 10px 12px;
  }
}
</style>
