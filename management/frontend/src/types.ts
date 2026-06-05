import type { Component } from 'vue'

/** Bootstrap data injected by Flask into the __INIT__ script tag on page load. */
type InitData = {
  hostname: string
  noUsersExist: boolean
  noAdminsExist: boolean
  backupS3Hosts: [string, string][]
  csrCountryCodes: [string, string][]
}

/** JSON response from POST /admin/login. */
type LoginApiResponse = {
  status: 'ok' | 'missing-totp-token' | 'invalid'
  /** The user's email address (present on ok). */
  email?: string
  /** User privilege list, e.g. ["admin"] (present on ok). */
  privileges?: string[]
  /** Session key used as Basic Auth password for subsequent requests (present on ok). */
  api_key?: string
  /** Human-readable failure reason (present on invalid / missing-totp-token). */
  reason?: string
}

/** JSON response from GET /admin/auth/methods. */
type AuthMethodsResponse = {
  paths: ('passkey' | 'password+totp' | 'password')[]
}

/** A single navigation link in the sidebar. */
type NavItem = {
  label: string
  path: string
  icon: Component
}

/** A labeled group of navigation links in the sidebar. */
type NavGroup = {
  label: string
  items: NavItem[]
}

// ---------------------------------------------------------------------------
// Mail users — GET /admin/mail/users?format=json
// ---------------------------------------------------------------------------

/** A single mail user account. */
type MailUser = {
  email: string
  privileges: string[]
  status: 'active' | 'inactive'
  quota: string
  box_size: string
  box_quota: number | string
  percent: string
  mailbox: string
}

/** One domain's worth of users as returned by the API. */
type MailUserDomain = {
  domain: string
  users: MailUser[]
}

// ---------------------------------------------------------------------------
// Mail aliases — GET /admin/mail/aliases?format=json
// ---------------------------------------------------------------------------

/** A single mail alias. */
type MailAlias = {
  address: string
  address_display: string
  forwards_to: string[]
  permitted_senders: string[] | null
  auto: boolean
}

/** One domain's worth of aliases as returned by the API. */
type MailAliasDomain = {
  domain: string
  aliases: MailAlias[]
}

// ---------------------------------------------------------------------------
// DNS — GET /admin/dns/custom
// ---------------------------------------------------------------------------

/** A custom DNS record. */
type DnsRecord = {
  qname: string
  rtype: string
  value: string
  'sort-order': { created: number; qname: number }
  zone?: string
}

/** A recommended external DNS record from GET /admin/dns/dump. */
type ExternalDnsEntry = {
  qname: string
  rtype: string
  value: string
  explanation: string
}

// ---------------------------------------------------------------------------
// System status — POST /admin/system/status
// ---------------------------------------------------------------------------

/** A single line in the system status output. */
type StatusCheckItem = {
  type: 'heading' | 'ok' | 'error' | 'warning'
  text: string
  extra: { text: string; monospace: boolean }[]
}

// ---------------------------------------------------------------------------
// SSL / TLS — GET /admin/ssl/status
// ---------------------------------------------------------------------------

/** TLS certificate status for one domain. */
type SslDomainStatus = {
  domain: string
  status: 'success' | 'error' | 'warning' | 'not-applicable'
  text: string
}

/** Full response from GET /admin/ssl/status. */
type SslStatus = {
  can_provision: string[]
  status: SslDomainStatus[]
}

// ---------------------------------------------------------------------------
// Backup — GET /admin/system/backup/status and /config
// ---------------------------------------------------------------------------

/** One backup entry in the backup history list. */
type BackupEntry = {
  date: string
  label: string
  size: number
  full: boolean
}

/** Response from GET /admin/system/backup/status. */
type BackupStatus = {
  target: string
  target_type: string
  min_age_days: number
  backups: BackupEntry[] | null
  error: string | null
}

/** Response from GET /admin/system/backup/config. */
type BackupConfig = {
  target: string
  target_user: string
  target_pass: string
  min_age: string
  enc_pw_file?: string
}

// ---------------------------------------------------------------------------
// MFA — POST /admin/mfa/status
// ---------------------------------------------------------------------------

/** An enabled MFA entry for a user. */
type MfaEntry = {
  id: number
  type: 'totp' | 'webauthn'
  label?: string
  name?: string
  last_used?: string | null
}

/** A provisioned TOTP setup (for enrollment). */
type TotpProvision = {
  type: 'totp'
  secret: string
  qr_code_base64: string
}

/** Response from POST /admin/mfa/status. */
type MfaStatus = {
  enabled_mfa: MfaEntry[]
  new_mfa?: { totp: TotpProvision }
}

// ---------------------------------------------------------------------------
// Web hosting — GET /admin/web/domains
// ---------------------------------------------------------------------------

/** A web domain entry. */
type WebDomain = {
  domain: string
  root: string
  custom_root: string
  static_enabled: boolean
}

export type {
  InitData, LoginApiResponse, AuthMethodsResponse, NavItem, NavGroup,
  MailUser, MailUserDomain, MailAlias, MailAliasDomain,
  DnsRecord, ExternalDnsEntry,
  StatusCheckItem,
  SslDomainStatus, SslStatus,
  BackupEntry, BackupStatus, BackupConfig,
  MfaEntry, TotpProvision, MfaStatus,
  WebDomain,
}
