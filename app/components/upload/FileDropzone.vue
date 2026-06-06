<template>
  <div
    :class="[
      'file-dropzone relative border-2 border-dashed rounded-xl p-6 text-center transition-all duration-200 cursor-pointer',
      isDragging
        ? 'border-cardiac-red/70 bg-cardiac-red/10'
        : 'border-cardiac-navy-border hover:border-cardiac-red/40 hover:bg-cardiac-red/5',
    ]"
    @dragover.prevent="isDragging = true"
    @dragleave="isDragging = false"
    @drop.prevent="onDrop"
    @click="openPicker"
  >
    <input
      ref="inputRef"
      type="file"
      class="hidden"
      multiple
      accept=".pdf,.jpg,.jpeg,.png,.tiff,.tif,.csv"
      @change="onInputChange"
    >

    <div class="flex flex-col items-center gap-3">
      <div :class="['w-12 h-12 rounded-full flex items-center justify-center transition-colors', isDragging ? 'bg-cardiac-red/20' : 'bg-cardiac-navy-border']">
        <svg class="w-6 h-6 text-cardiac-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
        </svg>
      </div>

      <div>
        <p class="text-sm font-medium text-white">
          {{ isDragging ? 'Drop files here' : 'Upload cardiac data' }}
        </p>
        <p class="text-xs text-cardiac-muted mt-1">
          PDF reports, ECG images (JPG/PNG), CSV waveforms
        </p>
      </div>

      <div class="flex flex-wrap gap-1 justify-center">
        <span v-for="t in ['PDF', 'JPG', 'PNG', 'TIFF', 'CSV']" :key="t" class="px-2 py-0.5 rounded text-xs bg-cardiac-navy-border text-cardiac-muted font-mono">
          {{ t }}
        </span>
      </div>
    </div>

    <div v-if="uploading" class="absolute inset-0 bg-cardiac-navy/80 rounded-xl flex items-center justify-center">
      <div class="flex items-center gap-2 text-sm text-cardiac-electric">
        <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        Uploading...
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  files: [files: File[]]
}>()

defineProps<{
  uploading?: boolean
}>()

const isDragging = ref(false)
const inputRef = ref<HTMLInputElement>()

function openPicker() {
  inputRef.value?.click()
}

function onDrop(e: DragEvent) {
  isDragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length) emit('files', files)
}

function onInputChange(e: Event) {
  const files = Array.from((e.target as HTMLInputElement).files || [])
  if (files.length) emit('files', files)
  ;(e.target as HTMLInputElement).value = ''
}
</script>

<style scoped>
.file-dropzone {
  background:
    radial-gradient(circle at 50% 0%, rgba(56, 189, 248, 0.08), transparent 12rem),
    rgba(10, 20, 35, 0.52);
  border-color: rgba(148, 163, 184, 0.22);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
}

.file-dropzone:hover {
  background:
    radial-gradient(circle at 50% 0%, rgba(255, 54, 95, 0.08), transparent 12rem),
    rgba(10, 20, 35, 0.64);
  border-color: rgba(255, 54, 95, 0.40);
}

.file-dropzone:focus-within {
  border-color: var(--ht-blue);
  box-shadow: var(--ht-shadow-glow-blue);
}

.file-dropzone span {
  border: 1px solid rgba(148, 163, 184, 0.14);
}

@media (prefers-reduced-motion: reduce) {
  .file-dropzone,
  .file-dropzone * {
    transition: none;
  }
}
</style>
