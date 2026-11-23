export type ProviderType = 'gmail' | 'outlook' | 'qq' | '163' | '126' | 'icloud' | 'school' | 'custom'
export type AuthType = 'password' | 'oauth2'
export type FolderType = 'inbox' | 'unread' | 'starred' | 'sent' | 'drafts' | 'archive' | 'spam' | 'trash'
export type CategoryType = 'all' | 'work' | 'study' | 'social' | 'subscription'
export type ThemeMode = 'light' | 'dark' | 'system'
export type MotionLevel = 'full' | 'gentle' | 'off'
export type FontSizeLevel = 'sm' | 'md' | 'lg'
export type ListDensityLevel = 'compact' | 'comfortable'

export interface ProviderPreset {
  id: ProviderType
  name: string
  domains: string[]
  imap_host: string
  imap_port: number
  imap_ssl: boolean
  smtp_host: string
  smtp_port: number
  smtp_ssl: boolean
  supports_oauth: boolean
  requires_imap_id: boolean
  badge_color: string
  auth_guide_url: string
  auth_guide_tip: string
}

export interface EmailAccount {
  id: number
  label: string
  email: string
  provider: ProviderType
  auth_type: AuthType
  imap_host: string
  imap_port: number
  imap_ssl: boolean
  smtp_host: string
  smtp_port: number
  smtp_ssl: boolean
  badge_color: string
  signature: string
  is_enabled: boolean
  include_in_unified: boolean
  notify_enabled: boolean
  sort_order: number
  last_synced_at: string | null
  sync_status: string
  last_error: string | null
  is_demo: boolean
  unread_count: number
  total_count: number
}

export interface AttachmentItem {
  id: number
  filename: string
  content_type: string
  size_bytes: number
}

export interface EmailSummary {
  id: number
  account_id: number
  account_label: string
  account_email: string
  account_color: string
  folder: string
  category: Exclude<CategoryType, 'all'>
  sender_name: string
  sender_email: string
  sender_avatar_key: string
  subject: string
  snippet: string
  is_read: boolean
  is_starred: boolean
  has_attachments: boolean
  received_at: string
}

export interface EmailDetail extends EmailSummary {
  message_id: string
  to_addresses: string[]
  cc_addresses: string[]
  bcc_addresses: string[]
  html_body: string
  text_body: string
  has_remote_images: boolean
  raw_headers: string
  attachments: AttachmentItem[]
}

export interface FolderCounts {
  inbox: number
  inbox_unread: number
  unread: number
  starred: number
  sent: number
  drafts: number
  archive: number
  spam: number
  trash: number
}

export interface EmailListResponse {
  items: EmailSummary[]
  total: number
  page: number
  page_size: number
  total_pages: number
  folder_counts: FolderCounts
}

export interface ClassificationRule {
  id: number
  name: string
  field: 'sender_email' | 'sender_name' | 'subject'
  pattern: string
  target_category: Exclude<CategoryType, 'all'>
  is_enabled: boolean
}

export interface AppSettings {
  theme_mode: ThemeMode
  show_mascots: boolean
  mascot_opacity: number
  custom_mascot_left: string | null
  custom_mascot_right: string | null
  show_particles: boolean
  motion_level: MotionLevel
  font_size: FontSizeLevel
  list_density: ListDensityLevel
  default_account_id: number | null
  smart_send_from: boolean
  undo_send_seconds: number
  sync_interval_minutes: number
  sync_days: number
  desktop_notifications: boolean
  block_remote_images: boolean
  oauth_google_client_id: string
  oauth_google_client_secret: string
  oauth_microsoft_client_id: string
}

export interface StorageInfo {
  db_size_bytes: number
  attachments_size_bytes: number
  attachments_count: number
  emails_count: number
  accounts_count: number
  demo_accounts_count: number
}

export interface SyncLogItem {
  id: number
  account_id: number | null
  status: string
  fetched_count: number
  message: string
  created_at: string
}
