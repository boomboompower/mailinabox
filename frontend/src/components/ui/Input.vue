<script setup lang="ts">
import { computed, ref } from 'vue';
import { Eye, EyeOff } from 'lucide-vue-next'

defineOptions({ inheritAttrs: false })

const model = defineModel<string>()

const props = defineProps<{
  type?: string
  placeholder?: string
  disabled?: boolean
  autocomplete?: string
  inputmode?: 'text' | 'numeric' | 'decimal' | 'email' | 'tel' | 'search' | 'url' | 'none'
  maxlength?: number
  required?: boolean
}>()

const showPassword = ref(false)

const computedType = computed(() => {
  if (props.type !== 'password') return props.type ?? 'text'
  return showPassword.value ? 'text' : 'password'
})

function togglePassword() {
  showPassword.value = !showPassword.value
}

const inputClass = computed(() => {
  return [
    'w-full rounded-lg py-2 px-4 text-sm bg-subtle text-text outline-none border border-border-input focus:border-accent ring-2 ring-transparent focus:ring-accent-ring transition-colors',
    props.type === 'password' ? 'pr-10' : ''
  ]
})
</script>

<template>
  <div class="relative w-full">
    <input
      v-model="model"
      v-bind="$attrs"
      :type="computedType"
      :placeholder="placeholder"
      :disabled="disabled"
      :autocomplete="autocomplete"
      :inputmode="inputmode"
      :maxlength="maxlength"
      :required="required"
      :class="inputClass"
    />

    <button
      v-if="type === 'password'"
      type="button"
      @click="togglePassword"
      class="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-text transition-colors"
      tabindex="-1"
    >
      <Eye v-if="!showPassword" :size="18" />
      <EyeOff v-else :size="18" />
    </button>
  </div>
</template>
