<script setup lang="ts">
defineProps<{ class?: string }>()
</script>

<template>
  <th
    scope="col"
    class="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider"
    :class="$props.class"
  >
    <slot />
  </th>
</template>
