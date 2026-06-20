<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center py-16 text-center">
    <div v-if="$slots.icon" class="text-3xl mb-3">
      <slot name="icon" />
    </div>
    <h3 class="text-lg font-medium text-text">{{ title }}</h3>
    <p v-if="description" class="text-xs text-muted mt-1">{{ description }}</p>
    <div v-if="$slots.action" class="mt-4">
      <slot name="action" />
    </div>
  </div>
</template>
