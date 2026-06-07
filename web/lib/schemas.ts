import { z } from 'zod'

export const ValueSourceSchema = z.enum([
  'file_extraction',
  'user_input',
  'default_model_prior',
  'derived',
])

export const SafetyLevelSchema = z.enum(['clear', 'caution', 'blocked'])
export const AgentStatusSchema = z.enum(['success', 'warning', 'failed'])
export const OperatingModeSchema = z.enum(['rest', 'mild_activity', 'stress', 'recovery'])
export const DataUncertaintyPolicySchema = z.enum(['conservative', 'moderate', 'optimistic'])
export const MissingValuePolicySchema = z.enum(['null', 'prior', 'refuse'])

export const RecoveryScenarioTypeSchema = z.enum([
  'load_reduction',
  'oxygen_delivery_improvement',
  'contractility_support',
  'conditioning',
  'stability_monitoring',
  'custom',
])

export const TargetMetricSchema = z.enum([
  'cardiac_output',
  'ef',
  'pv_loop_efficiency',
  'stability',
  'balanced',
])

export const MeasuredValueSchema = z.object({
  value: z.number(),
  unit: z.string(),
  source: ValueSourceSchema,
  confidence: z.number().min(0).max(1),
  source_file_id: z.string().nullable().optional(),
  method: z.string().nullable().optional(),
  evidence: z.string().nullable().optional(),
})

export const PatientContextSchema = z.object({
  age_years: MeasuredValueSchema.nullable().optional(),
  sex: z.string().nullable().optional(),
  height_cm: MeasuredValueSchema.nullable().optional(),
  weight_kg: MeasuredValueSchema.nullable().optional(),
  bsa_m2: MeasuredValueSchema.nullable().optional(),
  notes: z.string().nullable().optional(),
})

export const MeasurementsSchema = z.object({
  heart_rate_bpm: MeasuredValueSchema.nullable().optional(),
  systolic_bp_mmhg: MeasuredValueSchema.nullable().optional(),
  diastolic_bp_mmhg: MeasuredValueSchema.nullable().optional(),
  edv_ml: MeasuredValueSchema.nullable().optional(),
  esv_ml: MeasuredValueSchema.nullable().optional(),
  ejection_fraction_pct: MeasuredValueSchema.nullable().optional(),
  stroke_volume_ml: MeasuredValueSchema.nullable().optional(),
  cardiac_output_l_min: MeasuredValueSchema.nullable().optional(),
  troponin_ng_l: MeasuredValueSchema.nullable().optional(),
  bnp_pg_ml: MeasuredValueSchema.nullable().optional(),
  oxygen_saturation_pct: MeasuredValueSchema.nullable().optional(),
})

export const ElectrophysiologySchema = z.object({
  rhythm_label: z.string().nullable().optional(),
  rr_interval_ms: MeasuredValueSchema.nullable().optional(),
  qrs_duration_ms: MeasuredValueSchema.nullable().optional(),
  qt_interval_ms: MeasuredValueSchema.nullable().optional(),
  qtc_ms: MeasuredValueSchema.nullable().optional(),
  r_peak_confidence: z.number().min(0).max(1).nullable().optional(),
  conduction_delay_score: MeasuredValueSchema.nullable().optional(),
  arrhythmia_instability_score: MeasuredValueSchema.nullable().optional(),
})

export const HemodynamicsSchema = z.object({
  preload_index: MeasuredValueSchema.nullable().optional(),
  afterload_index: MeasuredValueSchema.nullable().optional(),
  contractility_index: MeasuredValueSchema.nullable().optional(),
  arterial_compliance_index: MeasuredValueSchema.nullable().optional(),
  systemic_vascular_resistance_index: MeasuredValueSchema.nullable().optional(),
  filling_pressure_index: MeasuredValueSchema.nullable().optional(),
  pv_loop_area_index: MeasuredValueSchema.nullable().optional(),
})

export const TissueStateSchema = z.object({
  scar_fraction: MeasuredValueSchema.nullable().optional(),
  inflammation_index: MeasuredValueSchema.nullable().optional(),
  oxygen_delivery_index: MeasuredValueSchema.nullable().optional(),
  myocardial_oxygen_demand_index: MeasuredValueSchema.nullable().optional(),
  stiffness_index: MeasuredValueSchema.nullable().optional(),
  remodeling_index: MeasuredValueSchema.nullable().optional(),
  damage_zone_location: z.string().nullable().optional(),
})

export const OperatingEnvironmentSchema = z.object({
  mode: OperatingModeSchema,
  simulation_duration_seconds: z.number(),
  time_step_ms: z.number(),
  activity_level_mets: z.number(),
  hydration_index: z.number(),
  sleep_recovery_index: z.number(),
  stress_catecholamine_index: z.number(),
  ambient_temperature_c: z.number(),
  altitude_m: z.number(),
  oxygen_fraction: z.number(),
  medication_effect_profile: z.record(z.number()).nullable().optional(),
  data_uncertainty_policy: DataUncertaintyPolicySchema,
  missing_value_policy: MissingValuePolicySchema,
})

export const RecoveryConfigSchema = z.object({
  recovery_horizon_days: z.number().int().min(1).max(365),
  scenario_type: RecoveryScenarioTypeSchema,
  contractility_delta_per_day: z.number(),
  afterload_delta_per_day: z.number(),
  preload_delta_per_day: z.number(),
  inflammation_decay_rate: z.number(),
  oxygen_delivery_delta_per_day: z.number(),
  stiffness_delta_per_day: z.number(),
  scar_remodeling_rate: z.number(),
  heart_rate_adaptation_rate: z.number(),
  arrhythmia_stability_delta: z.number(),
  max_safe_parameter_shift: z.number(),
  uncertainty_penalty_weight: z.number(),
  target_metric: TargetMetricSchema,
})

export const SimulationConfigSchema = z.object({
  operating: OperatingEnvironmentSchema,
  recovery: RecoveryConfigSchema,
  random_seed: z.number().int(),
})

export const SourceMapEntrySchema = z.object({
  field: z.string(),
  value: z.number().nullable().optional(),
  unit: z.string(),
  source: ValueSourceSchema,
  source_file_id: z.string().nullable().optional(),
  confidence: z.number().min(0).max(1),
  method: z.string().nullable().optional(),
  evidence: z.string().nullable().optional(),
})

export const CardiacTwinStateSchema = z.object({
  case_id: z.string(),
  created_at: z.string(),
  data_quality_score: z.number().min(0).max(1),
  safety_level: SafetyLevelSchema,
  patient_context: PatientContextSchema,
  measurements: MeasurementsSchema,
  electrophysiology: ElectrophysiologySchema,
  hemodynamics: HemodynamicsSchema,
  tissue_state: TissueStateSchema,
  operating_environment: OperatingEnvironmentSchema,
  simulation_config: SimulationConfigSchema,
  source_map: z.array(SourceMapEntrySchema),
  warnings: z.array(z.string()),
})

export const AgentTraceStepSchema = z.object({
  tool: z.string(),
  inputs: z.record(z.unknown()),
  outputs: z.record(z.unknown()),
  duration_ms: z.number(),
})

export const AgentResponseSchema = z.object({
  agent: z.string(),
  status: AgentStatusSchema,
  inputs_used: z.array(z.string()),
  outputs: z.record(z.unknown()),
  warnings: z.array(z.string()),
  confidence: z.number().min(0).max(1),
  trace: z.array(AgentTraceStepSchema),
})

export const ManualVitalsSchema = z.object({
  heart_rate_bpm: z.number().min(20).max(280).optional(),
  systolic_bp_mmhg: z.number().min(50).max(260).optional(),
  diastolic_bp_mmhg: z.number().min(20).max(160).optional(),
  edv_ml: z.number().min(30).max(400).optional(),
  esv_ml: z.number().min(5).max(350).optional(),
  ejection_fraction_pct: z.number().min(5).max(90).optional(),
  troponin_ng_l: z.number().min(0).optional(),
  bnp_pg_ml: z.number().min(0).optional(),
  oxygen_saturation_pct: z.number().min(50).max(100).optional(),
  age_years: z.number().min(0).max(130).optional(),
  sex: z.enum(['male', 'female', 'other', '']).optional(),
  height_cm: z.number().min(50).max(250).optional(),
  weight_kg: z.number().min(1).max(500).optional(),
  notes: z.string().max(500).optional(),
}).refine(
  (data) => data.esv_ml == null || data.edv_ml == null || data.esv_ml < data.edv_ml,
  { message: 'ESV must be less than EDV', path: ['esv_ml'] },
).refine(
  (data) => (
    data.diastolic_bp_mmhg == null
    || data.systolic_bp_mmhg == null
    || data.diastolic_bp_mmhg < data.systolic_bp_mmhg
  ),
  { message: 'Diastolic BP must be less than systolic BP', path: ['diastolic_bp_mmhg'] },
)

export type ManualVitals = z.infer<typeof ManualVitalsSchema>

export function safeParse<T>(
  schema: z.ZodSchema<T>,
  data: unknown,
): { ok: true; data: T } | { ok: false; errors: z.ZodError } {
  const result = schema.safeParse(data)
  if (result.success) return { ok: true, data: result.data }
  return { ok: false, errors: result.error }
}
