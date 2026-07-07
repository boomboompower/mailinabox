<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
import AppMobileDrawer from './AppMobileDrawer.vue'
import { useUiStore } from '@/stores/ui'
import { useConfigStore } from '@/stores/config'
import { Menu } from 'lucide-vue-next'

const ui = useUiStore()
const config = useConfigStore()
</script>

<template>
  <div class="min-h-screen bg-bg text-text">
    <AppSidebar class="hidden md:flex" />
    <AppMobileDrawer />

    <div
      :class="[
        'transition-[margin] duration-300 md:min-h-screen',
        ui.sidebarCollapsed ? 'md:ml-14' : 'md:ml-[260px]',
      ]"
    >
      <!-- Mobile top bar -->
      <div class="flex items-center gap-3 px-4 py-3 border-b border-border md:hidden">
        <button
          class="rounded-xl hover:bg-hover size-9 flex items-center justify-center transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          @click="ui.openMobileSidebar()"
        >
          <Menu class="size-5" />
        </button>
        <span class="text-sm font-medium">{{ config.hostname || 'Mail-in-a-Box' }}</span>
      </div>

      <div class="p-6">
        <div class="mx-auto w-full max-w-5xl page">
          <slot />
        </div>
      </div>
    </div>
  </div>
</template>
