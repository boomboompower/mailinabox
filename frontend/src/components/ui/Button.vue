<script setup lang="ts">
import { computed } from 'vue'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'destructive'
type ButtonSize = 'sm' | 'md' | 'lg'

const props = withDefaults(
  defineProps<{
    variant?: ButtonVariant
    size?: ButtonSize
    disabled?: boolean
    type?: 'button' | 'submit' | 'reset'
  }>(),
  { variant: 'primary', size: 'md', type: 'button' },
)

const classes = computed(() => {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50'

  const variants: Record<ButtonVariant, string> = {
    primary:
      'bg-accent text-accent-fg hover:bg-accent-hover',
    secondary:
      'bg-surface text-text hover:bg-hover',
    ghost: 'hover:bg-hover text-text',
    destructive: 'bg-red-600 text-white hover:bg-red-700',
  }

  const sizes: Record<ButtonSize, string> = {
    sm: 'h-8 px-3 text-xs',
    md: 'h-9 px-4 text-sm',
    lg: 'h-10 px-5 text-sm',
  }

  return [base, variants[props.variant], sizes[props.size]]
})
</script>

<template>
  <button :class="classes" :type="type" :disabled="disabled">
    <slot />
  </button>
</template>
