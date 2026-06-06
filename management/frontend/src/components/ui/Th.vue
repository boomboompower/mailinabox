<script setup lang="ts">
defineProps<{ class?: string }>()
</script>

<template>
  <th
    class="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider"
    :class="$props.class"
  >
    <slot />
  </th>
</template>
