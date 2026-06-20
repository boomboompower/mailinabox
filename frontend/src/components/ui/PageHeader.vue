<script setup lang="ts">
defineProps<{ title: string }>()
</script>

<template>
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-semibold">{{ title }}</h1>
    <slot name="actions" />
  </div>
</template>
