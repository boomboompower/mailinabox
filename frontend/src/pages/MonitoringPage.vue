<script setup lang="ts">
import { ref, computed } from 'vue'
import { toast } from 'vue-sonner'
import { ExternalLink, Cpu, HardDrive, Mail, Network } from 'lucide-vue-next'
import AppLayout from '@/components/layout/AppLayout.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Code from '@/components/ui/Code.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import { useApi } from '@/composables/useApi'
import { useAuthStore } from '@/stores/auth'

const api = useApi()
const auth = useAuthStore()
const opening = ref(false)

const TOOL_URLS: Record<string, { setup: string; open: string }> = {
  munin:   { setup: '/admin/munin/', open: '/admin/munin/index.html' },
  beszel:  { setup: '',             open: '/admin/beszel/' },
  netdata: { setup: '',             open: '/admin/netdata/' },
}

const hasMonitoring = computed(() => !!auth.monitoringTool)

async function openMonitoring(): Promise<void> {
  if (opening.value || !hasMonitoring.value) return
  opening.value = true
  const tool = auth.monitoringTool!
  const urls = TOOL_URLS[tool]
  try {
    if (urls.setup) {
      const res = await api.get(urls.setup)
      if (!res.ok) {
        toast.error('Failed to open monitoring. Make sure you are logged in.')
        return
      }
    }
    window.open(urls.open, '_blank')
  } catch {
    toast.error('Failed to open monitoring.')
  } finally {
    opening.value = false
  }
}

type MonitoringCategory = {
  icon: typeof Cpu
  label: string
  description: string
}

const updateNote = computed(() =>
  auth.monitoringTool === 'munin'
    ? 'Graphs are updated every 5 minutes.'
    : 'Dashboard updates in real time.'
)

const CATEGORIES: MonitoringCategory[] = [
  { icon: Cpu,       label: 'System',  description: 'CPU usage, load average, memory, swap, and process counts over time.' },
  { icon: HardDrive, label: 'Disk',    description: 'Disk I/O throughput, latency, and filesystem usage trends.' },
  { icon: Network,   label: 'Network', description: 'Bandwidth in/out per interface, connection states, and error rates.' },
  { icon: Mail,      label: 'Mail',    description: 'Postfix queue depth, delivery rates, spam/virus filter hits, and Dovecot connections.' },
]
</script>

<template>
  <AppLayout>
    <PageHeader title="Monitoring" description="View server health and performance metrics." />

    <template v-if="!hasMonitoring">
      <EmptyState
        title="No monitoring tool configured"
        description="Run the command below and select a monitoring tool, or re-run setup to enable one."
      >
        <template #icon><Cpu /></template>
        <template #action>
          <Code>sudo boxctl doctor</Code>
        </template>
      </EmptyState>
    </template>

    <template v-else>
      <p class="text-sm text-muted mb-6">
        System metrics are collected and rendered as historical graphs.
        Use them to spot trends, diagnose performance issues, or verify that services are behaving normally.
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
          <p class="text-xs text-muted">Opens in a new tab. {{ updateNote }}</p>
        </div>
        <Button size="sm" :disabled="opening" @click="openMonitoring">
          <ExternalLink class="size-3.5" />{{ opening ? 'Opening...' : 'Open Monitoring' }}
        </Button>
      </Card>
    </template>
  </AppLayout>
</template>
