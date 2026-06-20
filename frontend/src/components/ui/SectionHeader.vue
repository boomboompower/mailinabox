<script setup lang="ts">
defineProps<{ title: string }>()
</script>

<template>
  <div class="flex items-center justify-between mb-3">
    <h2 class="text-base font-semibold">{{ title }}</h2>
    <slot name="actions" />
  </div>
</template>
