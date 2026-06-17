<script setup lang="ts">
defineProps<{ class?: string }>()
</script>

<template>
  <div
    class="rounded-2xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-850"
    :class="$props.class"
  >
    <slot />
  </div>
</template>
