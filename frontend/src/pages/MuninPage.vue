<script setup lang="ts">
import { ref } from 'vue'
import { toast } from 'vue-sonner'
import { ExternalLink, Cpu, HardDrive, Mail, Network } from 'lucide-vue-next'
import AppLayout from '@/components/layout/AppLayout.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
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

type MuninCategory = {
  icon: typeof Cpu
  label: string
  description: string
}

const CATEGORIES: MuninCategory[] = [
  { icon: Cpu,       label: 'System',  description: 'CPU usage, load average, memory, swap, and process counts over time.' },
  { icon: HardDrive, label: 'Disk',    description: 'Disk I/O throughput, latency, and filesystem usage trends.' },
  { icon: Network,   label: 'Network', description: 'Bandwidth in/out per interface, connection states, and error rates.' },
  { icon: Mail,      label: 'Mail',    description: 'Postfix queue depth, delivery rates, spam/virus filter hits, and Dovecot connections.' },
]
</script>

<template>
  <AppLayout>
    <PageHeader title="Munin Monitoring">
      <template #actions>
        <Button size="sm" :disabled="opening" @click="openMunin">
          <ExternalLink class="size-3.5" />{{ opening ? 'Opening...' : 'Open Munin' }}
        </Button>
      </template>
    </PageHeader>

    <p class="text-sm text-muted mb-6">
      Munin collects system and service metrics every 5 minutes and renders them as historical graphs.
      Use it to spot trends, diagnose performance issues, or verify that services are behaving normally.
    </p>

    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
      <Card v-for="cat in CATEGORIES" :key="cat.label" class="flex items-start gap-3 p-4">
        <div class="mt-0.5 rounded-lg bg-accent/10 p-2 shrink-0">
          <component :is="cat.icon" class="size-4 text-accent" />
        </div>
        <div>
          <p class="text-sm font-medium mb-0.5">{{ cat.label }}</p>
          <p class="text-xs text-muted">{{ cat.description }}</p>
        </div>
      </Card>
    </div>

    <Card class="p-4 flex items-center justify-between gap-4">
      <div>
        <p class="text-sm font-medium mb-0.5">Open monitoring dashboard</p>
        <p class="text-xs text-muted">Opens in a new tab. Graphs are updated every 5 minutes.</p>
      </div>
      <Button size="sm" :disabled="opening" @click="openMunin">
        <ExternalLink class="size-3.5" />{{ opening ? 'Opening...' : 'Open Munin' }}
      </Button>
    </Card>
  </AppLayout>
</template>
