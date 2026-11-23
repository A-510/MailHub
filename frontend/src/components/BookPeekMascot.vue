<script setup lang="ts">
import { computed } from 'vue'
import { getOptionalAsset } from '@/utils/optionalAssets'
import { useBookMotion } from '@/composables/useBookMotion'
import { useMailStore } from '@/stores/mailStore'

const store = useMailStore()
const { motionMode } = useBookMotion()

const mascotRightDefault = getOptionalAsset('mascot-right.png')
const mascotSrc = computed(() => store.settings.custom_mascot_right || mascotRightDefault)
</script>

<template>
  <div
    v-if="mascotSrc"
    class="book-peek-mascot"
    :class="[
      `motion-${motionMode}`,
    ]"
    :style="{ opacity: store.settings.mascot_opacity }"
    aria-hidden="true"
  >
    <div class="peek-body-pivot">
      <div class="peek-breath-layer">
        <img
          :src="mascotSrc"
          alt="书侧探头装饰角色立绘"
          class="peek-mascot-img"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 锚定在书本右侧中间角落，z-index 低于 .book-shell(z-index: 3)，实现从书背面爬出来的真实遮挡层次 */
.book-peek-mascot {
  position: absolute;
  top: 34%;
  right: -94px;
  width: 154px;
  height: 204px;
  z-index: 1;
  pointer-events: auto;
  user-select: none;
  transition: opacity 0.25s ease;
}

.peek-body-pivot {
  width: 100%;
  height: 100%;
  transform-origin: 18% 82%;
  transform: translate(-20px, -10px) rotate(48deg);
  transition: transform 0.34s cubic-bezier(0.22, 1, 0.36, 1);
}

.book-peek-mascot:not(.motion-off):hover .peek-body-pivot {
  transform: translate(-6px, -16px) rotate(42deg) scale(1.03);
}

.peek-breath-layer {
  width: 100%;
  height: 100%;
  transform-origin: 20% 85%;
}

.book-peek-mascot.motion-full .peek-breath-layer {
  animation: peek-sway 5.6s ease-in-out infinite;
}

.peek-mascot-img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
  object-position: top center;
  /* 仅保留上半身探出姿态，底部柔和淡出防止在书背边缘穿帮 */
  -webkit-mask-image: linear-gradient(to bottom, #000 0%, #000 72%, transparent 100%);
  mask-image: linear-gradient(to bottom, #000 0%, #000 72%, transparent 100%);
  filter: drop-shadow(-3px 6px 14px rgba(48, 28, 66, 0.28));
  pointer-events: none;
}

@keyframes peek-sway {
  0%,
  100% {
    transform: rotate(0deg) translateY(0px);
  }
  50% {
    transform: rotate(-2.4deg) translateY(-3px);
  }
}

@media (max-width: 1180px) {
  .book-peek-mascot {
    top: 35%;
    right: -68px;
    width: 120px;
    height: 162px;
  }

  .peek-body-pivot {
    transform: translate(-16px, -8px) rotate(46deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .book-peek-mascot.motion-full .peek-breath-layer {
    animation: none;
  }

  .peek-body-pivot {
    transition: none;
  }
}
</style>
