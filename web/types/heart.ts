// Canonical TypeScript types for HeartTwin Lab.
// These mirror the Python Pydantic schemas in python/hearttwin/schemas.py.

export type ValueSource = 'file_extraction' | 'user_input' | 'default_model_prior' | 'derived'

export interface MeasuredValue {
  value: number
  unit: string
  source: ValueSource
  confidence: number
  source_file_id?: string | null
  method?: string | null
  evidence?: string | null
}

export interface PatientContext {
  age_years?: MeasuredValue | null
  sex?: string | null
  height_cm?: MeasuredValue | null
  weight_kg?: MeasuredValue | null
  bsa_m2?: MeasuredValue | null
  notes?: string | null
}

export interface Measurements {
  heart_rate_bpm?: MeasuredValue | null
  systolic_bp_mmhg?: MeasuredValue | null
  diastolic_bp_mmhg?: MeasuredValue | null
  edv_ml?: MeasuredValue | null
  esv_ml?: MeasuredValue | null
  ejection_fraction_pct?: MeasuredValue | null
  stroke_volume_ml?: MeasuredValue | null
  cardiac_output_l_min?: MeasuredValue | null
  troponin_ng_l?: MeasuredValue | null
  bnp_pg_ml?: MeasuredValue | null
  oxygen_saturation_pct?: MeasuredValue | null
}

export interface Electrophysiology {
  rhythm_label?: string | null
  rr_interval_ms?: MeasuredValue | null
  qrs_duration_ms?: MeasuredValue | null
  qt_interval_ms?: MeasuredValue | null
  qtc_ms?: MeasuredValue | null
  r_peak_confidence?: number | null
  conduction_delay_score?: MeasuredValue | null
  arrhythmia_instability_score?: MeasuredValue | null
}

export interface Hemodynamics {
  preload_index?: MeasuredValue | null
  afterload_index?: MeasuredValue | null
  contractility_index?: MeasuredValue | null
  arterial_compliance_index?: MeasuredValue | null
  systemic_vascular_resistance_index?: MeasuredValue | null
  filling_pressure_index?: MeasuredValue | null
  pv_loop_area_index?: MeasuredValue | null
}

export interface TissueState {
  scar_fraction?: MeasuredValue | null
  inflammation_index?: MeasuredValue | null
  oxygen_delivery_index?: MeasuredValue | null
  myocardial_oxygen_demand_index?: MeasuredValue | null
  stiffness_index?: MeasuredValue | null
  remodeling_index?: MeasuredValue | null
  damage_zone_location?: string | null
}

export type OperatingMode = 'rest' | 'mild_activity' | 'stress' | 'recovery'
export type DataUncertaintyPolicy = 'conservative' | 'moderate' | 'optimistic'
export type MissingValuePolicy = 'null' | 'prior' | 'refuse'

export interface OperatingEnvironment {
  mode: OperatingMode
  simulation_duration_seconds: number
  time_step_ms: number
  activity_level_mets: number
  hydration_index: number
  sleep_recovery_index: number
  stress_catecholamine_index: number
  ambient_temperature_c: number
  altitude_m: number
  oxygen_fraction: number
  medication_effect_profile?: Record<string, number> | null
  data_uncertainty_policy: DataUncertaintyPolicy
  missing_value_policy: MissingValuePolicy
}

export type RecoveryScenarioType =
  | 'load_reduction'
  | 'oxygen_delivery_improvement'
  | 'contractility_support'
  | 'conditioning'
  | 'stability_monitoring'
  | 'custom'

export type TargetMetric = 'cardiac_output' | 'ef' | 'pv_loop_efficiency' | 'stability' | 'balanced'

export interface RecoveryConfig {
  recovery_horizon_days: number
  scenario_type: RecoveryScenarioType
  contractility_delta_per_day: number
  afterload_delta_per_day: number
  preload_delta_per_day: number
  inflammation_decay_rate: number
  oxygen_delivery_delta_per_day: number
  stiffness_delta_per_day: number
  scar_remodeling_rate: number
  heart_rate_adaptation_rate: number
  arrhythmia_stability_delta: number
  max_safe_parameter_shift: number
  uncertainty_penalty_weight: number
  target_metric: TargetMetric
}

export interface SimulationConfig {
  operating: OperatingEnvironment
  recovery: RecoveryConfig
  random_seed: number
}

export interface SourceMapEntry {
  field: string
  value?: number | null
  unit: string
  source: ValueSource
  source_file_id?: string | null
  confidence: number
  method?: string | null
  evidence?: string | null
}

export type SafetyLevel = 'clear' | 'caution' | 'blocked'

export interface CardiacTwinState {
  case_id: string
  created_at: string
  data_quality_score: number
  safety_level: SafetyLevel
  patient_context: PatientContext
  measurements: Measurements
  electrophysiology: Electrophysiology
  hemodynamics: Hemodynamics
  tissue_state: TissueState
  operating_environment: OperatingEnvironment
  simulation_config: SimulationConfig
  source_map: SourceMapEntry[]
  warnings: string[]
}

export interface PVLoopData {
  volumes_ml: number[]
  pressures_mmhg: number[]
  pv_loop_area_mmhg_ml: number
  stroke_work_j: number
  peak_pressure_mmhg: number
  edp_mmhg: number
}

export interface CardiacCycleData {
  time_ms: number[]
  lv_volume_ml: number[]
  lv_pressure_mmhg: number[]
  aortic_flow_ml_s: number[]
  heart_rate_bpm: number
  cycle_duration_ms: number
}

export interface SimulationVisualization {
  cardiac_cycle: CardiacCycleData
  pv_loop: PVLoopData
  summary: {
    edv_ml: number
    esv_ml: number
    stroke_volume_ml: number
    ef_pct: number
    cardiac_output_l_min: number
    heart_rate_bpm: number
    map_mmhg: number
    operating_mode: OperatingMode
  }
  hemodynamics: Record<string, number>
  electrophysiology: {
    rhythm_label?: string | null
    rr_interval_ms?: number | null
    qrs_duration_ms?: number | null
    qtc_ms?: number | null
    arrhythmia_instability_score?: number | null
    r_peak_confidence?: number | null
  }
  simulation_note: string
}

export interface RecoveryDay {
  day: number
  ef_pct: number
  cardiac_output_l_min: number
  stroke_volume_ml: number
  heart_rate_bpm: number
  contractility_index: number
  inflammation_index: number
  oxygen_delivery_index: number
  uncertainty_low: number
  uncertainty_high: number
}

export interface RecoveryScenario {
  scenario_type: RecoveryScenarioType
  scenario_label: string
  summary_metrics: {
    initial_ef_pct: number
    final_ef_pct: number
    ef_delta_pct: number
    initial_co_l_min: number
    final_co_l_min: number
    co_delta_l_min: number
    final_inflammation_index: number
    final_arrhythmia_instability: number
    horizon_days: number
  }
  trajectory: RecoveryDay[]
  warnings: string[]
  simulation_disclaimer: string
  simulation_note: string
}
