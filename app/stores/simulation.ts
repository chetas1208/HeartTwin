import { defineStore } from 'pinia'
import type { OperatingEnvironment, RecoveryConfig } from '~/types/heart'

const DEFAULT_OPERATING: OperatingEnvironment = {
  mode: 'rest',
  simulation_duration_seconds: 60,
  time_step_ms: 5,
  activity_level_mets: 1.0,
  hydration_index: 1.0,
  sleep_recovery_index: 1.0,
  stress_catecholamine_index: 1.0,
  ambient_temperature_c: 22.0,
  altitude_m: 0,
  oxygen_fraction: 0.21,
  medication_effect_profile: null,
  data_uncertainty_policy: 'moderate',
  missing_value_policy: 'prior',
}

const DEFAULT_RECOVERY: RecoveryConfig = {
  recovery_horizon_days: 30,
  scenario_type: 'load_reduction',
  contractility_delta_per_day: 0.005,
  afterload_delta_per_day: -0.005,
  preload_delta_per_day: -0.003,
  inflammation_decay_rate: 0.03,
  oxygen_delivery_delta_per_day: 0.003,
  stiffness_delta_per_day: -0.002,
  scar_remodeling_rate: 0.001,
  heart_rate_adaptation_rate: 0.002,
  arrhythmia_stability_delta: 0.005,
  max_safe_parameter_shift: 0.30,
  uncertainty_penalty_weight: 0.2,
  target_metric: 'balanced',
}

export const useSimulationStore = defineStore('simulation', {
  state: () => ({
    operating: { ...DEFAULT_OPERATING } as OperatingEnvironment,
    recovery: { ...DEFAULT_RECOVERY } as RecoveryConfig,
    selectedScenarioIndex: 0,
    animationSpeed: 1.0,
    showDamageZone: true,
    showBloodFlow: true,
    showElectricalOverlay: true,
    colorMode: 'cardiac' as 'cardiac' | 'oxygen' | 'pressure',
  }),

  actions: {
    setOperatingMode(mode: OperatingEnvironment['mode']) {
      this.operating.mode = mode
    },

    updateOperating(patch: Partial<OperatingEnvironment>) {
      Object.assign(this.operating, patch)
    },

    updateRecovery(patch: Partial<RecoveryConfig>) {
      Object.assign(this.recovery, patch)
    },

    setSelectedScenario(idx: number) {
      this.selectedScenarioIndex = idx
    },

    resetToDefaults() {
      this.operating = { ...DEFAULT_OPERATING }
      this.recovery = { ...DEFAULT_RECOVERY }
    },
  },
})
