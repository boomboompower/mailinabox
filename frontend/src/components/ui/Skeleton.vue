<script setup lang="ts">
defineProps<{ class?: string }>()
</script>

<template>
  <div class="animate-pulse rounded bg-skeleton" :class="$props.class" />
</template>
