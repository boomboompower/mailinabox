<script setup lang="ts">
defineProps<{ class?: string }>()
</script>

<template>
  <div
    class="rounded-2xl border border-border bg-surface"
    :class="$props.class"
  >
    <slot />
  </div>
</template>
