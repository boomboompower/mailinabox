<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { toast } from 'vue-sonner'
import { RefreshCw } from 'lucide-vue-next'
import AsyncState from '@/components/ui/AsyncState.vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import Button from '@/components/ui/Button.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import Card from '@/components/ui/Card.vue'
import Dialog from '@/components/ui/Dialog.vue'
import Divider from '@/components/ui/Divider.vue'
import StatusIcon from '@/components/shared/StatusIcon.vue'
import { useApi } from '@/composables/useApi'
import type { StatusCheckItem, StatusCheckResponse } from '@/types'

// Status checks take 10-30s. 8s balances responsiveness against server load:
// fast enough that results appear promptly once ready, slow enough not to hammer
// the endpoint while the subprocess pool is still working.
const POLL_INTERVAL_MS = 8_000

const api = useApi()

const loading = ref(true)
const jobStatus = ref<'idle' | 'running' | 'done'>('idle')
const items = ref<StatusCheckItem[]>([])
const checkedAt = ref<string | null>(null)
const source = ref<'cron' | 'manual' | null>(null)
const loadError = ref(false)
const expanded = ref(new Set<number>())
let pollTimer: ReturnType<typeof setInterval> | null = null

// Privacy and reboot are cheap fetches loaded independently so they never
// gate or slow down the expensive status check display.
const privacy = ref<boolean | null>(null)
const rebootNeeded = ref<boolean | null>(null)
const rebootOpen = ref(false)
const rebooting = ref(false)

const activeTab = ref<string | null>(null)

type SectionItem = { item: StatusCheckItem; idx: number }
type Section = { heading: string; items: SectionItem[] }

const SEVERITY: Record<string, number> = { error: 0, warning: 1, ok: 2 }

const sections = computed<Section[]>(() => {
  const result: Section[] = []
  let current: Section | null = null
  items.value.forEach((item, idx) => {
    if (item.type === 'heading') {
      current = { heading: item.text, items: [] }
      result.push(current)
    } else if (current) {
      current.items.push({ item, idx })
    }
  })
  for (const section of result) {
    section.items.sort((a, b) => {
      const sd = (SEVERITY[a.item.type] ?? 3) - (SEVERITY[b.item.type] ?? 3)
      if (sd !== 0) return sd
      return a.item.text.localeCompare(b.item.text)
    })
  }
  return result
})

// Auto-select: keep current tab if it still exists, otherwise pick first section with errors.
watch(sections, (newSections) => {
  if (!newSections.length) return
  if (activeTab.value && newSections.some(s => s.heading === activeTab.value)) return
  const withErrors = newSections.find(s => s.items.some(({ item }) => item.type === 'error'))
  activeTab.value = (withErrors ?? newSections[0]).heading
}, { immediate: true })

const activeSection = computed(() =>
  sections.value.find(s => s.heading === activeTab.value) ?? null
)

function sectionErrors(section: Section): number {
  return section.items.filter(({ item }) => item.type === 'error').length
}

function sectionWarnings(section: Section): number {
  return section.items.filter(({ item }) => item.type === 'warning').length
}

const checkedAtLabel = computed(() => {
  if (!checkedAt.value) return null
  const diff = Math.round((Date.now() - new Date(checkedAt.value).getTime()) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
})

function applyResponse(data: StatusCheckResponse): void {
  jobStatus.value = data.status
  if (data.items) items.value = data.items
  checkedAt.value = data.checked_at
  source.value = data.source
}

function startPolling(): void {
  if (pollTimer !== null) return
  pollTimer = setInterval(async () => {
    try {
      const res = await api.get('/admin/system/status')
      const data: StatusCheckResponse = await res.json()
      applyResponse(data)
      if (data.status !== 'running') stopPolling()
    } catch {
      // Keep polling on transient network errors
    }
  }, POLL_INTERVAL_MS)
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadStatus(): Promise<void> {
  loading.value = true
  loadError.value = false
  try {
    const res = await api.get('/admin/system/status')
    const data: StatusCheckResponse = await res.json()
    applyResponse(data)
    if (data.status === 'running') {
      startPolling()
    } else if (data.status === 'idle') {
      // No cache yet (fresh install or cleared cache) - trigger automatically.
      await triggerRefresh()
    }
  } catch {
    loadError.value = true
    toast.error('Failed to load system status.')
  } finally {
    loading.value = false
  }
}

async function loadPrivacyAndReboot(): Promise<void> {
  try {
    const [privacyRes, rebootRes] = await Promise.all([
      api.get('/admin/system/privacy'),
      api.get('/admin/system/reboot'),
    ])
    privacy.value = await privacyRes.json()
    rebootNeeded.value = await rebootRes.json()
  } catch {
    // Non-critical - silently ignore
  }
}

async function triggerRefresh(): Promise<void> {
  try {
    const res = await api.post('/admin/system/status')
    const data: StatusCheckResponse = await res.json()
    applyResponse(data)
    startPolling()
    if (res.status === 202 && data.status === 'running' && items.value.length > 0) {
      toast.info('A check is already in progress.')
    }
  } catch {
    toast.error('Failed to start status check.')
  }
}

function toggleExpand(idx: number): void {
  if (expanded.value.has(idx)) {
    expanded.value.delete(idx)
  } else {
    expanded.value.add(idx)
  }
}

async function togglePrivacy(): Promise<void> {
  if (privacy.value === null) return
  const newVal = !privacy.value
  const res = await api.post('/admin/system/privacy', { value: newVal ? 'private' : 'off' })
  if (res.ok) {
    privacy.value = newVal
    toast.success(newVal ? 'Version check enabled.' : 'Version check disabled.')
  }
}

async function doReboot(): Promise<void> {
  rebooting.value = true
  try {
    const res = await api.post('/admin/system/reboot')
    if (res.ok) {
      toast.success('Reboot initiated. Reload this page in about a minute.')
      rebootOpen.value = false
    }
  } catch {
    toast.error('Failed to initiate reboot.')
  } finally {
    rebooting.value = false
  }
}

onMounted(() => {
  // Fire independently - privacy/reboot never block the status check display.
  loadStatus()
  loadPrivacyAndReboot()
})

onUnmounted(stopPolling)
</script>

<template>
  <AppLayout>
    <PageHeader title="System Status" description="Health and configuration checks for this server.">
      <template v-if="checkedAtLabel" #description>
        <p class="text-xs text-faint mt-0.5">
          Last checked {{ checkedAtLabel }}<span v-if="source === 'cron'" class="ml-1">(nightly)</span>
        </p>
      </template>
      <template #actions>
        <Button
          variant="secondary"
          size="sm"
          :disabled="jobStatus === 'running'"
          @click="triggerRefresh"
        >
          <RefreshCw class="size-4 mr-1.5" :class="{ 'animate-spin': jobStatus === 'running' }" />
          {{ jobStatus === 'running' ? 'Checking...' : 'Refresh' }}
        </Button>
      </template>
    </PageHeader>

    <!-- Reboot banner -->
    <Card
      v-if="rebootNeeded"
      class="p-4 mb-5 border-yellow-300 dark:border-yellow-700 bg-yellow-50 dark:bg-yellow-950/30"
    >
      <p class="text-sm font-medium text-yellow-800 dark:text-yellow-200">
        A system reboot is required to apply package updates.
      </p>
      <Button variant="secondary" size="sm" class="mt-2" @click="rebootOpen = true">
        Reboot Now
      </Button>
    </Card>

    <AsyncState
      :loading="loading || (jobStatus === 'running' && items.length === 0)"
      :error="loadError"
      :empty="false"
      error-title="Could not load status checks"
      @retry="loadStatus"
    >
      <template #loading>
        <div class="flex gap-0 border-b border-border mb-6">
          <Skeleton v-for="i in 4" :key="i" class="h-9 w-24 mr-2 mb-px rounded-b-none" />
        </div>
        <div class="space-y-2">
          <div v-for="i in 6" :key="i" class="flex items-center gap-3 py-2">
            <Skeleton class="size-4 rounded-full shrink-0" />
            <Skeleton class="h-4" :class="i % 2 === 0 ? 'w-3/4' : 'w-1/2'" />
          </div>
        </div>
      </template>

      <!-- Stale cache notice while a new check runs -->
      <p v-if="jobStatus === 'running'" class="text-xs text-faint mb-4">
        Showing previous results while the new check runs...
      </p>

      <!-- Tab bar -->
      <div class="flex gap-0 border-b border-border mb-6">
        <button
          v-for="section in sections"
          :key="section.heading"
          :class="[
            'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors flex items-center gap-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded',
            activeTab === section.heading
              ? 'border-text text-text'
              : 'border-transparent text-muted hover:text-text',
          ]"
          @click="activeTab = section.heading; expanded = new Set()"
        >
          {{ section.heading }}
          <span
            v-if="sectionErrors(section) > 0"
            class="text-xs px-1.5 py-0.5 rounded-full font-medium bg-red-100 dark:bg-red-950/50 text-red-600 dark:text-red-400"
          >{{ sectionErrors(section) }}</span>
          <span
            v-else-if="sectionWarnings(section) > 0"
            class="text-xs px-1.5 py-0.5 rounded-full font-medium bg-yellow-100 dark:bg-yellow-950/50 text-yellow-600 dark:text-yellow-400"
          >{{ sectionWarnings(section) }}</span>
          <span v-else class="size-2 rounded-full bg-emerald-500 dark:bg-emerald-400" />
        </button>
      </div>

      <!-- Active section -->
      <Card v-if="activeSection">
        <template
          v-for="({ item, idx }, i) in activeSection.items"
          :key="idx"
        >
          <Divider v-if="i > 0" />
          <div class="px-4 py-3">
            <div class="flex items-start gap-3">
              <StatusIcon :status="item.type as 'ok' | 'error' | 'warning'" class="mt-0.5 shrink-0" />
              <div class="flex-1 min-w-0 break-words">
                <p class="text-sm font-medium">{{ item.text }}</p>
                <p v-if="item.detail" class="text-sm text-muted dark:text-faint mt-0.5">{{ item.detail }}</p>
                <div v-if="expanded.has(idx) && item.extra.length" class="mt-2 space-y-1">
                  <p
                    v-for="(ex, ei) in item.extra.filter(e => e.text.trim())"
                    :key="ei"
                    class="text-xs text-muted dark:text-faint"
                    :class="{ 'font-mono whitespace-pre-wrap': ex.monospace }"
                  >
                    {{ ex.text }}
                  </p>
                </div>
                <Button
                  v-if="item.extra.some(e => e.text.trim())"
                  variant="link"
                  size="sm"
                  class="mt-1 text-faint"
                  :aria-expanded="expanded.has(idx)"
                  @click="toggleExpand(idx)"
                >
                  {{ expanded.has(idx) ? 'show less' : 'show more' }}
                </Button>
              </div>
            </div>
          </div>
        </template>
      </Card>

      <!-- System Tools -->
      <Card class="p-5 mt-6">
        <h2 class="text-sm font-semibold mb-3">System Tools</h2>
        <div class="flex flex-wrap gap-3">
          <div>
            <p class="text-xs text-muted mb-1.5">
              Version check: {{ privacy === true ? 'enabled' : privacy === false ? 'disabled' : '...' }}
            </p>
            <Button variant="secondary" size="sm" :disabled="privacy === null" @click="togglePrivacy">
              {{ privacy ? 'Disable Version Check' : 'Enable Version Check' }}
            </Button>
          </div>
          <div v-if="rebootNeeded === false">
            <p class="text-xs text-muted mb-1.5">No reboot required.</p>
            <Button variant="secondary" size="sm" disabled>Reboot</Button>
          </div>
          <div v-else-if="rebootNeeded">
            <p class="text-xs text-muted mb-1.5">Reboot pending.</p>
            <Button variant="secondary" size="sm" @click="rebootOpen = true">Reboot Now</Button>
          </div>
        </div>
      </Card>
    </AsyncState>

    <!-- Reboot confirm -->
    <Dialog
      v-model="rebootOpen"
      title="Reboot server?"
      description="This will reboot your Mail-in-a-Box instance. Mail will be unavailable for about a minute."
    >
      <template #actions>
        <Button variant="secondary" @click="rebootOpen = false">Cancel</Button>
        <Button variant="destructive" :disabled="rebooting" @click="doReboot">
          {{ rebooting ? 'Rebooting...' : 'Reboot Now' }}
        </Button>
      </template>
    </Dialog>
  </AppLayout>
</template>
