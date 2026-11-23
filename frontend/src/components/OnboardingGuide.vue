<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Sparkles, X } from 'lucide-vue-next'
import { useMailStore } from '@/stores/mailStore'
import { useBookMotion } from '@/composables/useBookMotion'
import {
  CLICK_CURSOR_SRC,
  computeCardRect,
  DIRECTIONAL_ARROWS,
  ONBOARDING_STEPS,
  type OnboardingStepConfig,
  type RectBox,
} from '@/composables/useOnboardingTour'

const store = useMailStore()
const { motionMode } = useBookMotion()

const viewportWidth = ref(window.innerWidth)
const viewportHeight = ref(window.innerHeight)
const spotlightRect = ref<RectBox | null>(null)
const clickCursorPos = ref<{ left: number; top: number } | null>(null)
const cardRef = ref<HTMLElement | null>(null)
const measuredCardHeight = ref(315)
let measureTimer: number | null = null

const totalSteps = ONBOARDING_STEPS.length
const currentStep = computed<OnboardingStepConfig>(
  () => ONBOARDING_STEPS[Math.min(Math.max(0, store.onboardingStep), totalSteps - 1)],
)

const isFirstStep = computed(() => store.onboardingStep <= 0)
const isLastStep = computed(() => store.onboardingStep >= totalSteps - 1)
const cardWidth = computed(() => Math.min(444, Math.max(308, viewportWidth.value - 32)))

/**
 * 同步设置弹窗显隐并重新测量目标元素与卡片位置
 */
async function syncAndMeasure(): Promise<void> {
  if (!store.onboardingOpen) return

  const step = currentStep.value
  if (step.requiresSettingsAccounts) {
    if (!store.settingsOpen || store.settingsTab !== 'accounts') {
      store.openSettings('accounts')
    }
  } else if (store.settingsOpen) {
    store.settingsOpen = false
  }

  await nextTick()
  if (measureTimer !== null) {
    window.clearTimeout(measureTimer)
  }

  // 等待弹窗打开/关闭与 motion-v 动画稳定后再精确采样坐标
  const delayMs = step.requiresSettingsAccounts ? 260 : 120
  measureTimer = window.setTimeout(() => {
    measureTargets()
  }, delayMs)
}

/**
 * 测量当前步骤聚光灯锚点与点击指针坐标
 */
function measureTargets(): void {
  viewportWidth.value = window.innerWidth
  viewportHeight.value = window.innerHeight

  const step = currentStep.value
  if (!step.targetSelector) {
    spotlightRect.value = null
    clickCursorPos.value = null
    nextTick(() => updateCardHeight())
    return
  }

  const el = document.querySelector(step.targetSelector) as HTMLElement | null
  if (!el) {
    spotlightRect.value = null
    clickCursorPos.value = null
    return
  }

  // 如果目标位于可滚动的设置面板内部，确保完整滚入可视区域
  if (step.requiresSettingsAccounts) {
    el.scrollIntoView({ block: 'center', behavior: 'instant' })
  }

  const raw = el.getBoundingClientRect()
  const pad = step.spotlightPadding
  spotlightRect.value = {
    left: Math.max(4, raw.left - pad),
    top: Math.max(4, raw.top - pad),
    width: Math.min(window.innerWidth - 8, raw.width + pad * 2),
    height: Math.min(window.innerHeight - 8, raw.height + pad * 2),
  }

  if (step.clickCursorSelector) {
    const cursorEl = document.querySelector(step.clickCursorSelector) as HTMLElement | null
    if (cursorEl) {
      const cr = cursorEl.getBoundingClientRect()
      clickCursorPos.value = {
        left: Math.min(window.innerWidth - 52, cr.right - 14),
        top: cr.bottom - 6,
      }
    } else {
      clickCursorPos.value = null
    }
  } else {
    clickCursorPos.value = null
  }

  nextTick(() => updateCardHeight())
}

function updateCardHeight(): void {
  if (cardRef.value) {
    const h = cardRef.value.offsetHeight
    if (h > 100) {
      measuredCardHeight.value = h
    }
  }
}

const layoutResult = computed(() => {
  const needsTopMascotSpace = currentStep.value.mascotPlacement !== 'inline-top'
  return computeCardRect(
    spotlightRect.value,
    currentStep.value.preferredSide,
    cardWidth.value,
    measuredCardHeight.value,
    viewportWidth.value,
    viewportHeight.value,
    needsTopMascotSpace ? 96 : 16,
  )
})

/**
 * 若卡片顶边贴近视口上方（< 92px），或顶角外探吉祥物会压到聚光灯高亮目标，
 * 则自动将吉祥物优雅收入卡片内嵌栏，避免遮挡目标文字或被视口截断
 */
const effectiveMascotPlacement = computed(() => {
  const base = currentStep.value.mascotPlacement
  if (base === 'inline-top') return 'inline-top'
  const card = layoutResult.value.rect
  if (card.top < 92) return 'inline-top'

  const s = spotlightRect.value
  if (s) {
    const mascotLeft = base === 'top-left' ? card.left - 14 : card.left + card.width - 100
    const mascotRight = mascotLeft + 112
    const mascotTop = card.top - 86
    const mascotBottom = card.top + 25
    const overlapsSpotlight =
      mascotLeft < s.left + s.width &&
      mascotRight > s.left &&
      mascotTop < s.top + s.height &&
      mascotBottom > s.top
    if (overlapsSpotlight) {
      return 'inline-top'
    }
  }
  return base
})

const effectiveMascotLabel = computed(() =>
  layoutResult.value.actualSide === 'bottom'
    ? '照着上方高亮区域填入授权信息吧 ↑'
    : layoutResult.value.actualSide === 'top'
      ? '看下方高亮区域填写真实邮箱哦 ↓'
      : '重点提示看这里哦 ↓',
)

const cardStyle = computed(() => ({
  left: `${layoutResult.value.rect.left}px`,
  top: `${layoutResult.value.rect.top}px`,
  width: `${layoutResult.value.rect.width}px`,
}))

const spotlightRingStyle = computed(() => {
  const s = spotlightRect.value
  if (!s) return {}
  return {
    left: `${s.left}px`,
    top: `${s.top}px`,
    width: `${s.width}px`,
    height: `${s.height}px`,
  }
})

/**
 * 依据卡片与聚光灯之间的真实方位（actualSide），自动匹配朝向正确的箭头贴纸并定位在空白间隙中，
 * 确保绝不压盖卡片标题与文字内容
 */
const arrowVisual = computed<{ src: string; style: Record<string, string> } | null>(() => {
  if (viewportWidth.value < 760) return null
  const card = layoutResult.value.rect
  const side = layoutResult.value.actualSide
  const s = spotlightRect.value

  const buildVisual = (): { src: string; style: Record<string, string> } => {
    if (side === 'center' || !s) {
      return {
        src: currentStep.value.arrowSrc,
        style: {
          left: `${Math.min(viewportWidth.value - 125, card.left + card.width - 130)}px`,
          top: `${Math.max(12, card.top - 58)}px`,
          width: '108px',
        },
      }
    }

    if (side === 'left') {
      const arrowW = 104
      const left = Math.max(card.left + card.width - 6, Math.min(s.left - arrowW - 2, (card.left + card.width + s.left - arrowW) / 2))
      const top = Math.min(
        Math.max(12, Math.min(card.top + 38, s.top + 16)),
        viewportHeight.value - 68,
      )
      return {
        src: currentStep.value.id === 'fill-credentials' ? DIRECTIONAL_ARROWS.comicRight : DIRECTIONAL_ARROWS.right,
        style: { left: `${left}px`, top: `${top}px`, width: `${arrowW}px` },
      }
    }

    if (side === 'right') {
      const arrowW = 104
      const left = Math.min(card.left - arrowW + 6, Math.max(s.left + s.width + 2, (s.left + s.width + card.left - arrowW) / 2))
      const top = Math.min(
        Math.max(12, s.top + s.height / 2 - 22),
        viewportHeight.value - 68,
      )
      return {
        src: DIRECTIONAL_ARROWS.left,
        style: { left: `${left}px`, top: `${top}px`, width: `${arrowW}px` },
      }
    }

    if (side === 'top') {
      // 卡片在上方、目标在下方：使用向下指粗粉箭头，放置在卡片底边与聚光灯顶边之间的间隙内
      const arrowW = 72
      const arrowH = 61
      const gapMidY = (card.top + card.height + s.top) / 2 - arrowH / 2
      const left = Math.min(
        Math.max(16, s.left + s.width / 2 - arrowW / 2),
        viewportWidth.value - arrowW - 16,
      )
      return {
        src: DIRECTIONAL_ARROWS.down,
        style: { left: `${left}px`, top: `${Math.max(12, gapMidY)}px`, width: `${arrowW}px` },
      }
    }

    // side === 'bottom'：卡片在目标下方，箭头向上指
    if (currentStep.value.arrowPlacement === 'to-top-right') {
      const arrowW = 104
      const left = Math.min(viewportWidth.value - arrowW - 16, Math.max(card.left + card.width - 10, s.left - 24))
      const top = Math.max(12, s.top + s.height + 2)
      return {
        src: DIRECTIONAL_ARROWS.swirlUpRight,
        style: { left: `${left}px`, top: `${top}px`, width: `${arrowW}px` },
      }
    }

    const arrowW = 74
    const arrowH = 66
    const gapMidY = (s.top + s.height + card.top) / 2 - arrowH / 2
    const left = Math.min(
      Math.max(16, s.left + s.width / 2 - arrowW / 2),
      viewportWidth.value - arrowW - 16,
    )
    return {
      src: DIRECTIONAL_ARROWS.up,
      style: { left: `${left}px`, top: `${Math.max(10, gapMidY)}px`, width: `${arrowW}px` },
    }
  }

  const candidate = buildVisual()
  return candidate.src ? candidate : null
})

function handlePrev(): void {
  if (store.onboardingStep > 0) {
    store.onboardingStep -= 1
  }
}

function handleNext(): void {
  if (!isLastStep.value) {
    store.onboardingStep += 1
  } else {
    finishTour()
  }
}

function handleJumpTo(idx: number): void {
  store.onboardingStep = idx
}

function finishTour(): void {
  store.closeOnboarding(true)
}

function handleSkip(): void {
  if (currentStep.value.requiresSettingsAccounts && store.settingsOpen) {
    store.settingsOpen = false
  }
  store.closeOnboarding(true)
}

function handleSecondaryAction(): void {
  const kind = currentStep.value.secondaryActionKind
  if (kind === 'stay-in-accounts') {
    store.openSettings('accounts')
    store.closeOnboarding(true)
    store.pushToast('已定位至添加邮箱表单，请填写后验证绑定 ✨', 'info')
  } else if (kind === 'open-accounts') {
    store.closeOnboarding(true)
    store.openSettings('accounts')
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (!store.onboardingOpen) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    handleSkip()
  } else if (event.key === 'ArrowRight' || event.key === 'Enter') {
    event.preventDefault()
    event.stopPropagation()
    handleNext()
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    event.stopPropagation()
    handlePrev()
  }
}

function handleViewportChange(): void {
  if (store.onboardingOpen) {
    measureTargets()
  }
}

watch(
  () => [store.onboardingOpen, store.onboardingStep],
  ([open]) => {
    if (open) {
      void syncAndMeasure()
    } else if (measureTimer !== null) {
      window.clearTimeout(measureTimer)
      measureTimer = null
    }
  },
)

watch(effectiveMascotPlacement, () => {
  void nextTick(() => {
    window.requestAnimationFrame(() => updateCardHeight())
  })
})

onMounted(() => {
  window.addEventListener('resize', handleViewportChange)
  window.addEventListener('keydown', handleKeydown, true)
  if (store.onboardingOpen) {
    void syncAndMeasure()
  }
})

onUnmounted(() => {
  if (measureTimer !== null) {
    window.clearTimeout(measureTimer)
  }
  window.removeEventListener('resize', handleViewportChange)
  window.removeEventListener('keydown', handleKeydown, true)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="store.onboardingOpen"
      class="onboarding-overlay"
      :class="{ 'no-motion': motionMode === 'off' }"
      role="dialog"
      aria-modal="true"
      aria-label="MailHub 新手引导向导"
    >
      <!-- SVG 柔暗聚光灯遮罩层 -->
      <svg class="spotlight-svg" :width="viewportWidth" :height="viewportHeight">
        <defs>
          <mask id="mailhub-onboarding-mask">
            <rect x="0" y="0" :width="viewportWidth" :height="viewportHeight" fill="white" />
            <rect
              v-if="spotlightRect"
              :x="spotlightRect.left"
              :y="spotlightRect.top"
              :width="spotlightRect.width"
              :height="spotlightRect.height"
              rx="16"
              ry="16"
              fill="black"
            />
          </mask>
        </defs>
        <rect
          x="0"
          y="0"
          :width="viewportWidth"
          :height="viewportHeight"
          fill="rgba(26, 14, 38, 0.56)"
          mask="url(#mailhub-onboarding-mask)"
          @click.stop
        />
      </svg>

      <!-- 高亮框梦幻樱花光环 -->
      <div
        v-if="spotlightRect"
        class="spotlight-ring"
        :style="spotlightRingStyle"
        aria-hidden="true"
      />

      <!-- 按钮点击小指针贴纸（第 2 步指向 + 按钮） -->
      <img
        v-if="clickCursorPos && CLICK_CURSOR_SRC"
        :src="CLICK_CURSOR_SRC"
        alt="点击提示指针"
        class="sticker-click-cursor"
        :style="{ left: `${clickCursorPos.left}px`, top: `${clickCursorPos.top}px` }"
        aria-hidden="true"
      />

      <!-- 梦幻箭头贴纸（随卡片与目标方位动态摆放） -->
      <img
        v-if="arrowVisual"
        :src="arrowVisual.src"
        alt="向导指示箭头"
        class="sticker-arrow"
        :class="`arrow-${layoutResult.actualSide}`"
        :style="arrowVisual.style"
        aria-hidden="true"
      />

      <!-- 核心向导卡片 -->
      <div ref="cardRef" class="onboarding-card" :style="cardStyle">
        <!-- 探出卡片顶角的向导吉祥物 -->
        <img
          v-if="effectiveMascotPlacement !== 'inline-top' && currentStep.mascotSrc"
          :src="currentStep.mascotSrc"
          alt="MailHub 可爱向导"
          class="sticker-mascot-corner"
          :class="effectiveMascotPlacement"
        />

        <!-- 顶部步骤进度条与跳过按钮 -->
        <div class="card-top-bar">
          <div class="step-badge">
            <Sparkles :size="13" />
            <span>第 {{ store.onboardingStep + 1 }} / {{ totalSteps }} 步</span>
          </div>

          <div class="step-dots" role="tablist" aria-label="引导进度">
            <button
              v-for="(s, idx) in ONBOARDING_STEPS"
              :key="s.id"
              type="button"
              class="step-dot"
              :class="{ active: idx === store.onboardingStep, passed: idx < store.onboardingStep }"
              :title="`跳至第 ${idx + 1} 步：${s.title}`"
              :aria-label="`第 ${idx + 1} 步`"
              @click="handleJumpTo(idx)"
            />
          </div>

          <button
            type="button"
            class="close-tour-btn"
            title="跳过引导"
            aria-label="跳过引导"
            @click="handleSkip"
          >
            <X :size="15" />
          </button>
        </div>

        <!-- 行内吉祥物提示行（空间受限时自动收纳，绝不被视口裁断） -->
        <div v-if="effectiveMascotPlacement === 'inline-top' && currentStep.mascotSrc" class="inline-mascot-row">
          <img
            :src="currentStep.mascotSrc"
            alt="小向导贴纸"
            class="sticker-mascot-inline"
          />
          <div class="inline-speech">{{ effectiveMascotLabel }}</div>
        </div>

        <h3 class="card-title">{{ currentStep.title }}</h3>
        <p class="card-desc">{{ currentStep.description }}</p>

        <ul v-if="currentStep.tips.length > 0" class="card-tips">
          <li v-for="(tip, idx) in currentStep.tips" :key="idx">
            <span class="tip-bullet" aria-hidden="true">✦</span>
            <span>{{ tip }}</span>
          </li>
        </ul>

        <!-- 底部导航按钮栏 -->
        <div class="card-actions">
          <button
            type="button"
            class="btn-skip"
            @click="handleSkip"
          >
            跳过
          </button>

          <div class="actions-right">
            <button
              v-if="!isFirstStep"
              type="button"
              class="btn-ghost"
              @click="handlePrev"
            >
              <ChevronLeft :size="14" />
              <span>上一步</span>
            </button>

            <button
              v-if="currentStep.secondaryActionLabel"
              type="button"
              class="btn-secondary"
              @click="handleSecondaryAction"
            >
              {{ currentStep.secondaryActionLabel }}
            </button>

            <button
              type="button"
              class="btn-primary"
              @click="handleNext"
            >
              <span>{{ currentStep.primaryLabel }}</span>
              <ChevronRight v-if="!isLastStep" :size="15" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.onboarding-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  pointer-events: auto;
}

.spotlight-svg {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}

.spotlight-ring {
  position: fixed;
  border-radius: 16px;
  border: 2.5px solid rgba(255, 179, 214, 0.92);
  box-shadow:
    0 0 0 4px rgba(168, 139, 250, 0.28),
    0 0 28px rgba(244, 146, 198, 0.55);
  pointer-events: none;
  transition: all 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

.onboarding-card {
  position: fixed;
  padding: 18px 20px 16px;
  border-radius: 22px;
  background: var(--modal-bg);
  border: 2px solid var(--selected-mail-border);
  box-shadow:
    0 24px 60px rgba(32, 16, 52, 0.42),
    0 0 0 4px rgba(255, 224, 240, 0.26);
  backdrop-filter: blur(18px);
  color: var(--text-primary);
  transition: left 0.28s cubic-bezier(0.22, 1, 0.36, 1), top 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

.sticker-mascot-corner {
  position: absolute;
  width: 112px;
  height: auto;
  pointer-events: none;
  filter: drop-shadow(0 8px 16px rgba(64, 34, 88, 0.24));
  animation: mascotFloat 3.2s ease-in-out infinite;
}

.sticker-mascot-corner.top-left {
  top: -86px;
  left: -14px;
}

.sticker-mascot-corner.top-right {
  top: -86px;
  right: -12px;
}

.inline-mascot-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.sticker-mascot-inline {
  width: 68px;
  height: auto;
  flex-shrink: 0;
  filter: drop-shadow(0 4px 10px rgba(64, 34, 88, 0.18));
  animation: mascotFloat 3s ease-in-out infinite;
}

.inline-speech {
  padding: 5px 11px;
  border-radius: 999px;
  background: var(--selected-mail-bg);
  border: 1px solid var(--selected-mail-border);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.sticker-arrow {
  position: fixed;
  height: auto;
  pointer-events: none;
  z-index: 2005;
  filter: drop-shadow(0 6px 14px rgba(48, 22, 68, 0.28));
  animation: arrowNudge 1.8s ease-in-out infinite;
}

.sticker-click-cursor {
  position: fixed;
  width: 48px;
  height: auto;
  pointer-events: none;
  z-index: 2010;
  filter: drop-shadow(0 4px 10px rgba(64, 30, 80, 0.32));
  animation: cursorTap 1.3s ease-in-out infinite;
}

.card-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.step-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-text);
  font-size: 11.5px;
  font-weight: 700;
}

.step-dots {
  display: flex;
  align-items: center;
  gap: 6px;
}

.step-dot {
  width: 8px;
  height: 8px;
  padding: 0;
  border-radius: 999px;
  border: none;
  background: var(--divider);
  cursor: pointer;
  transition: width 0.2s ease, background-color 0.2s ease;
}

.step-dot.passed {
  background: rgba(231, 139, 182, 0.65);
}

.step-dot.active {
  width: 20px;
  background: linear-gradient(90deg, #ee8fbd, #9a7df4);
}

.close-tour-btn {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 1px solid var(--divider);
  background: transparent;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.close-tour-btn:hover {
  background: var(--accent-soft);
  color: var(--text-primary);
}

.card-title {
  margin: 0 0 6px;
  font-size: 16.5px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.3;
}

.card-desc {
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.58;
  color: var(--text-secondary);
}

.card-tips {
  list-style: none;
  margin: 0 0 14px;
  padding: 9px 12px;
  border-radius: 13px;
  background: var(--letter-card-bg);
  border: 1px solid var(--letter-card-border);
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.card-tips li {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  line-height: 1.48;
  color: var(--text-primary);
}

.tip-bullet {
  color: var(--badge-pink);
  font-size: 11px;
  margin-top: 1px;
  flex-shrink: 0;
}

.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.actions-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.btn-skip {
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  padding: 6px 4px;
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
}

.btn-skip:hover {
  color: var(--text-primary);
  text-decoration: underline;
}

.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 6px 11px;
  border-radius: 999px;
  border: 1px solid var(--divider);
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
}

.btn-ghost:hover {
  background: var(--accent-soft);
  color: var(--accent-text);
}

.btn-secondary {
  padding: 7px 12px;
  border-radius: 999px;
  border: 1.5px solid var(--selected-mail-border);
  background: var(--selected-mail-bg);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
}

.btn-secondary:hover {
  filter: brightness(1.04);
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 7px 15px;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #ee8fbd 0%, #9b7bf2 100%);
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 700;
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
  box-shadow: 0 6px 16px rgba(176, 114, 198, 0.36);
}

.btn-primary:hover {
  filter: brightness(1.06);
}

.no-motion *,
.no-motion *::before,
.no-motion *::after {
  animation: none !important;
  transition: none !important;
}

@keyframes mascotFloat {
  0%,
  100% {
    transform: translateY(0px);
  }
  50% {
    transform: translateY(-5px);
  }
}

@keyframes arrowNudge {
  0%,
  100% {
    transform: translate(0px, 0px) scale(1);
  }
  50% {
    transform: translate(4px, -3px) scale(1.03);
  }
}

@keyframes cursorTap {
  0%,
  100% {
    transform: translate(0px, 0px) scale(1);
  }
  50% {
    transform: translate(-4px, -4px) scale(0.9);
  }
}
</style>
