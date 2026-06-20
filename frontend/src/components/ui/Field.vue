<script setup lang="ts">
withDefaults(defineProps<{ label?: string; for?: string }>(), { label: undefined, for: undefined })
</script>

<template>
  <div>
    <label :for="$props.for" class="block text-sm font-medium mb-1.5">
      <slot name="label">{{ label }}</slot>
    </label>
    <slot />
  </div>
</template>
