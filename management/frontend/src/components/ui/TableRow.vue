<script setup lang="ts">
defineProps<{ clickable?: boolean }>()
defineEmits<{ click: [] }>()
</script>

<template>
  <tr
    :class="[
      'border-b border-gray-100 dark:border-gray-800 last:border-0',
      clickable && 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors',
    ]"
    @click="clickable && $emit('click')"
  >
    <slot />
  </tr>
</template>
