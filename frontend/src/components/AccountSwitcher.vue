<script setup lang="ts">
import { computed } from 'vue'
import { Layers, Mail, Plus } from 'lucide-vue-next'
import Live2DMascot from '@/components/Live2DMascot.vue'
import ProviderBadge from '@/components/ProviderBadge.vue'
import { useMailStore } from '@/stores/mailStore'

const store = useMailStore()

const totalUnifiedUnread = computed(() =>
  store.accounts
    .filter((a) => a.include_in_unified)
    .reduce((sum, a) => sum + a.unread_count, 0),
)
</script>

<template>
  <aside class="accounts-sidebar" aria-label="我的邮箱切换栏">
    <div class="accounts-glass-card" data-tour="account-panel">
      <div class="accounts-header">
        <div class="accounts-title-group">
          <Mail :size="15" />
          <span>我的邮箱</span>
        </div>
        <button
          type="button"
          class="add-account-btn"
          data-tour="add-account-btn"
          title="添加或管理邮箱渠道"
          aria-label="新增邮箱渠道"
          @click="store.openSettings('accounts')"
        >
          <Plus :size="15" />
        </button>
      </div>

      <!-- 全部聚合视图入口 -->
      <button
        type="button"
        class="unified-row"
        :class="{ active: store.selectedAccountId === null }"
        @click="store.switchAccount(null)"
      >
        <div class="unified-left">
          <Layers :size="14" />
          <span>全部聚合邮箱</span>
        </div>
        <span class="unread-pill">{{ totalUnifiedUnread }}</span>
      </button>

      <!-- 各绑定邮箱列表 -->
      <div class="accounts-list soft-scroll">
        <div
          v-for="acc in store.accounts"
          :key="acc.id"
          class="account-row"
          :class="{ active: store.selectedAccountId === acc.id }"
          role="button"
          tabindex="0"
          @click="store.switchAccount(acc.id)"
          @keydown.enter.prevent="store.switchAccount(acc.id)"
        >
          <input
            type="checkbox"
            class="agg-check"
            :checked="acc.include_in_unified"
            title="是否在「全部聚合」中显示该邮箱"
            aria-label="参与聚合显示"
            @click.stop
            @change="store.toggleIncludeInUnified(acc)"
          />

          <ProviderBadge :kind="acc.provider" :color="acc.badge_color" :size="24" />

          <div class="account-meta">
            <div class="account-label-line">
              <span class="account-label">{{ acc.label }}</span>
              <span v-if="acc.is_demo" class="demo-tag">演示</span>
            </div>
            <div class="account-email">{{ acc.email }}</div>
          </div>

          <span v-if="acc.unread_count > 0" class="unread-pill pink">
            {{ acc.unread_count }}
          </span>
        </div>

        <button
          type="button"
          class="quick-bind-btn"
          data-tour="quick-bind-btn"
          @click="store.openSettings('accounts')"
        >
          <Plus :size="13" />
          <span>添加邮箱渠道</span>
        </button>
      </div>
    </div>

    <!-- 右下角二阶堂真红 Live2D 看板娘 -->
    <Live2DMascot v-if="store.settings.show_mascots" />
  </aside>
</template>

<style scoped>
.accounts-sidebar {
  position: relative;
  width: 226px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding-top: 12px;
  z-index: 12;
  /* 透明空白区不拦截书侧探头立绘的鼠标悬停事件 */
  pointer-events: none;
}

.accounts-glass-card {
  position: relative;
  z-index: 20;
  pointer-events: auto;
  display: flex;
  flex-direction: column;
  max-height: 60vh;
  padding: 12px;
  border-radius: 18px;
  background: var(--glass-panel-bg);
  border: 1.5px solid var(--glass-panel-border);
  box-shadow: var(--glass-panel-shadow);
  backdrop-filter: blur(16px);
}

.accounts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 9px;
  border-bottom: 1px solid var(--divider);
}

.accounts-title-group {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text-primary);
}

.add-account-btn {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  border: 1px solid var(--divider);
  background: var(--surface-elevated);
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.add-account-btn:hover {
  background: var(--accent-soft);
  color: var(--accent-text);
}

.unified-row {
  margin-top: 9px;
  padding: 8px 10px;
  border-radius: 11px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.16s ease, border-color 0.16s ease;
}

.unified-row:hover {
  background: var(--accent-soft);
}

.unified-row.active {
  background: var(--selected-mail-bg);
  border-color: var(--selected-mail-border);
}

.unified-left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.accounts-list {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding-right: 2px;
}

.account-row {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 8px;
  border-radius: 11px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: background-color 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
}

.account-row:hover {
  background: var(--mail-card-hover);
  transform: translateX(-2px);
}

.account-row.active {
  background: var(--selected-mail-bg);
  border-color: var(--selected-mail-border);
}

.agg-check {
  width: 13px;
  height: 13px;
  accent-color: var(--accent-primary);
  cursor: pointer;
  flex-shrink: 0;
}

.account-meta {
  flex: 1;
  min-width: 0;
}

.account-label-line {
  display: flex;
  align-items: center;
  gap: 4px;
}

.account-label {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.demo-tag {
  font-size: 9.5px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-text);
  flex-shrink: 0;
}

.account-email {
  font-size: 10.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.unread-pill {
  min-width: 22px;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  text-align: center;
  background: var(--accent-soft);
  color: var(--accent-text);
  flex-shrink: 0;
}

.unread-pill.pink {
  background: var(--badge-pink);
  color: #ffffff;
}

.quick-bind-btn {
  margin-top: 4px;
  padding: 7px 10px;
  border-radius: 10px;
  border: 1px dashed var(--divider);
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  cursor: pointer;
}

.quick-bind-btn:hover {
  border-color: var(--accent-primary);
  color: var(--accent-text);
  background: var(--accent-soft);
}

@media (max-width: 1180px) {
  .accounts-sidebar {
    width: 196px;
  }
}
</style>
