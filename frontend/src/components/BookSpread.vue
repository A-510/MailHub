<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { motion } from 'motion-v'
import { useMailStore } from '@/stores/mailStore'
import { useBookMotion } from '@/composables/useBookMotion'
import BookPeekMascot from '@/components/BookPeekMascot.vue'
import MailListPage from '@/components/MailListPage.vue'
import MailDetailPage from '@/components/MailDetailPage.vue'

const store = useMailStore()
const { motionMode, pageFlipDurationMs } = useBookMotion()

const isFlipping = ref(false)
const flipKey = ref(0)
const flipDirection = ref<'forward' | 'backward'>('forward')
let flipEndTimer: number | null = null

function cancelFlipTimer(): void {
  if (flipEndTimer !== null) {
    window.clearTimeout(flipEndTimer)
    flipEndTimer = null
  }
}

watch(
  () => store.bookFlipTick,
  (tick) => {
    if (tick === 0 || motionMode.value === 'off') {
      isFlipping.value = false
      return
    }
    // 遵循 TR-06：快速连点时立即打断旧翻页并向最新目标重启翻页
    cancelFlipTimer()
    flipDirection.value = store.bookFlipDirection
    flipKey.value += 1
    isFlipping.value = true
    flipEndTimer = window.setTimeout(() => {
      isFlipping.value = false
      flipEndTimer = null
    }, pageFlipDurationMs.value + 40)
  },
)

onUnmounted(() => {
  cancelFlipTimer()
})
</script>

<template>
  <main class="book-stage-wrap">
    <!-- 从书本右侧背面探头爬出的装饰立绘，位于 .book-shell 之前且 z-index 更低以形成真实遮挡 -->
    <BookPeekMascot v-if="store.settings.show_mascots" />

    <div class="book-shell" :class="{ 'reading-focus': store.readingFullscreen }">
      <div class="book-pages-stage">
        <div v-show="!store.readingFullscreen" class="book-page-left">
          <MailListPage />
        </div>

        <div v-show="!store.readingFullscreen" class="book-spine-crease" aria-hidden="true" />

        <div class="book-page-right" :class="{ 'full-span': store.readingFullscreen }">
          <MailDetailPage />
        </div>

        <!-- 3D 翻页临时视觉代理（仅当切邮箱且开启动效时显示） -->
        <motion.div
          v-if="isFlipping && motionMode === 'full'"
          :key="flipKey"
          class="book-flip-proxy"
          :class="{ 'flip-backward': flipDirection === 'backward' }"
          aria-hidden="true"
          :initial="{ rotateY: 0, opacity: 0.96 }"
          :animate="{
            rotateY: flipDirection === 'forward' ? -180 : 180,
            opacity: [0.96, 1, 0.2],
          }"
          :transition="{
            duration: pageFlipDurationMs / 1000,
            ease: [0.24, 0.9, 0.32, 1],
          }"
        >
          <div class="book-flip-face front" />
          <div class="book-flip-face back" />
        </motion.div>

        <!-- 轻柔模式替代过渡遮罩 -->
        <motion.div
          v-if="isFlipping && motionMode === 'gentle'"
          :key="`gentle-${flipKey}`"
          class="gentle-veil"
          aria-hidden="true"
          :initial="{ opacity: 0.35 }"
          :animate="{ opacity: 0 }"
          :transition="{ duration: 0.22 }"
        />
      </div>
    </div>
  </main>
</template>

<style scoped>
.book-stage-wrap {
  position: relative;
  z-index: 10;
  overflow: visible;
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  padding: 4px 6px 6px;
}

.book-shell {
  position: relative;
  z-index: 3;
  width: 100%;
  height: 100%;
  display: flex;
}

.book-shell.reading-focus .book-pages-stage {
  grid-template-columns: 1fr;
}

.book-page-right.full-span {
  grid-column: 1 / -1;
}

.gentle-veil {
  position: absolute;
  inset: 0;
  background: var(--page-right-bg);
  pointer-events: none;
  z-index: 25;
}
</style>
