import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useMailStore } from '@/stores/mailStore'
import type { ThemeMode } from '@/types/mail'

/**
 * 主题与阅读偏好管理组合式函数：
 * 同步明亮/暗黑/跟随系统模式、字号、密度及动效档位到 HTML 根元素属性。
 */
export function useTheme() {
  const store = useMailStore()
  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')

  const resolvedTheme = computed<'light' | 'dark'>(() => {
    if (store.settings.theme_mode === 'system') {
      return mediaQuery.matches ? 'dark' : 'light'
    }
    return store.settings.theme_mode
  })

  function applyDomAttributes(): void {
    const root = document.documentElement
    root.setAttribute('data-theme', resolvedTheme.value)
    root.setAttribute('data-font-size', store.settings.font_size)
    root.setAttribute('data-density', store.settings.list_density)
    root.setAttribute('data-motion', store.settings.motion_level)
  }

  async function setThemeWithTransition(mode: ThemeMode, event?: MouseEvent): Promise<void> {
    const doc = document as Document & {
      startViewTransition?: (cb: () => void) => { ready: Promise<void>; finished: Promise<void> }
    }

    const canHaloTransition =
      typeof doc.startViewTransition === 'function' &&
      store.settings.motion_level !== 'off' &&
      !window.matchMedia('(prefers-reduced-motion: reduce)').matches

    if (!canHaloTransition || !event) {
      await store.updateSettings({ theme_mode: mode })
      applyDomAttributes()
      return
    }

    const x = event.clientX
    const y = event.clientY
    const endRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    )

    const transition = doc.startViewTransition(() => {
      store.settings.theme_mode = mode
      applyDomAttributes()
    })

    // 异步持久化到后端，不阻塞视觉切换
    void store.updateSettings({ theme_mode: mode })

    try {
      await transition.ready
      document.documentElement.animate(
        {
          clipPath: [
            `circle(0px at ${x}px ${y}px)`,
            `circle(${endRadius}px at ${x}px ${y}px)`,
          ],
        },
        {
          duration: 380,
          easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
          pseudoElement: '::view-transition-new(root)',
        },
      )
    } catch {
      // 浏览器打断 View Transition 时静默恢复最终态（TR-06）
    }
  }

  function handleSystemThemeChange(): void {
    if (store.settings.theme_mode === 'system') {
      applyDomAttributes()
    }
  }

  watch(
    () => [
      store.settings.theme_mode,
      store.settings.font_size,
      store.settings.list_density,
      store.settings.motion_level,
    ],
    () => {
      applyDomAttributes()
    },
    { immediate: true },
  )

  onMounted(() => {
    mediaQuery.addEventListener('change', handleSystemThemeChange)
    applyDomAttributes()
  })

  onUnmounted(() => {
    mediaQuery.removeEventListener('change', handleSystemThemeChange)
  })

  return {
    resolvedTheme,
    setThemeWithTransition,
  }
}
