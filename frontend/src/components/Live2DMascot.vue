<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { Application } from 'pixi.js'
import { Live2DModel, MotionPriority } from '@jannchie/pixi-live2d-display/cubism4'
import type { InternalModel } from '@jannchie/pixi-live2d-display/cubism4'
import { useBookMotion } from '@/composables/useBookMotion'
import { useMailStore } from '@/stores/mailStore'

const LIVE2D_MODEL_URL = encodeURI(
  '/live2d/二阶堂真红Live2D模型/运行模型/真红_一期基准.model3.json',
)
const INTERACTIVE_MOTIONS = [
  'Smile',
  'Shy',
  'Reading',
  'SmileSpeaking',
  'ShyIdle',
] as const

interface ContentBounds {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

interface CoreModelMetrics {
  getDrawableOpacity?: (index: number) => number
  getDrawableDynamicFlagIsVisible?: (index: number) => boolean
}

const store = useMailStore()
const { motionMode } = useBookMotion()

const containerRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const isReady = ref(false)
const hasError = ref(false)

let pixiApp: Application | null = null
let live2dModel: Live2DModel | null = null
let cachedContentBounds: ContentBounds | null = null
let resizeObserver: ResizeObserver | null = null
let resizeRafId: number | null = null
let disposed = false
let motionCursor = 0

/**
 * 计算模型所有可见图层的真实几何包围盒，避免因原始画布透明留白导致缩放失真或头部裁切
 */
function measureContentBounds(model: Live2DModel): ContentBounds {
  const internal = model.internalModel
  const fallbackWidth = internal?.originalWidth || model.width || 1
  const fallbackHeight = internal?.originalHeight || model.height || 1
  if (!internal) {
    return { minX: 0, maxX: fallbackWidth, minY: 0, maxY: fallbackHeight }
  }

  const ids = internal.getDrawableIDs()
  const core = internal.coreModel as CoreModelMetrics
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY

  for (let i = 0; i < ids.length; i += 1) {
    const opacity = core.getDrawableOpacity ? core.getDrawableOpacity(i) : 1
    if (opacity <= 0.01) continue
    if (
      core.getDrawableDynamicFlagIsVisible &&
      !core.getDrawableDynamicFlagIsVisible(i)
    ) {
      continue
    }

    const rect = internal.getDrawableBounds(i)
    if (!Number.isFinite(rect.width) || !Number.isFinite(rect.height)) continue
    if (rect.width <= 0 && rect.height <= 0) continue

    minX = Math.min(minX, rect.x)
    minY = Math.min(minY, rect.y)
    maxX = Math.max(maxX, rect.x + rect.width)
    maxY = Math.max(maxY, rect.y + rect.height)
  }

  if (
    !Number.isFinite(minX) ||
    !Number.isFinite(minY) ||
    !Number.isFinite(maxX) ||
    !Number.isFinite(maxY) ||
    maxX <= minX ||
    maxY <= minY
  ) {
    return { minX: 0, maxX: fallbackWidth, minY: 0, maxY: fallbackHeight }
  }

  return { minX, maxX, minY, maxY }
}

/**
 * 按真实可见包围盒与当前容器尺寸自适应缩放并贴底居中放置模型，确保头脚完整呈现
 */
function layoutModel(): void {
  const container = containerRef.value
  if (!container || !pixiApp || !live2dModel) return

  const width = container.clientWidth
  const height = container.clientHeight
  if (width <= 0 || height <= 0) return

  pixiApp.renderer.resize(width, height)

  const bounds = cachedContentBounds ?? measureContentBounds(live2dModel)
  const contentWidth = Math.max(bounds.maxX - bounds.minX, 1)
  const contentHeight = Math.max(bounds.maxY - bounds.minY, 1)

  const padX = 6
  const padTop = 8
  const padBottom = 4
  const scale = Math.min(
    Math.max(width - padX * 2, 1) / contentWidth,
    Math.max(height - padTop - padBottom, 1) / contentHeight,
  )
  const contentCenterX = (bounds.minX + bounds.maxX) * 0.5

  live2dModel.anchor.set(0, 0)
  live2dModel.scale.set(scale)
  live2dModel.position.set(
    width * 0.5 - contentCenterX * scale,
    height - padBottom - bounds.maxY * scale,
  )

  pixiApp.renderer.resetState()
  pixiApp.render()
}

/**
 * 包装 InternalModel.draw，解决 HiDPI 视口错位及 Cubism 4 裁剪遮罩导致的白底缓存污染
 */
function patchInternalDraw(internal: InternalModel, app: Application): void {
  const originalDraw = internal.draw.bind(internal)
  internal.draw = (gl: WebGLRenderingContext) => {
    // NOTE: @jannchie/pixi-live2d-display 将 CSS 逻辑宽高写入 viewport，
    // 在外部高 DPI 浏览器（devicePixelRatio > 1）下会与物理画布缓冲不匹配而偏移裁切。
    internal.viewport[0] = 0
    internal.viewport[1] = 0
    internal.viewport[2] = gl.drawingBufferWidth
    internal.viewport[3] = gl.drawingBufferHeight

    try {
      originalDraw(gl)
    } finally {
      // NOTE: Cubism 4 裁剪遮罩会执行 gl.clearColor(1, 1, 1, 0) 且不恢复，
      // PixiJS v8 GlRenderTargetAdaptor 缓存了 clearColor=[0,0,0,0] 导致后续帧
      // 误用 (1,1,1,0) 清屏变成纯白矩形；此处归零并重置 Pixi GL 状态缓存。
      gl.clearColor(0, 0, 0, 0)
      app.renderer.resetState()
    }
  }
}

/**
 * 将页面指针位置映射为画布局部坐标以驱动看板娘眼神与头部轻微跟随
 */
function handleWindowPointerMove(event: PointerEvent): void {
  if (disposed || motionMode.value === 'off' || !live2dModel || !canvasRef.value) {
    return
  }
  const rect = canvasRef.value.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return

  const localX = event.clientX - rect.left
  const localY = event.clientY - rect.top
  live2dModel.focus(localX, localY)
}

/**
 * 点击看板娘时轮换触发互动动作；快速连点由 FORCE 优先级覆盖旧动作
 */
function handleModelClick(): void {
  if (disposed || motionMode.value === 'off' || !live2dModel) return
  const group = INTERACTIVE_MOTIONS[motionCursor % INTERACTIVE_MOTIONS.length]
  motionCursor += 1
  void live2dModel.motion(group, 0, MotionPriority.FORCE)
}

function handleContextLost(event: Event): void {
  event.preventDefault()
}

function handleContextRestored(): void {
  if (disposed) return
  layoutModel()
}

/**
 * 根据全局动效档位控制渲染循环启停，并在关闭动效前确保渲染出一帧静止画面
 */
function syncTickerWithMotionMode(): void {
  if (!pixiApp || !live2dModel) return

  if (motionMode.value === 'off') {
    const container = containerRef.value
    const centerX = (container?.clientWidth || 240) * 0.5
    const lookY = (container?.clientHeight || 320) * 0.35
    live2dModel.focus(centerX, lookY, true)
    live2dModel.update(16)
    pixiApp.render()
    pixiApp.ticker.stop()
    return
  }

  if (!pixiApp.ticker.started) {
    pixiApp.ticker.start()
  }
}

watch(motionMode, () => {
  syncTickerWithMotionMode()
})

onMounted(async () => {
  const container = containerRef.value
  const canvas = canvasRef.value
  if (!container || !canvas) return

  const initWidth = Math.max(container.clientWidth, 240)
  const initHeight = Math.max(container.clientHeight, 260)

  const app = new Application()
  pixiApp = app

  canvas.addEventListener('webglcontextlost', handleContextLost)
  canvas.addEventListener('webglcontextrestored', handleContextRestored)

  try {
    await app.init({
      canvas,
      width: initWidth,
      height: initHeight,
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
      preference: 'webgl',
      // NOTE: cubism4 仅更新已废弃的 texture.source.touched，若开启 Pixi v8 GC
      // 约 60s 后会误卸载 Live2D 纹理导致角色从画布整体消失。
      gcActive: false,
    })

    if (app.renderer.gc) {
      app.renderer.gc.enabled = false
    }

    if (disposed) {
      app.destroy({ removeView: false }, { children: true })
      pixiApp = null
      return
    }

    const model = await Live2DModel.from(LIVE2D_MODEL_URL, {
      ticker: app.ticker,
      autoInteract: false,
    })

    if (disposed) {
      model.destroy({ children: true, texture: true, textureSource: true })
      app.destroy({ removeView: false }, { children: true })
      pixiApp = null
      return
    }

    for (const tex of model.textures) {
      if (tex?.source) {
        tex.source.autoGarbageCollect = false
      }
    }

    if (model.internalModel) {
      patchInternalDraw(model.internalModel, app)
    }

    live2dModel = model
    app.stage.addChild(model)
    model.update(16)
    cachedContentBounds = measureContentBounds(model)
    layoutModel()
    void model.motion('Idle', 0, MotionPriority.IDLE)

    isReady.value = true
    syncTickerWithMotionMode()

    window.addEventListener('pointermove', handleWindowPointerMove, { passive: true })
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        if (resizeRafId !== null) {
          window.cancelAnimationFrame(resizeRafId)
        }
        resizeRafId = window.requestAnimationFrame(() => {
          resizeRafId = null
          layoutModel()
        })
      })
      resizeObserver.observe(container)
    }
  } catch (err) {
    hasError.value = true
    console.warn('[Live2DMascot] Failed to initialize Live2D model:', err)
    if (live2dModel) {
      live2dModel.destroy({ children: true, texture: true, textureSource: true })
      live2dModel = null
    }
    if (pixiApp) {
      pixiApp.destroy({ removeView: false }, { children: true })
      pixiApp = null
    }
  }
})

onUnmounted(() => {
  disposed = true
  window.removeEventListener('pointermove', handleWindowPointerMove)
  if (canvasRef.value) {
    canvasRef.value.removeEventListener('webglcontextlost', handleContextLost)
    canvasRef.value.removeEventListener('webglcontextrestored', handleContextRestored)
  }
  if (resizeRafId !== null) {
    window.cancelAnimationFrame(resizeRafId)
    resizeRafId = null
  }
  resizeObserver?.disconnect()
  resizeObserver = null
  cachedContentBounds = null

  if (live2dModel) {
    live2dModel.destroy({ children: true, texture: true, textureSource: true })
    live2dModel = null
  }
  if (pixiApp) {
    pixiApp.destroy({ removeView: false }, { children: true })
    pixiApp = null
  }
})
</script>

<template>
  <div
    ref="containerRef"
    class="live2d-mascot-slot"
    :class="{ ready: isReady, clickable: isReady && motionMode !== 'off' }"
    :style="{ opacity: isReady ? store.settings.mascot_opacity : 0 }"
    :title="isReady ? '二阶堂真红（点击互动）' : undefined"
    @click="handleModelClick"
  >
    <canvas v-if="!hasError" ref="canvasRef" class="live2d-canvas" />
  </div>
</template>

<style scoped>
.live2d-mascot-slot {
  position: absolute;
  right: -16px;
  bottom: -10px;
  width: 256px;
  height: clamp(240px, 42vh, 340px);
  z-index: 14;
  pointer-events: auto;
  user-select: none;
  opacity: 0;
  filter: drop-shadow(0 12px 22px rgba(48, 28, 66, 0.25));
  transition: opacity 0.28s ease;
}

.live2d-mascot-slot.clickable {
  cursor: pointer;
}

.live2d-canvas {
  display: block;
  width: 100%;
  height: 100%;
}

@media (max-width: 1180px) {
  .live2d-mascot-slot {
    right: -12px;
    bottom: -8px;
    width: 204px;
    height: clamp(210px, 38vh, 274px);
  }
}
</style>
