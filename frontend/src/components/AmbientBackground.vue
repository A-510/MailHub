<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { getOptionalAsset } from '@/utils/optionalAssets'
import { useMailStore } from '@/stores/mailStore'
import { useTheme } from '@/composables/useTheme'

const bgLight = getOptionalAsset('bg-light.png')
const bgDark = getOptionalAsset('bg-dark.png')

const store = useMailStore()
const { resolvedTheme } = useTheme()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let animFrameId: number | null = null

interface Particle {
  x: number
  y: number
  size: number
  speedY: number
  speedX: number
  angle: number
  spin: number
  alpha: number
}

function stopParticles(): void {
  if (animFrameId !== null) {
    window.cancelAnimationFrame(animFrameId)
    animFrameId = null
  }
  const canvas = canvasRef.value
  if (canvas) {
    const ctx = canvas.getContext('2d')
    ctx?.clearRect(0, 0, canvas.width, canvas.height)
  }
}

function startParticles(): void {
  stopParticles()
  const canvas = canvasRef.value
  if (!canvas) return
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!store.settings.show_particles || store.settings.motion_level === 'off' || reduced) {
    return
  }

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const resize = () => {
    canvas.width = window.innerWidth
    canvas.height = window.innerHeight
  }
  resize()

  const count = 18
  const particles: Particle[] = Array.from({ length: count }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    size: 4 + Math.random() * 6,
    speedY: 0.32 + Math.random() * 0.55,
    speedX: -0.25 + Math.random() * 0.5,
    angle: Math.random() * Math.PI * 2,
    spin: (Math.random() - 0.5) * 0.025,
    alpha: 0.32 + Math.random() * 0.45,
  }))

  const render = () => {
    if (!store.settings.show_particles || store.settings.motion_level === 'off') {
      stopParticles()
      return
    }
    if (canvas.width !== window.innerWidth || canvas.height !== window.innerHeight) {
      resize()
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    const isDark = resolvedTheme.value === 'dark'

    for (const p of particles) {
      p.y += isDark ? -p.speedY * 0.45 : p.speedY
      p.x += p.speedX + Math.sin(p.y * 0.012) * 0.28
      p.angle += p.spin

      if (!isDark && p.y > canvas.height + 16) {
        p.y = -16
        p.x = Math.random() * canvas.width
      } else if (isDark && p.y < -16) {
        p.y = canvas.height + 16
        p.x = Math.random() * canvas.width
      }
      if (p.x > canvas.width + 20) p.x = -12
      if (p.x < -20) p.x = canvas.width + 12

      ctx.save()
      ctx.translate(p.x, p.y)
      ctx.rotate(p.angle)
      ctx.globalAlpha = p.alpha

      if (isDark) {
        // 暗黑模式：星尘微光
        const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, p.size * 1.4)
        glow.addColorStop(0, 'rgba(235, 210, 255, 0.95)')
        glow.addColorStop(0.5, 'rgba(180, 148, 255, 0.35)')
        glow.addColorStop(1, 'rgba(180, 148, 255, 0)')
        ctx.fillStyle = glow
        ctx.beginPath()
        ctx.arc(0, 0, p.size * 1.4, 0, Math.PI * 2)
        ctx.fill()
      } else {
        // 明亮模式：樱花花瓣
        ctx.fillStyle = 'rgba(255, 198, 224, 0.88)'
        ctx.beginPath()
        ctx.ellipse(0, 0, p.size * 0.9, p.size * 0.52, 0, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.restore()
    }

    animFrameId = window.requestAnimationFrame(render)
  }

  animFrameId = window.requestAnimationFrame(render)
}

watch(
  () => [store.settings.show_particles, store.settings.motion_level, resolvedTheme.value],
  () => {
    startParticles()
  },
)

onMounted(() => {
  startParticles()
})

onUnmounted(() => {
  stopParticles()
})
</script>

<template>
  <div class="ambient-bg" aria-hidden="true">
    <img
      v-if="bgLight"
      class="bg-layer"
      :class="{ visible: resolvedTheme === 'light' }"
      :src="bgLight"
      alt=""
    />
    <img
      v-if="bgDark"
      class="bg-layer"
      :class="{ visible: resolvedTheme === 'dark' }"
      :src="bgDark"
      alt=""
    />
    <div class="bg-overlay" />
    <canvas ref="canvasRef" class="particle-canvas" />
  </div>
</template>

<style scoped>
.ambient-bg {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
  /* 无外部壁纸素材时使用樱花白昼柔和书桌渐变兜底 */
  background:
    radial-gradient(circle at 18% 18%, rgba(255, 224, 238, 0.92) 0%, rgba(255, 224, 238, 0) 48%),
    radial-gradient(circle at 82% 24%, rgba(226, 214, 255, 0.88) 0%, rgba(226, 214, 255, 0) 52%),
    linear-gradient(135deg, #fdf3f8 0%, #f5ecf8 52%, #ebe4f6 100%);
  transition: background 0.4s ease;
}

:global([data-theme='dark']) .ambient-bg {
  background:
    radial-gradient(circle at 20% 20%, rgba(114, 72, 152, 0.36) 0%, rgba(114, 72, 152, 0) 50%),
    radial-gradient(circle at 80% 78%, rgba(168, 98, 148, 0.24) 0%, rgba(168, 98, 148, 0) 50%),
    linear-gradient(135deg, #161124 0%, #201834 55%, #120e1e 100%);
}

.bg-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
  transition: opacity 0.4s ease;
}

.bg-layer.visible {
  opacity: 1;
}

.bg-overlay {
  position: absolute;
  inset: 0;
  background: var(--bg-desk-overlay);
}

.particle-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
</style>
