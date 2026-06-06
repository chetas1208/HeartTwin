import { ref } from 'vue'
import { useCaseStore } from '~/stores/case'
import { useHeartTwinApi } from './useHeartTwinApi'

export function useFileUpload() {
  const api = useHeartTwinApi()
  const caseStore = useCaseStore()

  const uploading = ref(false)
  const uploadProgress = ref<Record<string, 'pending' | 'uploading' | 'done' | 'error'>>({})

  const ACCEPTED_TYPES = [
    'application/pdf',
    'image/jpeg', 'image/jpg', 'image/png', 'image/tiff',
    'text/csv', 'text/plain', 'application/json',
  ]

  function validateFile(file: File): string | null {
    if (!ACCEPTED_TYPES.includes(file.type) && !file.type.startsWith('image/')) {
      return `${file.name}: unsupported type (${file.type})`
    }
    if (file.size > 50 * 1024 * 1024) {
      return `${file.name}: too large (max 50 MB)`
    }
    return null
  }

  async function uploadFiles(caseId: string, files: File[]): Promise<string[]> {
    const uploadedIds: string[] = []
    uploading.value = true

    for (const file of files) {
      const err = validateFile(file)
      if (err) {
        console.warn('[upload]', err)
        continue
      }

      uploadProgress.value[file.name] = 'uploading'
      try {
        const result = await api.uploadFile(caseId, file)
        uploadProgress.value[file.name] = 'done'
        uploadedIds.push(result.file_id)
        caseStore.addFile({
          file_id: result.file_id,
          filename: file.name,
          content_type: file.type,
          size_bytes: file.size,
          storage_url: result.storage_url ?? null,
          uploaded_at: new Date().toISOString(),
        })
      } catch (e) {
        uploadProgress.value[file.name] = 'error'
        console.error('[upload] failed:', file.name, e)
      }
    }

    uploading.value = false
    return uploadedIds
  }

  return { uploading, uploadProgress, uploadFiles, validateFile, ACCEPTED_TYPES }
}
