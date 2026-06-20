import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { Palette } from '@/types'

type Theme = 'light' | 'dark' | 'system'

function applyTheme(theme: Theme): void {
  if (theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

function applyPalette(palette: Palette): void {
  if (palette === 'zinc') {
    document.documentElement.removeAttribute('data-palette')
  } else {
    document.documentElement.setAttribute('data-palette', palette)
  }
}

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(localStorage.getItem('sidebar_collapsed') === 'true')
  const mobileSidebarOpen = ref(false)
  const theme = ref<Theme>((localStorage.getItem('theme') as Theme) ?? 'system')
  const palette = ref<Palette>((localStorage.getItem('palette') as Palette) ?? 'zinc')

  applyTheme(theme.value)
  applyPalette(palette.value)

  // Keep system mode in sync when OS preference changes at runtime
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', () => {
    if (theme.value === 'system') applyTheme('system')
  })

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('sidebar_collapsed', String(sidebarCollapsed.value))
  }

  function setTheme(t: Theme): void {
    theme.value = t
    localStorage.setItem('theme', t)
    applyTheme(t)
  }

  function setPalette(p: Palette): void {
    palette.value = p
    localStorage.setItem('palette', p)
    applyPalette(p)
  }

  function openMobileSidebar(): void {
    mobileSidebarOpen.value = true
  }

  function closeMobileSidebar(): void {
    mobileSidebarOpen.value = false
  }

  return { sidebarCollapsed, mobileSidebarOpen, theme, palette, toggleSidebar, setTheme, setPalette, openMobileSidebar, closeMobileSidebar }
})
