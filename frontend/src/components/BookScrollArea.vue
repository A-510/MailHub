<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

interface BookScrollAreaProps {
  contentClass?: string
}

defineProps<BookScrollAreaProps>()

const viewportRef = ref<HTMLElement | null>(null)
const contentRef = ref<HTMLElement | null>(null)
const trackRef = ref<HTMLElement | null>(null)

const hasOverflow = ref(false)
const thumbHeight = ref(40)
const thumbTop = ref(0)
const isDragging = ref(false)
const isHoveringTrack = ref(false)

let resizeObserver: ResizeObserver | null = null
let mutationObserver: MutationObserver | null = null
let dragStartY = 0
let dragStartScrollTop = 0

function updateMetrics(): void {
  const viewport = viewportRef.value
  if (!viewport) return

  const { scrollHeight, clientHeight, scrollTop } = viewport
  const overflow = scrollHeight > clientHeight + 2
  hasOverflow.value = overflow
  if (!overflow) {
    thumbTop.value = 0
    return
  }

  const trackHeight = trackRef.value?.clientHeight || Math.max(40, clientHeight - 16)
  const rawThumb = (clientHeight / scrollHeight) * trackHeight
  const clampedThumb = Math.min(trackHeight, Math.max(36, rawThumb))
  const maxScroll = Math.max(1, scrollHeight - clientHeight)
  const maxTop = Math.max(0, trackHeight - clampedThumb)

  thumbHeight.value = clampedThumb
  thumbTop.value = Math.min(maxTop, Math.max(0, (scrollTop / maxScroll) * maxTop))
}

function handleScroll(): void {
  updateMetrics()
}

function handleTrackClick(event: MouseEvent): void {
  const viewport = viewportRef.value
  const track = trackRef.value
  if (!viewport || !track || event.target !== track) return

  const rect = track.getBoundingClientRect()
  const clickY = event.clientY - rect.top
  const ratio = Math.min(1, Math.max(0, (clickY - thumbHeight.value / 2) / Math.max(1, rect.height - thumbHeight.value)))
  const maxScroll = Math.max(0, viewport.scrollHeight - viewport.clientHeight)
  viewport.scrollTo({
    top: ratio * maxScroll,
    behavior: 'smooth',
  })
}

function handlePointerMove(event: PointerEvent): void {
  if (!isDragging.value) return
  const viewport = viewportRef.value
  const track = trackRef.value
  if (!viewport || !track) return

  const maxScroll = Math.max(0, viewport.scrollHeight - viewport.clientHeight)
  const maxTop = Math.max(1, track.clientHeight - thumbHeight.value)
  const deltaY = event.clientY - dragStartY
  viewport.scrollTop = dragStartScrollTop + (deltaY / maxTop) * maxScroll
}

function handlePointerUp(): void {
  if (!isDragging.value) return
  isDragging.value = false
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', handlePointerUp)
  document.body.style.userSelect = ''
}

function handleThumbPointerDown(event: PointerEvent): void {
  const viewport = viewportRef.value
  if (!viewport) return
  event.preventDefault()
  event.stopPropagation()

  isDragging.value = true
  dragStartY = event.clientY
  dragStartScrollTop = viewport.scrollTop
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', handlePointerUp)
}

onMounted(() => {
  updateMetrics()

  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => updateMetrics())
    if (viewportRef.value) resizeObserver.observe(viewportRef.value)
    if (contentRef.value) resizeObserver.observe(contentRef.value)
  }

  if (typeof MutationObserver !== 'undefined' && contentRef.value) {
    mutationObserver = new MutationObserver(() => {
      window.requestAnimationFrame(updateMetrics)
    })
    mutationObserver.observe(contentRef.value, {
      childList: true,
      subtree: true,
      attributes: false,
    })
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  mutationObserver?.disconnect()
  handlePointerUp()
})

defineExpose({
  viewportRef,
  contentRef,
})
</script>

<template>
  <div class="book-scroll-wrap">
    <div
      ref="viewportRef"
      class="book-scroll-viewport"
      @scroll="handleScroll"
    >
      <div
        ref="contentRef"
        class="book-scroll-content"
        :class="[contentClass, { 'has-ribbon': hasOverflow }]"
      >
        <slot />
      </div>
    </div>

    <!-- 契合手账主题的悬浮丝带滚动条 -->
    <div
      v-show="hasOverflow"
      ref="trackRef"
      class="ribbon-track"
      :class="{ active: isDragging || isHoveringTrack }"
      aria-hidden="true"
      @mouseenter="isHoveringTrack = true"
      @mouseleave="isHoveringTrack = false"
      @click="handleTrackClick"
    >
      <div
        class="ribbon-thumb"
        :style="{
          height: `${thumbHeight}px`,
          transform: `translateY(${thumbTop}px)`,
        }"
        @pointerdown="handleThumbPointerDown"
      >
        <span class="ribbon-gem" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.book-scroll-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
}

.book-scroll-viewport {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.book-scroll-viewport::-webkit-scrollbar {
  display: none;
  width: 0;
  height: 0;
}

.book-scroll-content {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.book-scroll-content.has-ribbon {
  padding-right: 14px;
}

.ribbon-track {
  position: absolute;
  top: 8px;
  bottom: 8px;
  right: 1px;
  width: 10px;
  display: flex;
  justify-content: center;
  border-radius: 999px;
  cursor: pointer;
  z-index: 8;
}

.ribbon-track::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  width: 4px;
  border-radius: 999px;
  background: var(--ribbon-track-bg);
  transition: width 0.18s ease, background-color 0.18s ease;
}

.ribbon-track.active::before {
  width: 6px;
}

.ribbon-thumb {
  position: relative;
  width: 6px;
  border-radius: 999px;
  background: var(--ribbon-thumb-bg);
  box-shadow: var(--ribbon-thumb-glow);
  cursor: grab;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: width 0.16s ease, filter 0.16s ease;
  will-change: transform;
}

.ribbon-track.active .ribbon-thumb {
  width: 8px;
  filter: brightness(1.08);
}

.ribbon-thumb:active {
  cursor: grabbing;
}

.ribbon-gem {
  width: 4px;
  height: 4px;
  border-radius: 1px;
  transform: rotate(45deg);
  background: var(--ribbon-gem-color);
  opacity: 0.85;
  pointer-events: none;
}
</style>
