<script setup lang="ts">
import { computed } from 'vue'

type BadgeVariant = 'default' | 'success' | 'warning' | 'error'

const props = withDefaults(defineProps<{ variant?: BadgeVariant }>(), { variant: 'default' })

const classes = computed(() => {
  const variants: Record<BadgeVariant, string> = {
    default: 'bg-hover text-text',
    success: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    warning: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    error: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  }
  return ['inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', variants[props.variant]]
})
</script>

<template>
  <span :class="classes"><slot /></span>
</template>
