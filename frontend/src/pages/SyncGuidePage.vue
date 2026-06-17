<script setup lang="ts">
import AppLayout from '@/components/layout/AppLayout.vue'
import Card from '@/components/ui/Card.vue'
import Code from '@/components/ui/Code.vue'
import Table from '@/components/ui/Table.vue'
import TableRow from '@/components/ui/TableRow.vue'
import { useConfigStore } from '@/stores/config'

const config = useConfigStore()

type SettingRow = [string, string]

const imapRows: SettingRow[] = [
  ['IMAP server', config.hostname],
  ['IMAP port', '993 (SSL/TLS)'],
  ['SMTP server', config.hostname],
  ['SMTP port', '587 (STARTTLS)'],
  ['Username', 'Your full email address'],
  ['Password', 'Your mail password'],
]

const caldavRows: SettingRow[] = [
  ['Server URL', `https://${config.hostname}/radicale/`],
  ['Username', 'Your full email address'],
  ['Password', 'Your mail password'],
]
</script>

<template>
  <AppLayout>
    <h1 class="text-2xl font-semibold mb-6">Sync to Devices</h1>

    <!-- IMAP / SMTP -->
    <h2 class="text-base font-semibold mb-3">Email (IMAP / SMTP)</h2>
    <Card class="p-5 mb-6">
      <p class="text-sm text-gray-500 mb-3">
        Configure any mail client using these settings. Autoconfig and autodiscover are
        supported - most clients can configure themselves with just your email address and password.
      </p>
      <Table>
        <tbody>
          <TableRow v-for="[label, value] in imapRows" :key="label">
            <th scope="row" class="px-4 py-2.5 text-sm text-gray-500 font-normal text-left w-48">{{ label }}</th>
            <td class="px-4 py-2.5 text-sm font-medium font-mono">{{ value }}</td>
          </TableRow>
        </tbody>
      </Table>
    </Card>

    <!-- CalDAV / CardDAV -->
    <h2 class="text-base font-semibold mb-3">Contacts &amp; Calendar (CalDAV / CardDAV)</h2>
    <Card class="p-5 mb-6">
      <p class="text-sm text-gray-500 mb-3">
        Contacts and calendars are served by <a href="https://radicale.org/" target="_blank" rel="noopener" class="underline underline-offset-2">Radicale</a>.
        Use these settings in iOS, Android, Thunderbird, or any CalDAV/CardDAV client.
        Clients that support <Code>.well-known</Code> autodiscovery
        only need the server URL and credentials.
      </p>
      <Table>
        <tbody>
          <TableRow v-for="[label, value] in caldavRows" :key="label">
            <th scope="row" class="px-4 py-2.5 text-sm text-gray-500 font-normal text-left w-48">{{ label }}</th>
            <td class="px-4 py-2.5 text-sm font-medium font-mono">{{ value }}</td>
          </TableRow>
        </tbody>
      </Table>
      <p class="text-xs text-gray-500 mt-3 px-1">
        CalDAV and CardDAV autodiscovery is configured via
        <Code>/.well-known/caldav</Code> and
        <Code>/.well-known/carddav</Code>.
        Enter just <span class="font-mono">{{ config.hostname }}</span> as the server in clients that support it.
      </p>
    </Card>

    <!-- Autodiscover -->
    <h2 class="text-base font-semibold mb-3">Autodiscover</h2>
    <Card class="p-5 mb-6">
      <p class="text-sm text-gray-500 mb-3">
        Outlook, iOS, and most modern mail clients can configure themselves automatically.
        Enter your email address and password - no manual server settings needed.
      </p>
      <div class="space-y-1">
        <div>
          <span class="text-xs text-gray-400 uppercase tracking-wide">Outlook (autodiscover)</span>
          <div>
            <a
              :href="`https://${config.hostname}/autodiscover/autodiscover.xml`"
              target="_blank"
              rel="noopener"
              class="text-sm font-medium underline underline-offset-2 font-mono"
            >https://{{ config.hostname }}/autodiscover/autodiscover.xml</a>
          </div>
        </div>
        <div class="pt-1">
          <span class="text-xs text-gray-400 uppercase tracking-wide">Thunderbird (autoconfig)</span>
          <div>
            <a
              :href="`https://${config.hostname}/.well-known/autoconfig/mail/config-v1.1.xml`"
              target="_blank"
              rel="noopener"
              class="text-sm font-medium underline underline-offset-2 font-mono"
            >https://{{ config.hostname }}/.well-known/autoconfig/mail/config-v1.1.xml</a>
          </div>
        </div>
      </div>
    </Card>

    <!-- Webmail -->
    <h2 class="text-base font-semibold mb-3">Webmail</h2>
    <Card class="p-5">
      <p class="text-sm text-gray-500 mb-3">
        Access your email from a browser without installing a client.
      </p>
      <a
        :href="`https://${config.hostname}/mail`"
        target="_blank"
        rel="noopener"
        class="text-sm font-medium underline underline-offset-2"
      >
        https://{{ config.hostname }}/mail
      </a>
    </Card>
  </AppLayout>
</template>
