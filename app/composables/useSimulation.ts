import { useCaseStore } from '~/stores/case'

export function useSimulation() {
  const caseStore = useCaseStore()

  async function runExtract(fileIds: string[] = [], userVitals: Record<string, unknown> = {}) {
    if (!caseStore.caseId) throw new Error('No case ID')
    await caseStore.extract(fileIds, userVitals)
  }

  async function runOperate(env?: Record<string, unknown>) {
    if (!caseStore.caseId) throw new Error('No case ID')
    await caseStore.operate(env as unknown as import('~/types/heart').OperatingEnvironment)
  }

  async function runRecovery() {
    if (!caseStore.caseId) throw new Error('No case ID')
    await caseStore.simulateRecovery()
  }

  return { runExtract, runOperate, runRecovery }
}
