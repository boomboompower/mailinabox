<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { Key, WifiOff, Plus } from 'lucide-vue-next'
import AppLayout from '@/components/layout/AppLayout.vue'
import Button from '@/components/ui/Button.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import Field from '@/components/ui/Field.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Card from '@/components/ui/Card.vue'
import Code from '@/components/ui/Code.vue'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Dialog from '@/components/ui/Dialog.vue'
import Sheet from '@/components/ui/Sheet.vue'
import Table from '@/components/ui/Table.vue'
import TableHead from '@/components/ui/TableHead.vue'
import Th from '@/components/ui/Th.vue'
import TableRow from '@/components/ui/TableRow.vue'
import { useApi } from '@/composables/useApi'
import type { ApiToken, ApiTokenCreateResponse } from '@/types'

const api = useApi()

const loading = ref(true)
const loadError = ref(false)
const tokens = ref<ApiToken[]>([])

// Create sheet state
const createOpen = ref(false)
const creating = ref(false)
const newName = ref('')
const newScope = ref('read')

// Reveal dialog state - shown once after token creation
const revealOpen = ref(false)
const revealedToken = ref('')
const copied = ref(false)

// Revoke confirm dialog state
const revokeOpen = ref(false)
const revokeTarget = ref<ApiToken | null>(null)
const revoking = ref(false)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = false
  try {
    const res = await api.get('/admin/tokens')
    if (!res.ok) {
      loadError.value = true
      toast.error('Failed to load API tokens.')
      return
    }
    tokens.value = await res.json()
  } catch {
    loadError.value = true
    toast.error('Failed to load API tokens.')
  } finally {
    loading.value = false
  }
}

async function createToken(): Promise<void> {
  if (!newName.value.trim() || creating.value) return
  creating.value = true
  try {
    const res = await api.post('/admin/tokens', {
      name: newName.value.trim(),
      scope: newScope.value,
    })
    if (!res.ok) {
      toast.error(await res.text())
      return
    }
    const data: ApiTokenCreateResponse = await res.json()
    createOpen.value = false
    newName.value = ''
    newScope.value = 'read'
    revealedToken.value = data.token
    copied.value = false
    revealOpen.value = true
    await load()
  } finally {
    creating.value = false
  }
}

async function copyToken(): Promise<void> {
  try {
    await navigator.clipboard.writeText(revealedToken.value)
    copied.value = true
  } catch {
    toast.error('Could not copy to clipboard.')
  }
}

function openRevoke(token: ApiToken): void {
  revokeTarget.value = token
  revokeOpen.value = true
}

async function confirmRevoke(): Promise<void> {
  if (!revokeTarget.value || revoking.value) return
  revoking.value = true
  try {
    const res = await api.del(`/admin/tokens/${revokeTarget.value.id}`)
    if (!res.ok) {
      toast.error(await res.text())
      return
    }
    toast.success(`Token "${revokeTarget.value.name}" revoked.`)
    revokeOpen.value = false
    await load()
  } finally {
    revoking.value = false
  }
}

function formatDate(iso: string): string {
  return new Date(iso + 'Z').toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

watch(revealOpen, (open) => {
  if (!open) {
    revealedToken.value = ''
    copied.value = false
  }
})

onMounted(load)
</script>

<template>
  <AppLayout>
    <PageHeader title="API Tokens">
      <template v-if="!loadError" #actions>
        <Button size="sm" @click="createOpen = true"><Plus class="size-3.5" />New token</Button>
      </template>
    </PageHeader>

    <p class="text-sm text-muted mb-6">
      API tokens let external scripts and tools authenticate to the admin API
      without using your password. Each token can be scoped to read-only or
      read-write access. Tokens cannot create other tokens or grant admin privileges.
    </p>

    <EmptyState
      v-if="loadError"
      title="Could not load tokens"
      description="The server did not respond. Check your connection and try again."
    >
      <template #icon><WifiOff /></template>
      <template #action>
        <Button variant="secondary" @click="load">Try again</Button>
      </template>
    </EmptyState>

    <Card v-else class="overflow-hidden">
      <!-- Loading skeleton -->
      <template v-if="loading">
        <div class="p-5 space-y-3">
          <Skeleton class="h-4 w-64" />
          <Skeleton class="h-4 w-48" />
          <Skeleton class="h-4 w-56" />
        </div>
      </template>

      <!-- Empty state -->
      <EmptyState
        v-else-if="tokens.length === 0"
        title="No API tokens"
        description="Create a token to authenticate scripts and tools against the admin API."
        class="py-10"
      >
        <template #icon><Key /></template>
        <template #action>
          <Button @click="createOpen = true">New token</Button>
        </template>
      </EmptyState>

      <!-- Token table -->
      <Table v-else>
        <TableHead>
          <Th>Name</Th>
          <Th>Scope</Th>
          <Th>Created</Th>
          <Th>Last used</Th>
          <Th />
        </TableHead>
        <tbody>
          <TableRow v-for="token in tokens" :key="token.id">
            <td class="px-4 py-3 text-sm font-medium">{{ token.name }}</td>
            <td class="px-4 py-3">
              <Badge :variant="token.scope === 'write' ? 'success' : 'default'">
                {{ token.scope }}
              </Badge>
            </td>
            <td class="px-4 py-3 text-sm text-muted">{{ formatDate(token.created_at) }}</td>
            <td class="px-4 py-3 text-sm text-muted">
              {{ token.last_used ? formatDate(token.last_used) : 'Never' }}
            </td>
            <td class="px-4 py-3 text-right">
              <Button variant="ghost" size="sm" @click="openRevoke(token)">Revoke</Button>
            </td>
          </TableRow>
        </tbody>
      </Table>
    </Card>

    <!-- Create token sheet -->
    <Sheet v-model="createOpen" title="New API token">
      <div class="space-y-5">
        <Field label="Name" for="tokenName">
          <Input
            id="tokenName"
            v-model="newName"
            placeholder="e.g. Backup script"
            @keydown.enter="createToken"
          />
          <p class="text-xs text-muted mt-1.5">A label so you can identify this token later.</p>
        </Field>

        <Field label="Scope" for="tokenScope">
          <Select id="tokenScope" v-model="newScope">
            <option value="read">Read - can only read data, no changes</option>
            <option value="write">Write - can read and make changes</option>
          </Select>
          <p class="text-xs text-muted mt-1.5">
            Read tokens can fetch data but cannot change settings, send email, or trigger actions.
            Write tokens have full access to the API except for managing other tokens and admin users.
          </p>
        </Field>
      </div>

      <template #footer>
        <div class="flex gap-2 justify-end">
          <Button variant="secondary" @click="createOpen = false">Cancel</Button>
          <Button :disabled="!newName.trim() || creating" @click="createToken">
            {{ creating ? 'Creating...' : 'Create token' }}
          </Button>
        </div>
      </template>
    </Sheet>

    <!-- Token reveal dialog - shown once after creation -->
    <Dialog
      v-model="revealOpen"
      title="Copy your new token"
      description="This token will not be shown again. Copy it now and store it somewhere safe."
    >
      <div class="space-y-3">
        <Code block class="break-all select-all">{{ revealedToken }}</Code>
        <Button variant="secondary" class="w-full" @click="copyToken">
          {{ copied ? 'Copied!' : 'Copy to clipboard' }}
        </Button>
      </div>
      <template #actions>
        <Button @click="revealOpen = false">I've copied it</Button>
      </template>
    </Dialog>

    <!-- Revoke confirm dialog -->
    <Dialog
      v-model="revokeOpen"
      title="Revoke token?"
      :description="`'${revokeTarget?.name}' will stop working immediately. This cannot be undone.`"
    >
      <template #actions>
        <Button variant="secondary" @click="revokeOpen = false">Cancel</Button>
        <Button variant="destructive" :disabled="revoking" @click="confirmRevoke">
          {{ revoking ? 'Revoking...' : 'Revoke' }}
        </Button>
      </template>
    </Dialog>
  </AppLayout>
</template>
