<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { BarChart2 } from 'lucide-vue-next'
import AppLayout from '@/components/layout/AppLayout.vue'
import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useApi } from '@/composables/useApi'

const api = useApi()
const opening = ref(false)

async function openMunin(): Promise<void> {
  if (opening.value) return
  opening.value = true
  try {
    // Sets a short-lived session cookie for munin page access
    const res = await api.get('/admin/munin/')
    if (res.ok) {
      window.open('/admin/munin/index.html', '_blank')
    } else {
      toast.error('Failed to open Munin. Make sure you are logged in.')
    }
  } catch {
    toast.error('Failed to open Munin.')
  } finally {
    opening.value = false
  }
}

onMounted(openMunin)
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold mb-6">Munin Monitoring</h1>

    <EmptyState
      title="Opening Munin..."
      description="Munin opens in a new tab. Allow pop-ups for this site if it does not open automatically."
    >
      <template #icon><BarChart2 /></template>
      <template #action>
        <Button :disabled="opening" @click="openMunin">
          {{ opening ? 'Opening...' : 'Open Munin' }}
        </Button>
      </template>
    </EmptyState>
  </AppLayout>
</template>
