import type { Component } from 'vue'

/** The 6 available color palettes for the admin panel. */
export type Palette = 'zinc' | 'oxi' | 'indigo' | 'nord' | 'emerald' | 'catppuccin'

/**
 * Bootstrap data injected by Flask into the __INIT__ script tag on page load.
 * Auth-sensitive fields are only present when the admin_session cookie is valid.
 * hostname and needsBootstrap are always present.
 */
type InitData = {
  hostname: string
  authenticated: boolean
  /** True when no admin users exist. Always present. Triggers onboarding redirect. */
  needsBootstrap?: boolean
  /** Present when authenticated. */
  email?: string
  /** Present when authenticated. */
  privileges?: string[]
  /** Present when authenticated. */
  noUsersExist?: boolean
  /** Present when authenticated. */
  noAdminsExist?: boolean
  /** Present when authenticated. */
  backupS3Hosts?: [string, string][]
}

/** Response from POST /admin/bootstrap/setup. */
type BootstrapSetupResponse = {
  status: 'ok'
}

/** Error response from POST /admin/bootstrap/setup when the code is wrong. */
type BootstrapCodeError = {
  error: 'invalid_code' | 'expired' | 'locked' | 'not_found'
  /** Present when error is invalid_code. */
  attempts_remaining?: number
}

/** JSON response from POST /admin/login. */
type LoginApiResponse = {
  status: 'ok' | 'missing-totp-token' | 'invalid'
  /** The user's email address (present on ok). */
  email?: string
  /** User privilege list, e.g. ["admin"] (present on ok). */
  privileges?: string[]
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
  /** If true, only rendered for admin users. */
  adminOnly?: boolean
}

/** A labeled group of navigation links in the sidebar. */
type NavGroup = {
  label: string
  items: NavItem[]
}

// ---------------------------------------------------------------------------
// Mail users - GET /admin/mail/users?format=json
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
// Mail aliases - GET /admin/mail/aliases?format=json
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
// DNS - GET /admin/dns/custom
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
// System status - GET /admin/system/status (instant) + POST (trigger fresh run)
// ---------------------------------------------------------------------------

/** A single line in the system status output. */
type StatusCheckItem = {
  type: 'heading' | 'ok' | 'error' | 'warning'
  /** Humanized label (check name ± [domain]). */
  text: string
  /** Primary error/warning message shown inline below the label. Empty for ok items. */
  detail?: string
  /** Additional step details shown in the expandable section. */
  extra: { text: string; monospace: boolean }[]
}

/**
 * Response envelope from GET /admin/system/status and POST /admin/system/status.
 * GET is always instant (returns cached state). POST triggers a fresh run or
 * returns the running state if one is already in progress (HTTP 202).
 */
type StatusCheckResponse = {
  /** idle = no cache yet; running = check in progress; done = results available. */
  status: 'idle' | 'running' | 'done'
  /** Last known results - present even while running so UI can show stale data. */
  items: StatusCheckItem[] | null
  /** ISO 8601 timestamp of when the cached result was produced. */
  checked_at: string | null
  /** Whether the cached result came from the nightly cron or a manual refresh. */
  source: 'cron' | 'manual' | null
}

// ---------------------------------------------------------------------------
// SSL / TLS - GET /admin/ssl/status
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
// Backup - GET /admin/system/backup/status and /config
// ---------------------------------------------------------------------------

/** One backup entry in the backup history list. */
type BackupEntry = {
  /** ISO 8601 timestamp. */
  date: string
  /** Human-readable date with timezone (e.g. "2026-06-05 14:23:47 AEST"). */
  date_str: string
  /** Human-readable age (e.g. "3 days, 2 hours"). */
  date_delta: string
  /** True for a full backup, false for an incremental. Always true for restic. */
  full: boolean
  /** Restore size in bytes. For restic: total bytes that would be restored from this snapshot (from backup summary cache). For duplicity: archive file size. */
  size: number
  /** Number of archive volumes (duplicity only - always 0 for restic). */
  volumes: number
  /** Human-readable time until deletion. */
  deleted_in?: string
  /** Snapshot ID (restic only). Use this when restoring, not the date. */
  id?: string
  /** Bytes of new data added to the repository by this snapshot (restic only - from backup summary cache). */
  data_added?: number
  /** Number of files in this snapshot (restic only - from backup summary cache). */
  file_count?: number
}

/**
 * Response from GET /admin/system/backup/status.
 * Returns {} when backups are off, {"error": ...} on failure,
 * or {"backend": ..., "backups": [...], "unmatched_file_size": N} when enabled.
 */
/** Result of the post-backup integrity check (restic only). */
type BackupCheckResult = {
  passed: boolean
  /** ISO 8601 timestamp of when the check ran. */
  timestamp: string
  /** restic check output - only populated when passed is false. */
  output: string
}

type BackupStatus = {
  /** Which backup backend produced this response. */
  backend?: 'restic' | 'duplicity'
  backups?: BackupEntry[]
  unmatched_file_size?: number
  error?: string
  /** Result of the most recent post-backup integrity check (restic only). */
  last_check?: BackupCheckResult
}

/**
 * Response from GET /admin/system/backup/config (for_ui=True).
 * target_user and target_pass are omitted by the backend for security.
 */
type BackupConfig = {
  /** Full target URL (e.g. "file://...", "rsync://...", "s3://...", "b2://...") or "off". */
  target: string
  /** Minimum backup age in days before deletion is allowed. */
  min_age_in_days: number
  /** Local path where encrypted backup files are stored. */
  file_target_directory: string
  /** Path to the encryption key file. */
  enc_pw_file: string
  /** SSH public key used for rsync access (present if key exists on disk). */
  ssh_pub_key?: string
  /** Whether to run an integrity check after each backup and email admin on failure. */
  check_after_backup: boolean
}

// ---------------------------------------------------------------------------
// SSL provision - POST /admin/ssl/provision
// ---------------------------------------------------------------------------

/** Result for a single domain group in a TLS provision run. */
type SslProvisionRequest = {
  domains: string[]
  result: 'installed' | 'error' | 'skipped'
  message?: string
  log: string[]
}

/** Response from POST /admin/ssl/provision. */
type SslProvisionResult = {
  requests: SslProvisionRequest[]
}

// ---------------------------------------------------------------------------
// MFA - POST /admin/mfa/status
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
// Web hosting - GET /admin/web/domains
// ---------------------------------------------------------------------------

/** A web domain entry. */
type WebDomain = {
  domain: string
  root: string
  custom_root: string
  static_enabled: boolean
}

// ---------------------------------------------------------------------------
// API tokens - GET /admin/tokens, POST /admin/tokens, DELETE /admin/tokens/:id
// ---------------------------------------------------------------------------

/** A single API token entry returned by GET /admin/tokens. The plaintext is never returned. */
type ApiToken = {
  /** Database id used to revoke the token. */
  id: number
  /** Human-readable label set at creation time. */
  name: string
  /** 'read' tokens can only call read-scope endpoints; 'write' tokens can call any endpoint. */
  scope: 'read' | 'write'
  /** ISO 8601 creation timestamp. */
  created_at: string
  /** ISO 8601 timestamp of last use, or null if never used. */
  last_used: string | null
}

/** Response from POST /admin/tokens. The plaintext is shown once and never stored. */
type ApiTokenCreateResponse = {
  token: string
}

// ---------------------------------------------------------------------------
// SMTP relay - GET /admin/system/relay
// ---------------------------------------------------------------------------

/** Response from GET /admin/system/relay. */
type SmtpRelayConfig = {
  /** SMTP relay hostname, or empty string when relay is disabled. */
  host: string
  /** SMTP port (typically 587). */
  port: number
  /** SMTP username. */
  user: string
  /** True if a password is stored on the server. The password itself is never returned. */
  password_set: boolean
  /** SPF include domain appended to the auto-generated SPF record (e.g. "sendgrid.net"). */
  spf_include: string
}

export type {
  InitData, LoginApiResponse, AuthMethodsResponse, BootstrapSetupResponse, BootstrapCodeError,
  NavItem, NavGroup,
  MailUser, MailUserDomain, MailAlias, MailAliasDomain,
  DnsRecord, ExternalDnsEntry,
  StatusCheckItem, StatusCheckResponse,
  SslDomainStatus, SslStatus, SslProvisionRequest, SslProvisionResult,
  BackupEntry, BackupStatus, BackupConfig, BackupCheckResult,
  MfaEntry, TotpProvision, MfaStatus,
  WebDomain,
  ApiToken, ApiTokenCreateResponse,
  SmtpRelayConfig,
}
