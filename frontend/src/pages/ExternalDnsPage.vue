<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { WifiOff, Download } from 'lucide-vue-next'
import AppLayout from '@/components/layout/AppLayout.vue'
import Button from '@/components/ui/Button.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import Badge from '@/components/ui/Badge.vue'
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


onMounted(load)
</script>

<template>
  <AppLayout>
    <PageHeader title="External DNS">
      <template #actions>
        <div class="flex items-center gap-2">
          <Select v-model="selectedZone" size="sm" class="w-auto" :disabled="loadError" aria-label="Select zone">
            <option v-if="loadError" value="" disabled>No zones</option>
            <option v-for="z in dnsZones" :key="z" :value="z">{{ z }}</option>
          </Select>
          <Button variant="secondary" size="sm" @click="downloadZonefile" :disabled="loadError"><Download class="size-3.5" />Download zone file</Button>
        </div>
      </template>
    </PageHeader>

    <p class="text-sm text-muted mb-6">
      If this box's DNS is managed by an external provider, set the following records.
      Records marked <Badge variant="error">Required</Badge> must be set.
      <Badge variant="warning">Recommended</Badge> records improve deliverability.
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
              <td class="px-4 py-3 text-xs hidden lg:table-cell">
                <Badge v-if="record.explanation.startsWith('Required.')" variant="error">{{ record.explanation }}</Badge>
                <Badge v-else-if="record.explanation.startsWith('Recommended.')" variant="warning">{{ record.explanation }}</Badge>
                <span v-else class="text-faint">{{ record.explanation }}</span>
              </td>
            </TableRow>
          </tbody>
        </Table>
      </div>
    </template>
  </AppLayout>
</template>

