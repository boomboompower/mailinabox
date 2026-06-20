<script setup lang="ts">
withDefaults(defineProps<{ modelValue: boolean; id?: string; disabled?: boolean }>(), {
  id: undefined,
  disabled: false,
})
defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <input
    :id="id"
    type="checkbox"
    :checked="modelValue"
    :disabled="disabled"
    class="size-4 rounded border-border-strong bg-surface focus:ring-2 focus:ring-accent"
    @change="$emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
  />
</template>
