<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown } from 'lucide-vue-next'

defineOptions({ inheritAttrs: false })

const model = defineModel<string>()
const props = withDefaults(defineProps<{ disabled?: boolean; size?: 'sm' | 'md' }>(), { size: 'md' })

const selectClass = computed(() =>
  props.size === 'sm'
    ? 'w-full h-8 rounded-lg py-0 px-3 pr-8 text-xs border border-border-input bg-subtle text-text outline-none focus:border-accent transition-colors appearance-none'
    : 'w-full rounded-lg py-2 px-3 pr-8 text-sm border border-border-input bg-subtle text-text outline-none focus:border-accent transition-colors appearance-none'
)
</script>

<template>
  <div class="relative">
    <select
      v-model="model"
      v-bind="$attrs"
      :disabled="disabled"
      :class="selectClass"
    >
      <slot />
    </select>
    <ChevronDown class="absolute right-2.5 top-1/2 -translate-y-1/2 size-4 text-faint pointer-events-none" />
  </div>
</template>
