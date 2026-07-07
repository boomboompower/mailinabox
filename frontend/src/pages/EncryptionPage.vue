<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { LockKeyhole, Copy, AlertTriangle } from 'lucide-vue-next'
import AsyncState from '@/components/ui/AsyncState.vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import Button from '@/components/ui/Button.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeader from '@/components/ui/SectionHeader.vue'
import Field from '@/components/ui/Field.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import Code from '@/components/ui/Code.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Sheet from '@/components/ui/Sheet.vue'
import { useApi } from '@/composables/useApi'
import type { EncryptionStatus, EncryptionSetupResponse } from '@/types'

const api = useApi()

const loading = ref(true)
const loadError = ref(false)
const status = ref<EncryptionStatus | null>(null)

// The ceremony lives in a Sheet. Stages:
//   password  - destructive warning + confirm current password
//   codes     - recovery codes generated, waiting for user to confirm they saved them
//   challenge - user must re-enter one specific code to prove they saved it
const sheetOpen = ref(false)
// 'setup' = initial encryption enable, 'rotate' = replace recovery codes
const mode = ref<'setup' | 'rotate'>('setup')
const stage = ref<'password' | 'codes' | 'challenge'>('password')
const password = ref('')
const starting = ref(false)
const recoveryCodes = ref<string[]>([])
// Which code (1-based display) we ask the user to re-enter. Chosen client-side at random.
const challengeIndex = ref(1)
const challengeCode = ref('')
const submitting = ref(false)

// Re-link state (recover the password slot after a password change/reset).
const relinkOpen = ref(false)
const relinkCode = ref('')
const relinkPassword = ref('')
const relinking = ref(false)
// Shown after a successful re-link to prompt the user to rotate their codes.
const showRotatePrompt = ref(false)

const enabled = computed(() => status.value?.enabled === true)

const SLOT_LABELS: Record<string, string> = {
  password: 'Login password',
  recovery_code: 'Recovery code',
  passkey_prf: 'Passkey',
}

// Wipe any secrets held in memory whenever the ceremony sheet closes.
watch(sheetOpen, (open) => {
  if (!open) {
    password.value = ''
    recoveryCodes.value = []
    challengeCode.value = ''
    stage.value = 'password'
  }
})

// ── Client-side recovery-code CRC (mirrors mail_crypt.validate_recovery_code_crc) ──
const CROCKFORD = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'

function normalizeCode(code: string): string {
  return code.trim().toUpperCase().replace(/[-\s]/g, '')
    .replace(/O/g, '0').replace(/I/g, '1').replace(/L/g, '1')
}

function validateCrc(code: string): boolean {
  const s = normalizeCode(code)
  if (s.length !== 16) return false
  const values: number[] = []
  for (const ch of s) {
    const v = CROCKFORD.indexOf(ch)
    if (v < 0) return false
    values.push(v)
  }
  const data = values.slice(0, 15)
  const cs = data.reduce((acc, v, i) => acc + v * (i + 1), 0) % 37
  if (cs >= 32) return false
  return CROCKFORD[cs] === s[15]
}

const challengeCodeValid = computed(() => validateCrc(challengeCode.value))
const challengeOrdinal = computed(() => {
  const n = challengeIndex.value
  return n === 1 ? '1st' : n === 2 ? '2nd' : n === 3 ? '3rd' : `${n}th`
})

async function load(): Promise<void> {
  loading.value = true
  loadError.value = false
  try {
    const res = await api.get('/admin/user/encryption/status')
    if (!res.ok) {
      loadError.value = true
      return
    }
    status.value = await res.json()
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function openCeremony(m: 'setup' | 'rotate'): void {
  mode.value = m
  password.value = ''
  recoveryCodes.value = []
  challengeCode.value = ''
  stage.value = 'password'
  sheetOpen.value = true
}

async function startSetup(): Promise<void> {
  if (!password.value || starting.value) return
  starting.value = true
  try {
    const endpoint = mode.value === 'rotate'
      ? '/admin/user/encryption/rotate-recovery'
      : '/admin/user/encryption/setup'
    const res = await api.post(endpoint, { password: password.value })
    if (!res.ok) {
      toast.error(await res.text())
      return
    }
    const data: EncryptionSetupResponse = await res.json()
    recoveryCodes.value = data.recovery_codes
    password.value = ''
    stage.value = 'codes'
  } finally {
    starting.value = false
  }
}

async function copyCodes(): Promise<void> {
  try {
    await navigator.clipboard.writeText(recoveryCodes.value.join('\n'))
    toast.success('Recovery codes copied to clipboard.')
  } catch {
    toast.error('Could not copy. Select and copy the codes manually.')
  }
}

function confirmSaved(): void {
  // Pick a random code for the challenge so users cannot blindly click through.
  challengeIndex.value = Math.floor(Math.random() * recoveryCodes.value.length) + 1
  challengeCode.value = ''
  stage.value = 'challenge'
}

async function submitChallenge(): Promise<void> {
  if (submitting.value) return
  if (!validateCrc(challengeCode.value)) {
    toast.error('That does not look like a valid recovery code. Check for typos.')
    return
  }
  submitting.value = true
  try {
    const endpoint = mode.value === 'rotate'
      ? '/admin/user/encryption/rotate-recovery-confirm'
      : '/admin/user/encryption/challenge'
    // challengeIndex is 1-based for display; slot labels are 0-based.
    const res = await api.post(endpoint, {
      code_index: String(challengeIndex.value - 1),
      code: challengeCode.value,
    })
    if (!res.ok) {
      toast.error(await res.text())
      return
    }
    sheetOpen.value = false
    if (mode.value === 'rotate') {
      showRotatePrompt.value = false
      toast.success('Recovery codes rotated. Keep your new codes safe.')
    } else {
      toast.success('Encryption at rest is now enabled.')
      await load()
    }
  } finally {
    submitting.value = false
  }
}

const relinkCodeValid = computed(() => validateCrc(relinkCode.value))

// Wipe re-link secrets when its sheet closes.
watch(relinkOpen, (open) => {
  if (!open) {
    relinkCode.value = ''
    relinkPassword.value = ''
  }
})

async function submitRelink(): Promise<void> {
  if (relinking.value) return
  if (!validateCrc(relinkCode.value)) {
    toast.error('That does not look like a valid recovery code. Check for typos.')
    return
  }
  if (!relinkPassword.value) {
    toast.error('Enter your current password.')
    return
  }
  relinking.value = true
  try {
    const res = await api.post('/admin/user/encryption/relink', {
      code: relinkCode.value,
      password: relinkPassword.value,
    })
    if (!res.ok) {
      toast.error(await res.text())
      return
    }
    relinkOpen.value = false
    showRotatePrompt.value = true
    toast.success('Encryption re-linked. Your password now unlocks your mail again.')
  } finally {
    relinking.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppLayout>
    <PageHeader title="Encryption at Rest" description="Encrypt your mailbox with a key only you can unlock." />

    <AsyncState :loading="loading" :error="loadError" :empty="false" error-title="Could not load encryption settings" @retry="load">
      <template #loading>
        <SectionHeader title="Status" />
        <Card class="p-6">
          <Skeleton class="size-12 rounded-full mb-4" />
          <Skeleton class="h-5 w-56 mb-2" />
          <Skeleton class="h-4 w-80 mb-4" />
          <Skeleton class="h-5 w-24" />
        </Card>
      </template>

      <SectionHeader title="Status" />

      <!-- Enabled -->
      <Card v-if="enabled" class="p-6">
        <div class="flex items-start gap-5">
          <div class="flex-none size-12 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
            <LockKeyhole class="size-6 text-emerald-600 dark:text-emerald-400" />
          </div>
          <div class="min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <p class="text-base font-semibold text-text">Your mailbox is encrypted at rest</p>
              <Badge variant="success">Enabled</Badge>
            </div>
            <p class="text-sm text-muted mb-4">
              Your mail is unlocked with your login password. Keep your recovery codes safe -
              they are the only other way to unlock it if you lose access.
            </p>
            <div v-if="status?.slot_types?.length" class="flex flex-wrap gap-1.5">
              <span class="text-xs text-muted mr-1 self-center">Active unlock methods:</span>
              <Badge v-for="t in status.slot_types" :key="t" variant="default">{{ SLOT_LABELS[t] ?? t }}</Badge>
            </div>
          </div>
        </div>
      </Card>

      <!-- Actions available when encryption is enabled -->
      <template v-if="enabled">
        <SectionHeader title="Recover access" class="mt-8" />
        <Card class="p-5">
          <p class="text-sm text-muted mb-4">
            If your password was changed or reset, your login may no longer unlock your encrypted mail.
            Re-link it with a recovery code to restore access - this does not change your recovery codes.
          </p>
          <Button variant="secondary" @click="relinkOpen = true">Re-link with a recovery code</Button>
        </Card>

        <SectionHeader title="Recovery codes" class="mt-8" />
        <Card class="p-5">
          <div v-if="showRotatePrompt" class="flex gap-3 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/10 p-4 mb-4">
            <AlertTriangle class="size-5 flex-none text-amber-600 dark:text-amber-400 mt-0.5" />
            <p class="text-sm text-muted">
              You used a recovery code to re-link.
              <span class="font-medium text-text">Generate a new set now</span>
              so your old codes cannot be reused by someone who may have seen them.
            </p>
          </div>
          <p class="text-sm text-muted mb-4">
            Your 4 recovery codes are the only way to unlock your mail if you forget your password.
            Rotate them if you think any code was exposed.
          </p>
          <Button variant="secondary" @click="openCeremony('rotate')">Generate new recovery codes</Button>
        </Card>
      </template>

      <!-- Not enabled -->
      <EmptyState
        v-else
        title="Encryption at rest is off"
        description="Enable it to encrypt your mailbox with a key derived from your login password. You will be given recovery codes to store safely."
      >
        <template #icon><LockKeyhole /></template>
        <template #action>
          <Button @click="openCeremony('setup')">Enable encryption</Button>
        </template>
      </EmptyState>
    </AsyncState>

    <!-- Setup / rotate ceremony (shared sheet, mode-aware) -->
    <Sheet v-model="sheetOpen" :title="mode === 'rotate' ? 'Generate new recovery codes' : 'Enable encryption at rest'">
      <!-- Stage: password -->
      <template v-if="stage === 'password'">
        <div v-if="mode === 'setup'" class="flex gap-3 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/10 p-4 mb-5">
          <AlertTriangle class="size-5 flex-none text-red-600 dark:text-red-400 mt-0.5" />
          <div class="text-sm">
            <p class="font-medium text-red-600 dark:text-red-400 mb-1">Read this before you continue.</p>
            <ul class="list-disc pl-4 space-y-1 text-muted">
              <li>Your mail is unlocked by your login password. If you forget it, only a recovery code can restore access.</li>
              <li>If you lose your password <span class="font-medium">and</span> all recovery codes, your mail is permanently unrecoverable. There is no master key.</li>
              <li>If an administrator resets your password, you will need a recovery code to regain access to your mail.</li>
            </ul>
          </div>
        </div>
        <p v-else class="text-sm text-muted mb-5">
          Your current password is needed to unlock your mail key before generating new codes.
          Your old codes will remain valid until you confirm the new ones.
        </p>

        <Field :label="mode === 'rotate' ? 'Current password' : 'Confirm your current password to continue'" for="encPassword">
          <Input
            id="encPassword"
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="Your account password"
          />
        </Field>
      </template>

      <!-- Stage: codes -->
      <template v-else-if="stage === 'codes'">
        <p class="text-sm text-muted mb-4">
          These codes are shown <span class="font-medium text-text">once</span> and cannot be retrieved later.
          Store them somewhere safe and offline. Each code can unlock your mailbox if you forget your password.
        </p>

        <div class="space-y-2 mb-4">
          <div v-for="(code, i) in recoveryCodes" :key="i" class="flex items-center gap-3">
            <span class="text-xs font-mono text-faint w-5 text-right shrink-0">{{ i + 1 }}.</span>
            <Code block class="flex-1 text-center tracking-widest">{{ code }}</Code>
          </div>
        </div>

        <Button variant="secondary" size="sm" @click="copyCodes">
          <Copy class="size-4" /> Copy all
        </Button>
      </template>

      <!-- Stage: challenge -->
      <template v-else-if="stage === 'challenge'">
        <p class="text-sm text-muted mb-4">
          To make sure you saved them correctly, enter recovery code
          <span class="font-medium text-text">#{{ challengeIndex }}</span>.
        </p>
        <Field :label="`Recovery code #${challengeIndex}`" for="challengeCode">
          <Input
            id="challengeCode"
            v-model="challengeCode"
            placeholder="XXXX-XXXX-XXXX-XXXX"
            class="font-mono tracking-widest uppercase"
            autocomplete="off"
          />
          <p class="text-xs text-muted mt-1.5">Enter the {{ challengeOrdinal }} code exactly as shown.</p>
        </Field>
      </template>

      <!-- Footer: stage-specific actions -->
      <template #footer>
        <div class="flex justify-end gap-2">
          <template v-if="stage === 'password'">
            <Button variant="secondary" @click="sheetOpen = false">Cancel</Button>
            <Button :disabled="!password || starting" @click="startSetup">
              {{ starting ? 'Generating...' : 'Continue' }}
            </Button>
          </template>
          <template v-else-if="stage === 'codes'">
            <Button variant="secondary" @click="sheetOpen = false">Cancel</Button>
            <Button @click="confirmSaved">I have saved my codes</Button>
          </template>
          <template v-else>
            <Button variant="ghost" @click="stage = 'codes'">Back</Button>
            <Button :disabled="!challengeCodeValid || submitting" @click="submitChallenge">
              {{ submitting ? 'Verifying...' : 'Confirm' }}
            </Button>
          </template>
        </div>
      </template>
    </Sheet>

    <!-- Re-link ceremony -->
    <Sheet v-model="relinkOpen" title="Re-link encryption">
      <p class="text-sm text-muted mb-5">
        Enter one of your recovery codes and your <span class="font-medium text-text">current</span> password.
        We will unlock your mail key with the recovery code and re-attach it to your current password.
      </p>
      <div class="space-y-4">
        <Field label="Recovery code" for="relinkCode">
          <Input
            id="relinkCode"
            v-model="relinkCode"
            placeholder="XXXX-XXXX-XXXX-XXXX"
            class="font-mono tracking-widest uppercase"
            autocomplete="off"
          />
        </Field>
        <Field label="Current password" for="relinkPassword">
          <Input
            id="relinkPassword"
            v-model="relinkPassword"
            type="password"
            autocomplete="current-password"
            placeholder="Your current account password"
          />
        </Field>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <Button variant="secondary" @click="relinkOpen = false">Cancel</Button>
          <Button :disabled="!relinkCodeValid || !relinkPassword || relinking" @click="submitRelink">
            {{ relinking ? 'Re-linking...' : 'Re-link' }}
          </Button>
        </div>
      </template>
    </Sheet>
  </AppLayout>
</template>
