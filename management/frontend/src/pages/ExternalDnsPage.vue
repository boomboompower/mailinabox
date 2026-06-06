<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { WifiOff } from 'lucide-vue-next'
import AppLayout from '@/components/layout/AppLayout.vue'
import Button from '@/components/ui/Button.vue'
import Select from '@/components/ui/Select.vue'
import Table from '@/components/ui/Table.vue'
import TableRow from '@/components/ui/TableRow.vue'
import TableHead from '@/components/ui/TableHead.vue'
import Th from '@/components/ui/Th.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useApi } from '@/composables/useApi'
import type { ExternalDnsEntry } from '@/types'

const api = useApi()

// /dns/dump returns [[zoneName, records[]], ...]
type ZoneData = [string, ExternalDnsEntry[]]

const zones = ref<ZoneData[]>([])
const dnsZones = ref<string[]>([])
const selectedZone = ref('')
const loading = ref(true)
const loadError = ref(false)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = false
  try {
    const [dumpRes, zonesRes] = await Promise.all([
      api.get('/admin/dns/dump'),
      api.get('/admin/dns/zones'),
    ])
    zones.value = await dumpRes.json()
    dnsZones.value = await zonesRes.json()
    if (dnsZones.value.length) selectedZone.value = dnsZones.value[0]
  } catch {
    loadError.value = true
    toast.error('Failed to load DNS records.')
  } finally {
    loading.value = false
  }
}

async function downloadZonefile(): Promise<void> {
  if (!selectedZone.value) return
  const res = await api.get(`/admin/dns/zonefile/${encodeURIComponent(selectedZone.value)}`)
  const text = await res.text()
  const blob = new Blob([text], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${selectedZone.value}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

function explanationBadgeClass(explanation: string): string {
  if (explanation.startsWith('Required.')) return 'text-red-600 dark:text-red-400 font-medium'
  if (explanation.startsWith('Recommended.')) return 'text-amber-600 dark:text-amber-400 font-medium'
  return 'text-gray-400'
}

onMounted(load)
</script>

<template>
  <AppLayout>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-semibold">External DNS</h1>
      <div class="flex items-center gap-2">
        <Select v-model="selectedZone" class="w-auto">
          <option v-for="z in dnsZones" :key="z" :value="z">{{ z }}</option>
        </Select>
        <Button variant="secondary" @click="downloadZonefile">Download zone file</Button>
      </div>
    </div>

    <p class="text-sm text-gray-500 mb-6">
      If this box's DNS is managed by an external provider, set the following records.
      Records marked <span class="text-red-600 dark:text-red-400 font-medium">Required</span> must be set.
      <span class="text-amber-600 dark:text-amber-400 font-medium">Recommended</span> records improve deliverability.
    </p>

    <template v-if="loading">
      <div class="space-y-6">
        <div v-for="i in 2" :key="i">
          <Skeleton class="h-5 w-40 mb-3" />
          <div class="space-y-2">
            <Skeleton v-for="j in 4" :key="j" class="h-12 w-full" />
          </div>
        </div>
      </div>
    </template>

    <EmptyState
      v-else-if="loadError"
      title="Could not load DNS records"
      description="The server did not respond. Check your connection and try again."
    >
      <template #icon><WifiOff /></template>
      <template #action>
        <Button variant="secondary" @click="load">Try again</Button>
      </template>
    </EmptyState>

    <template v-else>
      <div v-for="[zoneName, zoneRecords] in zones" :key="zoneName" class="mb-8">
        <h2 class="text-base font-semibold mb-3">{{ zoneName }}</h2>
        <Table>
          <TableHead>
            <Th>Name</Th>
            <Th>Type</Th>
            <Th>Value</Th>
            <Th class="hidden lg:table-cell">Note</Th>
          </TableHead>
          <tbody>
            <TableRow
              v-for="record in zoneRecords"
              :key="`${record.qname}/${record.rtype}`"
            >
              <td class="px-4 py-3 font-mono text-sm">{{ record.qname }}</td>
              <td class="px-4 py-3 text-sm font-medium">{{ record.rtype }}</td>
              <td class="px-4 py-3 font-mono text-xs max-w-xs break-all">{{ record.value }}</td>
              <td class="px-4 py-3 text-xs hidden lg:table-cell" :class="explanationBadgeClass(record.explanation)">
                {{ record.explanation }}
              </td>
            </TableRow>
          </tbody>
        </Table>
      </div>
    </template>
  </AppLayout>
</template>

