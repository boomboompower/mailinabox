<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { HardDrive, Settings2, AlertTriangle, WifiOff } from 'lucide-vue-next'
import AsyncState from '@/components/ui/AsyncState.vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import Button from '@/components/ui/Button.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import Field from '@/components/ui/Field.vue'
import Checkbox from '@/components/ui/Checkbox.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import Card from '@/components/ui/Card.vue'
import Sheet from '@/components/ui/Sheet.vue'
import Table from '@/components/ui/Table.vue'
import TableHead from '@/components/ui/TableHead.vue'
import Th from '@/components/ui/Th.vue'
import TableRow from '@/components/ui/TableRow.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Well from '@/components/ui/Well.vue'
import { useApi } from '@/composables/useApi'
import { useConfigStore } from '@/stores/config'
import type { BackupEntry, BackupStatus, BackupConfig, BackupCheckResult } from '@/types'

const api = useApi()
const config = useConfigStore()

type BackupTargetType = 'off' | 'local' | 'rsync' | 's3' | 'b2'

const loadingStatus = ref(true)
const statusLoadError = ref(false)
const loadingConfig = ref(true)
const saving = ref(false)
const configSheetOpen = ref(false)

// Status data
const backups = ref<BackupEntry[]>([])
const unmatchedSize = ref(0)
const statusError = ref<string | null>(null)
const backupsOff = ref(false)
const backupBackend = ref<'restic' | 'duplicity' | null>(null)
const lastCheck = ref<BackupCheckResult | null>(null)

// Config read-only info
const fileTargetDir = ref('')
const encPwFile = ref('')
const sshPubKey = ref('')

// Config form state
const targetType = ref<BackupTargetType>('local')
const minAge = ref('3')
const checkAfterBackup = ref(true)
// rsync
const rsyncUser = ref('')
const rsyncHost = ref('')
const rsyncPath = ref('')
// s3
const s3Region = ref('')
const s3Host = ref('')
const s3Path = ref('')
const s3AccessKey = ref('')
const s3SecretKey = ref('')
// b2
const b2AppKeyId = ref('')
const b2AppKey = ref('')
const b2Bucket = ref('')

function niceSize(bytes: number): string {
  const units = ['bytes', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (bytes >= 1000 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  const rounded = bytes >= 100 ? Math.round(bytes) : Math.round(bytes * 10) / 10
  return `${rounded} ${units[i]}`
}

function urlSplit(url: string): { scheme: string; user: string; host: string; path: string } {
  const schemeSep = url.indexOf('://')
  const scheme = schemeSep >= 0 ? url.substring(0, schemeSep) : ''
  const rest = schemeSep >= 0 ? url.substring(schemeSep + 3) : url
  const atIdx = rest.indexOf('@')
  const user = atIdx >= 0 ? rest.substring(0, atIdx) : ''
  const afterAt = atIdx >= 0 ? rest.substring(atIdx + 1) : rest
  const slashIdx = afterAt.indexOf('/')
  const host = slashIdx >= 0 ? afterAt.substring(0, slashIdx) : afterAt
  const path = slashIdx >= 0 ? afterAt.substring(slashIdx + 1) : ''
  return { scheme, user, host, path }
}

function parseConfig(cfg: BackupConfig): void {
  fileTargetDir.value = cfg.file_target_directory ?? ''
  encPwFile.value = cfg.enc_pw_file ?? ''
  sshPubKey.value = cfg.ssh_pub_key ?? ''
  minAge.value = String(cfg.min_age_in_days ?? 3)
  checkAfterBackup.value = cfg.check_after_backup ?? true

  const target = cfg.target ?? 'off'
  if (target === 'off') {
    targetType.value = 'off'
  } else if (target.startsWith('file://') || target === 'local') {
    targetType.value = 'local'
  } else if (target.startsWith('rsync://')) {
    targetType.value = 'rsync'
    const parts = urlSplit(target)
    rsyncUser.value = parts.user
    rsyncHost.value = parts.host
    rsyncPath.value = parts.path
  } else if (target.startsWith('s3://')) {
    targetType.value = 's3'
    const parts = urlSplit(target)
    // user part is the region name
    s3Region.value = parts.user
    s3Host.value = parts.host
    s3Path.value = parts.path
  } else if (target.startsWith('b2://')) {
    targetType.value = 'b2'
    const raw = target.substring(5)
    const colonIdx = raw.indexOf(':')
    b2AppKeyId.value = colonIdx >= 0 ? raw.substring(0, colonIdx) : raw
    const rest = colonIdx >= 0 ? raw.substring(colonIdx + 1) : ''
    const atIdx = rest.indexOf('@')
    b2AppKey.value = atIdx >= 0 ? decodeURIComponent(rest.substring(0, atIdx)) : rest
    b2Bucket.value = atIdx >= 0 ? rest.substring(atIdx + 1) : ''
  }
}

function buildTarget(): { target: string; target_user: string; target_pass: string } {
  switch (targetType.value) {
    case 'off':
      return { target: 'off', target_user: '', target_pass: '' }
    case 'local':
      return { target: 'local', target_user: '', target_pass: '' }
    case 'rsync':
      return {
        target: `rsync://${rsyncUser.value}@${rsyncHost.value}/${rsyncPath.value}`,
        target_user: '',
        target_pass: '',
      }
    case 's3':
      return {
        target: `s3://${s3Region.value ? s3Region.value + '@' : ''}${s3Host.value}/${s3Path.value}`,
        target_user: s3AccessKey.value,
        target_pass: s3SecretKey.value,
      }
    case 'b2':
      return {
        target: `b2://${b2AppKeyId.value}:${encodeURIComponent(b2AppKey.value)}@${b2Bucket.value}`,
        target_user: '',
        target_pass: '',
      }
  }
}

async function loadStatus(): Promise<void> {
  loadingStatus.value = true
  statusLoadError.value = false
  try {
    const res = await api.get('/admin/system/backup/status')
    const data: BackupStatus = await res.json()
    if (data.error) {
      statusError.value = data.error
    } else if (!data.backups) {
      backupsOff.value = true
    } else {
      backups.value = data.backups
      unmatchedSize.value = data.unmatched_file_size ?? 0
      backupBackend.value = data.backend ?? null
      lastCheck.value = data.last_check ?? null
    }
  } catch {
    statusLoadError.value = true
    toast.error('Failed to load backup status.')
  } finally {
    loadingStatus.value = false
  }
}

async function loadConfig(): Promise<void> {
  loadingConfig.value = true
  try {
    const res = await api.get('/admin/system/backup/config')
    const data: BackupConfig = await res.json()
    parseConfig(data)
  } catch {
    toast.error('Failed to load backup configuration.')
  } finally {
    loadingConfig.value = false
  }
}

async function save(): Promise<void> {
  if (saving.value) return
  saving.value = true
  try {
    const { target, target_user, target_pass } = buildTarget()
    const res = await api.post('/admin/system/backup/config', {
      target,
      target_user,
      target_pass,
      min_age: minAge.value,
      check_after_backup: String(checkAfterBackup.value),
    })
    const text = await res.text()
    if (!res.ok) {
      toast.error(text)
      return
    }
    toast.success(text || 'Backup configuration saved.')
    configSheetOpen.value = false
    // Reload status after config change
    backupsOff.value = false
    backups.value = []
    statusError.value = null
    backupBackend.value = null
    await loadStatus()
  } finally {
    saving.value = false
  }
}

const totalSize = computed(() => {
  const total = backups.value.reduce((sum, b) => sum + b.size, 0) + unmatchedSize.value
  return total > 0 ? niceSize(total) : null
})

const s3HostOptions = computed(() =>
  config.backupS3Hosts.map(([region, host]) => ({ region, host }))
)

onMounted(() => Promise.all([loadStatus(), loadConfig()]))
</script>

<template>
  <AppLayout>
    <PageHeader title="System Backup" description="Schedule and review backups of your mail, settings, and data.">
      <template #actions>
        <Button variant="secondary" size="sm" @click="configSheetOpen = true"><Settings2 class="size-3.5" />Configure</Button>
      </template>
    </PageHeader>

    <!-- Backup history -->
    <SectionHeader title="Backup History" />

    <AsyncState :loading="loadingStatus" :error="statusLoadError || !!statusError" :empty="backupsOff || backups.length === 0" error-title="Could not load backup status" @retry="loadStatus">
      <template #loading>
        <Table>
          <TableHead>
            <Th>Date</Th>
            <Th>Age</Th>
            <Th>Type</Th>
            <Th class="text-right">Size</Th>
            <Th>Deletes in</Th>
          </TableHead>
          <tbody>
            <TableRow v-for="i in 4" :key="i">
              <td class="px-4 py-3"><Skeleton class="h-4 w-40" /></td>
              <td class="px-4 py-3"><Skeleton class="h-4 w-24" /></td>
              <td class="px-4 py-3"><Skeleton class="h-4 w-20" /></td>
              <td class="px-4 py-3"><Skeleton class="h-4 w-16 ml-auto" /></td>
              <td class="px-4 py-3"><Skeleton class="h-4 w-28" /></td>
            </TableRow>
          </tbody>
        </Table>
      </template>

      <template #error>
        <EmptyState v-if="statusError" title="Backup unavailable" :description="statusError">
          <template #icon><AlertTriangle /></template>
        </EmptyState>
        <EmptyState v-else title="Could not load backup status" description="Check your connection and try again.">
          <template #icon><WifiOff /></template>
          <template #action><Button variant="secondary" @click="loadStatus">Try again</Button></template>
        </EmptyState>
      </template>

      <template #empty>
        <EmptyState
          title="No backups"
          :description="backupsOff ? 'Backups are turned off. Use Configure to set a backup target.' : 'No backups have been made yet.'"
        >
          <template #icon><HardDrive /></template>
        </EmptyState>
      </template>

      <Table>
        <TableHead>
          <Th>Date</Th>
          <Th>Age</Th>
          <Th>{{ backupBackend === 'restic' ? 'Snapshot' : 'Type' }}</Th>
          <Th class="text-right">Size</Th>
          <Th>Deletes in</Th>
        </TableHead>
        <tbody>
          <TableRow v-for="b in backups" :key="b.date">
            <td class="px-4 py-3 text-sm font-mono">{{ b.date_str }}</td>
            <td class="px-4 py-3 text-sm text-muted">{{ b.date_delta }} ago</td>
            <td class="px-4 py-3 text-sm">
              <template v-if="backupBackend === 'restic'">
                <span class="font-mono text-muted">{{ b.id ?? '—' }}</span>
              </template>
              <template v-else>{{ b.full ? 'full' : 'increment' }}</template>
            </td>
            <td class="px-4 py-3 text-sm text-right tabular-nums">
              <template v-if="backupBackend === 'restic'">
                <span v-if="b.size" class="text-text">{{ niceSize(b.size) }}</span>
                <span v-else class="text-faint">—</span>
                <div v-if="b.data_added || b.file_count" class="text-xs text-faint mt-0.5 space-x-2">
                  <span v-if="b.data_added">+{{ niceSize(b.data_added) }} new</span>
                  <span v-if="b.file_count">{{ b.file_count.toLocaleString() }} files</span>
                </div>
              </template>
              <template v-else>
                <span class="text-muted">{{ niceSize(b.size) }}</span>
              </template>
            </td>
            <td class="px-4 py-3 text-sm text-muted">{{ b.deleted_in ?? '—' }}</td>
          </TableRow>
        </tbody>
      </Table>
      <p v-if="totalSize" class="text-xs text-muted mt-2 text-right px-1">
        Total storage: {{ totalSize }}
      </p>
    </AsyncState>

    <!-- Integrity check warning - rendered after the table so it doesn't cause a layout shift on load -->
    <Card v-if="lastCheck && !lastCheck.passed" class="p-5 mt-6 border-red-200 dark:border-red-800">
      <p class="text-sm font-medium text-red-600 dark:text-red-400 mb-1">Backup integrity check failed</p>
      <p class="text-xs text-muted mb-3">Last checked {{ new Date(lastCheck.timestamp).toLocaleString() }}. An email has been sent to the administrator.</p>
      <pre v-if="lastCheck.output" class="text-xs font-mono whitespace-pre-wrap break-all text-text">{{ lastCheck.output }}</pre>
    </Card>

    <!-- Backup configuration sheet -->
    <Sheet v-model="configSheetOpen" title="Backup Configuration">
      <template v-if="loadingConfig">
        <div class="space-y-4">
          <Skeleton class="h-4 w-32" />
          <Skeleton class="h-9 w-full" />
          <Skeleton class="h-9 w-full" />
        </div>
      </template>
      <div v-else class="space-y-5">
        <Field label="Backup target" for="targetType">
          <Select id="targetType" v-model="targetType">
            <option value="off">Disabled</option>
            <option value="local">Local storage (on this machine)</option>
            <option value="rsync">Rsync to remote server</option>
            <option value="s3">Amazon S3 (or compatible)</option>
            <option value="b2">Backblaze B2</option>
          </Select>
        </Field>

        <!-- Local info -->
        <template v-if="targetType === 'local'">
          <Well class="text-sm space-y-1">
            <p class="text-muted">Storage location: <span class="font-mono text-text">{{ fileTargetDir }}</span></p>
            <p class="text-muted">Encryption key: <span class="font-mono text-text">{{ encPwFile }}</span></p>
          </Well>
        </template>

        <!-- Rsync fields -->
        <template v-if="targetType === 'rsync'">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Remote user" for="rsyncUser">
              <Input id="rsyncUser" v-model="rsyncUser" placeholder="backup-user" />
            </Field>
            <Field label="Remote host" for="rsyncHost">
              <Input id="rsyncHost" v-model="rsyncHost" placeholder="backup.example.com" />
            </Field>
            <Field label="Remote path" for="rsyncPath" class="sm:col-span-2">
              <Input id="rsyncPath" v-model="rsyncPath" placeholder="backups/mailinabox" />
            </Field>
          </div>
          <Well v-if="sshPubKey">
            <p class="text-xs font-medium text-muted mb-1.5">SSH public key (add to remote authorized_keys)</p>
            <pre class="text-xs font-mono text-text whitespace-pre-wrap break-all select-all">{{ sshPubKey }}</pre>
          </Well>
        </template>

        <!-- S3 fields -->
        <template v-if="targetType === 's3'">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="S3 endpoint / host" for="s3Host">
              <Select v-if="s3HostOptions.length" id="s3Host" v-model="s3Host">
                <option v-for="o in s3HostOptions" :key="o.host" :value="o.host">{{ o.host }}</option>
                <option value="">Other...</option>
              </Select>
              <Input v-if="s3HostOptions.length && s3Host === ''" v-model="s3Host" class="mt-2" placeholder="s3.amazonaws.com" />
              <Input v-else-if="!s3HostOptions.length" id="s3Host" v-model="s3Host" placeholder="s3.amazonaws.com" />
            </Field>
            <Field label="Region name" for="s3Region">
              <Input id="s3Region" v-model="s3Region" placeholder="us-east-1" />
            </Field>
            <Field label="Bucket path" for="s3Path">
              <Input id="s3Path" v-model="s3Path" placeholder="my-bucket/mailinabox" />
            </Field>
            <Field label="Access key ID" for="s3AccessKey">
              <Input id="s3AccessKey" v-model="s3AccessKey" autocomplete="off" placeholder="AKIA..." />
            </Field>
            <Field label="Secret access key" for="s3SecretKey" class="sm:col-span-2">
              <Input id="s3SecretKey" v-model="s3SecretKey" type="password" autocomplete="off" placeholder="wJalEXAMPLExFE..." />
            </Field>
          </div>
        </template>

        <!-- B2 fields -->
        <template v-if="targetType === 'b2'">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Application key ID" for="b2AppKeyId">
              <Input id="b2AppKeyId" v-model="b2AppKeyId" autocomplete="off" placeholder="4a1b2c3d4e5f6g7h8i9j0k" />
            </Field>
            <Field label="Application key" for="b2AppKey">
              <Input id="b2AppKey" v-model="b2AppKey" type="password" autocomplete="off" placeholder="b2_app_key_..." />
            </Field>
            <Field label="Bucket name" for="b2Bucket">
              <Input id="b2Bucket" v-model="b2Bucket" placeholder="my-mailinabox-bucket" />
            </Field>
          </div>
        </template>

        <!-- Min age (shown for all enabled targets) -->
        <Field v-if="targetType !== 'off'" label="Minimum backup age (days)" for="minAge">
          <Input id="minAge" v-model="minAge" type="number" class="max-w-xs" placeholder="3" />
          <p class="text-xs text-muted mt-1">Backups are kept for at least this many days before being deleted.</p>
        </Field>

        <div v-if="targetType !== 'off'" class="flex items-start gap-3">
          <Checkbox id="checkAfterBackup" v-model="checkAfterBackup" class="mt-0.5" />
          <div>
            <label for="checkAfterBackup" class="text-sm font-medium cursor-pointer">Verify backup integrity after each run</label>
            <p class="text-xs text-muted mt-0.5">Checks the backup chain for errors after each backup. Email is sent to the administrator if a problem is found.</p>
          </div>
        </div>

      </div>

      <template #footer>
        <div class="flex gap-2 justify-end">
          <Button variant="secondary" @click="configSheetOpen = false">Cancel</Button>
          <Button :disabled="saving" @click="save">
            {{ saving ? 'Saving...' : 'Save Configuration' }}
          </Button>
        </div>
      </template>
    </Sheet>
  </AppLayout>
</template>
