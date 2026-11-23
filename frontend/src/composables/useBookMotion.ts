import { computed } from 'vue'
import { useMailStore } from '@/stores/mailStore'

/**
 * 统一封装动效参数，严格尊重用户设置档位与系统 prefers-reduced-motion。
 */
export function useBookMotion() {
  const store = useMailStore()

  const systemReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  const motionMode = computed<'full' | 'gentle' | 'off'>(() => {
    if (systemReduced || store.settings.motion_level === 'off') return 'off'
    return store.settings.motion_level
  })

  const springTransition = computed(() => {
    if (motionMode.value === 'off') return { duration: 0 }
    if (motionMode.value === 'gentle') {
      return { duration: 0.2, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] }
    }
    return {
      type: 'spring' as const,
      stiffness: 260,
      damping: 26,
      mass: 0.9,
    }
  })

  const pageFlipDurationMs = computed(() => {
    if (motionMode.value === 'off') return 0
    if (motionMode.value === 'gentle') return 220
    return 460
  })

  return {
    motionMode,
    springTransition,
    pageFlipDurationMs,
  }
}
