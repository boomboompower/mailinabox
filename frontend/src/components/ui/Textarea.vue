<script setup lang="ts">
defineOptions({ inheritAttrs: false })

const model = defineModel<string>()
defineProps<{ placeholder?: string; rows?: number; disabled?: boolean }>()
</script>

<template>
  <textarea
    v-model="model"
    v-bind="$attrs"
    :placeholder="placeholder"
    :rows="rows ?? 3"
    :disabled="disabled"
    class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:bg-gray-850 dark:text-gray-300 outline-none border border-gray-200 dark:border-gray-700 focus:border-gray-400 dark:focus:border-gray-500 transition-colors resize-none"
  />
</template>
