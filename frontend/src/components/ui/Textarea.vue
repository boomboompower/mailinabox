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
    class="w-full rounded-lg py-2 px-4 text-sm bg-subtle text-text outline-none border border-border-input focus:border-accent ring-2 ring-transparent focus:ring-accent-ring transition-colors resize-none"
  />
</template>
