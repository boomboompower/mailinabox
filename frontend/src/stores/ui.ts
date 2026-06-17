import { ref } from 'vue'
import { defineStore } from 'pinia'

type Theme = 'light' | 'dark' | 'system'

function applyTheme(theme: Theme): void {
  if (theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(localStorage.getItem('sidebar_collapsed') === 'true')
  const mobileSidebarOpen = ref(false)
  const theme = ref<Theme>((localStorage.getItem('theme') as Theme) ?? 'system')

  applyTheme(theme.value)

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('sidebar_collapsed', String(sidebarCollapsed.value))
  }

  function setTheme(t: Theme): void {
    theme.value = t
    localStorage.setItem('theme', t)
    applyTheme(t)
  }

  function openMobileSidebar(): void {
    mobileSidebarOpen.value = true
  }

  function closeMobileSidebar(): void {
    mobileSidebarOpen.value = false
  }

  return { sidebarCollapsed, mobileSidebarOpen, theme, toggleSidebar, setTheme, openMobileSidebar, closeMobileSidebar }
})
