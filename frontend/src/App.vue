<script setup lang="ts">
import { Toaster } from 'vue-sonner'
import { useUiStore } from '@/stores/ui'

// Initialize the UI store at the root so theme + palette are applied
// immediately on every route, including the login page.
useUiStore()
</script>

<template>
  <router-view />
  <Toaster position="bottom-right" rich-colors />
</template>
