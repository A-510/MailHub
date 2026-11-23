<script setup lang="ts">
import { computed } from 'vue'
import { motion } from 'motion-v'
import {
  Archive,
  FileEdit,
  Inbox,
  Layers,
  Mail,
  Send,
  ShieldAlert,
  Star,
  Trash2,
} from 'lucide-vue-next'
import { getOptionalAsset } from '@/utils/optionalAssets'
import ProviderBadge from '@/components/ProviderBadge.vue'
import { useMailStore } from '@/stores/mailStore'
import { useBookMotion } from '@/composables/useBookMotion'
import type { FolderCounts, FolderType } from '@/types/mail'

const store = useMailStore()
const { motionMode, springTransition } = useBookMotion()

interface FolderMeta {
  id: FolderType
  label: string
  icon: typeof Inbox
  countKey: keyof FolderCounts
}

const folders: FolderMeta[] = [
  { id: 'inbox', label: '收件箱', icon: Inbox, countKey: 'inbox' },
  { id: 'unread', label: '未读', icon: Mail, countKey: 'unread' },
  { id: 'starred', label: '星标', icon: Star, countKey: 'starred' },
  { id: 'sent', label: '发件箱', icon: Send, countKey: 'sent' },
  { id: 'drafts', label: '草稿箱', icon: FileEdit, countKey: 'drafts' },
  { id: 'archive', label: '归档', icon: Archive, countKey: 'archive' },
  { id: 'spam', label: '垃圾邮件', icon: ShieldAlert, countKey: 'spam' },
  { id: 'trash', label: '回收站', icon: Trash2, countKey: 'trash' },
]

const mascotLeftDefault = getOptionalAsset('mascot-left.png')
const mascotSrc = computed(() => store.settings.custom_mascot_left || mascotLeftDefault)

function getBadgeCount(item: FolderMeta): number {
  return store.folderCounts[item.countKey] ?? 0
}
</script>

<template>
  <aside class="folder-sidebar" aria-label="邮件文件夹">
    <nav class="bookmark-panel">
      <div
        class="folder-scope-chip"
        :title="
          store.currentAccount
            ? `${store.currentAccount.label} (${store.currentAccount.email})`
            : '当前显示全部已勾选聚合邮箱'
        "
      >
        <ProviderBadge
          v-if="store.currentAccount"
          :kind="store.currentAccount.provider"
          :color="store.currentAccount.badge_color"
          :size="16"
        />
        <Layers v-else :size="14" class="scope-layers-icon" />
        <span class="scope-label">
          {{ store.currentAccount ? store.currentAccount.label : '全部邮箱' }}
        </span>
      </div>

      <button
        v-for="item in folders"
        :key="item.id"
        type="button"
        class="folder-btn"
        :class="{ active: store.activeFolder === item.id }"
        @click="store.setFolder(item.id)"
      >
        <motion.span
          v-if="store.activeFolder === item.id && motionMode !== 'off'"
          layout-id="folder-active-pill"
          class="folder-active-bg"
          :transition="springTransition"
        />
        <span
          v-else-if="store.activeFolder === item.id"
          class="folder-active-bg"
        />
        <span class="folder-content">
          <component :is="item.icon" :size="16" class="folder-icon" />
          <span class="folder-label">{{ item.label }}</span>
        </span>
        <span
          v-if="getBadgeCount(item) > 0"
          class="folder-badge"
          :class="{ highlight: item.id === 'inbox' || item.id === 'drafts' }"
        >
          {{ getBadgeCount(item) }}
        </span>
      </button>
    </nav>

    <!-- 左下角装饰角色立绘（pointer-events: none 不遮挡任何点击） -->
    <img
      v-if="store.settings.show_mascots && mascotSrc"
      :src="mascotSrc"
      alt="书房装饰角色立绘"
      class="mascot-left-img"
      :style="{ opacity: store.settings.mascot_opacity }"
    />
  </aside>
</template>

<style scoped>
.folder-sidebar {
  position: relative;
  width: 162px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  padding-top: 22px;
  z-index: 12;
}

.bookmark-panel {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 10px;
  border-radius: 16px 8px 8px 16px;
  background: var(--bookmark-bg);
  border: 1.5px solid var(--bookmark-border);
  box-shadow: 0 14px 32px rgba(74, 48, 88, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(12px);
}

.folder-scope-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  margin-bottom: 4px;
  border-radius: 9px;
  background: var(--accent-soft);
  border: 1px solid var(--divider);
  color: var(--accent-text);
  font-size: 11.5px;
  font-weight: 700;
  min-width: 0;
}

.scope-layers-icon {
  flex-shrink: 0;
  color: var(--accent-primary);
}

.scope-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.folder-btn {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 10px;
  border: none;
  border-radius: 11px;
  background: transparent;
  color: var(--text-primary);
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: background-color 0.16s ease, color 0.16s ease;
}

.folder-btn:not(.active):hover {
  background: var(--bookmark-hover);
}

.folder-btn.active {
  color: #ffffff;
  font-weight: 600;
}

.folder-active-bg {
  position: absolute;
  inset: 0;
  border-radius: 11px;
  background: var(--folder-active-bg);
  box-shadow: var(--folder-active-shadow);
  z-index: 0;
}

.folder-content {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.folder-icon {
  opacity: 0.9;
}

.folder-badge {
  position: relative;
  z-index: 1;
  min-width: 24px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  text-align: center;
  background: var(--badge-soft-bg);
  color: var(--text-secondary);
}

.folder-btn.active .folder-badge {
  background: rgba(255, 255, 255, 0.28);
  color: #ffffff;
}

.folder-badge.highlight:not(.folder-btn.active .folder-badge) {
  background: var(--badge-pink);
  color: #ffffff;
}

.mascot-left-img {
  position: absolute;
  left: -18px;
  bottom: -14px;
  width: 210px;
  max-height: 44vh;
  object-fit: contain;
  object-position: bottom left;
  -webkit-mask-image: linear-gradient(to bottom, #000 88%, transparent 100%);
  mask-image: linear-gradient(to bottom, #000 88%, transparent 100%);
  pointer-events: none;
  user-select: none;
  z-index: 15;
  filter: drop-shadow(0 12px 22px rgba(48, 28, 66, 0.25));
  transition: opacity 0.25s ease;
}

@media (max-width: 1180px) {
  .folder-sidebar {
    width: 136px;
  }
  .mascot-left-img {
    width: 150px;
  }
}
</style>
