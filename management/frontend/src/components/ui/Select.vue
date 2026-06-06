<script setup lang="ts">
const model = defineModel<string>()
defineProps<{ disabled?: boolean }>()
</script>

<template>
  <select
    v-model="model"
    :disabled="disabled"
    class="w-full rounded-lg py-2 px-3 text-sm border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-850 dark:text-gray-300 outline-none focus:border-gray-400 dark:focus:border-gray-500 transition-colors"
  >
    <slot />
  </select>
</template>
