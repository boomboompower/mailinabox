<script setup lang="ts">
defineProps<{ clickable?: boolean }>()
defineEmits<{ click: [] }>()
</script>

<template>
  <tr
    :class="[
      'border-b border-border last:border-0',
      clickable && 'cursor-pointer hover:bg-hover-subtle transition-colors',
    ]"
    @click="clickable && $emit('click')"
  >
    <slot />
  </tr>
</template>
