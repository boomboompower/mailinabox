<script setup lang="ts">
import AppLayout from '@/components/layout/AppLayout.vue'
import Card from '@/components/ui/Card.vue'
import { useConfigStore } from '@/stores/config'

const config = useConfigStore()
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold mb-2">Checking and Sending Mail</h1>
    <p class="text-sm text-gray-500 mb-6">Everything you need to access and manage your email.</p>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">

      <!-- Webmail -->
      <Card class="p-5">
        <p class="text-2xl mb-3">🌐</p>
        <h2 class="text-base font-semibold mb-2">Webmail</h2>
        <p class="text-sm text-gray-600 dark:text-gray-400">
          Access your email from any web browser at:
          <a :href="`https://${config.hostname}/mail`" target="_blank" class="font-medium underline">
            https://{{ config.hostname }}/mail
          </a>
        </p>
        <p class="text-sm text-gray-500 mt-1">Your username is your full email address.</p>
      </Card>

      <!-- Mobile & Desktop -->
      <Card class="p-5">
        <p class="text-2xl mb-3">📱</p>
        <h2 class="text-base font-semibold mb-2">Mobile &amp; Desktop Apps</h2>
        <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">
          <strong>Automatic setup (iOS/macOS only):</strong>
          <a :href="`https://${config.hostname}/mailinabox.mobileconfig`" class="underline ml-1">
            Configuration profile
          </a>
        </p>
        <p class="text-sm font-medium mb-2">Manual IMAP/SMTP settings:</p>
        <table class="w-full text-sm border-collapse">
          <tbody>
            <tr v-for="[label, value] in [
              ['Protocol', 'IMAP'],
              ['Mail server', config.hostname],
              ['IMAP Port', '993'],
              ['IMAP Security', 'SSL or TLS'],
              ['SMTP Port', '465'],
              ['SMTP Security', 'SSL or TLS'],
              ['Username', 'Your full email address'],
              ['Password', 'Your mail password'],
            ]" :key="label" class="border-b border-gray-100 dark:border-gray-800 last:border-0">
              <td class="py-1.5 pr-3 text-gray-500 whitespace-nowrap">{{ label }}</td>
              <td class="py-1.5 font-medium">{{ value }}</td>
            </tr>
          </tbody>
        </table>
        <p class="text-xs text-gray-400 mt-2">POP is also available on port 995 with SSL/TLS. IMAP is recommended.</p>
      </Card>

      <!-- Exchange / ActiveSync -->
      <Card class="p-5">
        <p class="text-2xl mb-3">🔄</p>
        <h2 class="text-base font-semibold mb-2">Exchange / ActiveSync</h2>
        <p class="text-sm text-gray-600 dark:text-gray-400 mb-2">
          Compatible with iOS devices and Outlook 2007+ on Windows 7+. IMAP is generally more reliable.
        </p>
        <table class="w-full text-sm border-collapse">
          <tbody>
            <tr class="border-b border-gray-100 dark:border-gray-800">
              <td class="py-1.5 pr-3 text-gray-500">Server</td>
              <td class="py-1.5 font-medium">{{ config.hostname }}</td>
            </tr>
            <tr>
              <td class="py-1.5 pr-3 text-gray-500">Options</td>
              <td class="py-1.5 font-medium">Secure Connection</td>
            </tr>
          </tbody>
        </table>
        <p class="text-xs text-gray-400 mt-2">Push email sync is supported on compatible devices.</p>
      </Card>

      <!-- Other info -->
      <Card class="p-5">
        <p class="text-2xl mb-3">ℹ️</p>
        <h2 class="text-base font-semibold mb-2">Other Mail Information</h2>
        <div class="space-y-2 text-sm text-gray-600 dark:text-gray-400">
          <p>
            <strong class="text-gray-700 dark:text-gray-300">Greylisting:</strong>
            Reduces spam by delaying first-time messages from new senders by at least 3 minutes.
          </p>
          <p>
            <strong class="text-gray-700 dark:text-gray-300">+tag addresses:</strong>
            Mail sent to <code class="text-xs bg-gray-100 dark:bg-gray-800 px-1 rounded">you+anything@yourdomain.com</code>
            is delivered to your inbox automatically.
          </p>
          <p>
            <strong class="text-gray-700 dark:text-gray-300">Outbound policy:</strong>
            Only this box can send mail on behalf of your domains, preventing spoofing.
          </p>
        </div>
      </Card>

    </div>
  </AppLayout>
</template>
