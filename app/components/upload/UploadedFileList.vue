<template>
  <div v-if="files.length" class="space-y-2">
    <p class="section-title">Uploaded Files ({{ files.length }})</p>
    <div v-for="file in files" :key="file.file_id" class="flex items-center gap-3 p-2.5 glass-card rounded-lg">
      <div :class="['w-8 h-8 rounded flex items-center justify-center shrink-0 text-xs font-mono font-bold', fileIconClass(file.content_type)]">
        {{ fileExt(file.filename) }}
      </div>
      <div class="flex-1 min-w-0">
        <p class="text-sm text-white truncate">{{ file.filename }}</p>
        <p class="text-xs text-cardiac-muted">{{ formatFileSize(file.size_bytes) }}</p>
      </div>
      <div class="w-2 h-2 rounded-full bg-green-400 shrink-0" title="Uploaded" />
    </div>
  </div>
  <div v-else class="text-center py-4 text-sm text-cardiac-muted">
    No files uploaded yet
  </div>
</template>

<script setup lang="ts">
import type { UploadedFile } from '~/types/api'
import { formatFileSize } from '~/utils/formatters'

defineProps<{
  files: UploadedFile[]
}>()

function fileExt(filename: string): string {
  return filename.split('.').pop()?.toUpperCase().slice(0, 3) || 'FILE'
}

function fileIconClass(contentType: string): string {
  if (contentType === 'application/pdf') return 'bg-red-900/50 text-red-400'
  if (contentType.startsWith('image/')) return 'bg-blue-900/50 text-blue-400'
  if (contentType === 'text/csv') return 'bg-green-900/50 text-green-400'
  return 'bg-cardiac-navy-border text-cardiac-muted'
}
</script>

<style scoped>
.section-title {
  color: rgba(142, 160, 184, 0.72);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.7rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.glass-card {
  background:
    linear-gradient(135deg, rgba(14, 28, 48, 0.82), rgba(7, 17, 31, 0.66));
  border: 1px solid var(--ht-border);
  border-radius: var(--ht-radius-sm);
}
</style>
