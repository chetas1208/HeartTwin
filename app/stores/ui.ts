import { defineStore } from 'pinia'

export type LabTab = 'overview' | 'files' | 'state' | 'operation' | 'recovery' | 'trace' | 'safety'

export const useUiStore = defineStore('ui', {
  state: () => ({
    sidebarOpen: true,
    activeLabTab: 'overview' as LabTab,
    toasts: [] as { id: string; type: 'info' | 'success' | 'warning' | 'error'; message: string }[],
    disclaimerDismissed: false,
    traceExpanded: false,
  }),

  actions: {
    toggleSidebar() {
      this.sidebarOpen = !this.sidebarOpen
    },

    setActiveTab(tab: LabTab) {
      this.activeLabTab = tab
    },

    toast(type: 'info' | 'success' | 'warning' | 'error', message: string) {
      const id = crypto.randomUUID()
      this.toasts.push({ id, type, message })
      setTimeout(() => {
        this.toasts = this.toasts.filter((t) => t.id !== id)
      }, 5000)
    },

    dismissDisclaimer() {
      this.disclaimerDismissed = true
    },

    toggleTrace() {
      this.traceExpanded = !this.traceExpanded
    },
  },
})
