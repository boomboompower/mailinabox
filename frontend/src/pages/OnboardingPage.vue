<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { toast } from 'vue-sonner'
import { useAuthStore } from '@/stores/auth'
import { useConfigStore } from '@/stores/config'
import Button from '@/components/ui/Button.vue'
import Code from '@/components/ui/Code.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import PageBackground from '@/components/ui/PageBackground.vue'
import type { BootstrapCodeError } from '@/types'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const config = useConfigStore()

const code = ref('')

onMounted(() => {
  const urlCode = route.query.code
  if (urlCode) code.value = String(urlCode)
})
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const attemptsRemaining = ref<number | null>(null)

async function submit(): Promise<void> {
  if (loading.value) return

  if (password.value !== confirmPassword.value) {
    toast.error('Passwords do not match.')
    return
  }

  loading.value = true
  attemptsRemaining.value = null

  try {
    const fd = new FormData()
    fd.append('code', code.value.replace(/\s/g, '').toUpperCase())
    fd.append('email', email.value.trim())
    fd.append('password', password.value)

    const res = await fetch('/admin/bootstrap/setup', {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: fd,
    })

    if (res.ok) {
      auth.clearBootstrap()
      await router.push('/login')
      toast.success('Account created. Sign in to continue.')
      return
    }

    const data: BootstrapCodeError = await res.json().catch(() => ({ error: 'not_found' as const }))

    if (data.error === 'invalid_code') {
      attemptsRemaining.value = data.attempts_remaining ?? null
      toast.error(
        attemptsRemaining.value !== null
          ? `Incorrect code. ${attemptsRemaining.value} ${attemptsRemaining.value === 1 ? 'attempt' : 'attempts'} remaining.`
          : 'Incorrect code.',
      )
    } else if (data.error === 'expired') {
      toast.error('Bootstrap code expired. Run: sudo boxctl bootstrap')
    } else if (data.error === 'locked') {
      toast.error('Too many failed attempts. Run: sudo boxctl bootstrap to get a new code.')
    } else {
      toast.error('No active bootstrap session. Run: sudo boxctl bootstrap')
    }
  } catch {
    toast.error('Something went wrong. Please try again.')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <PageBackground class="flex items-center justify-center p-4">
    <Card class="w-full max-w-sm p-6">
      <h1 class="text-2xl font-semibold text-center mb-1">
        {{ config.hostname || 'Mail-in-a-Box' }}
      </h1>
      <p class="text-sm text-muted text-center mb-7">Initial setup</p>

      <p class="text-sm text-muted mb-5">
        No admin account exists yet. Run <Code>sudo boxctl bootstrap</Code> in your terminal to get a setup code, then fill in the form below.
      </p>

      <form class="space-y-4" @submit.prevent="submit">
        <div>
          <label for="setupCode" class="block text-sm font-medium mb-1.5">Setup code</label>
          <Input
            id="setupCode"
            v-model="code"
            type="text"
            autocomplete="off"
            spellcheck="false"
            placeholder="XXXXXXXX"
            :maxlength="9"
            class="font-mono tracking-widest uppercase"
            required
          />
          <p v-if="attemptsRemaining !== null" class="mt-1.5 text-xs text-red-500">
            {{ attemptsRemaining }} {{ attemptsRemaining === 1 ? 'attempt' : 'attempts' }} remaining before lockout.
          </p>
        </div>

        <div>
          <label for="setupEmail" class="block text-sm font-medium mb-1.5">Admin email</label>
          <Input id="setupEmail" v-model="email" type="email" autocomplete="email" required />
        </div>

        <div>
          <label for="setupPassword" class="block text-sm font-medium mb-1.5">Password</label>
          <Input id="setupPassword" v-model="password" type="password" autocomplete="new-password" required />
        </div>

        <div>
          <label for="setupConfirm" class="block text-sm font-medium mb-1.5">Confirm password</label>
          <Input id="setupConfirm" v-model="confirmPassword" type="password" autocomplete="new-password" required />
        </div>

        <Button type="submit" class="w-full" :disabled="loading">
          {{ loading ? 'Creating account...' : 'Create admin account' }}
        </Button>
      </form>
    </Card>
  </PageBackground>
</template>
