<template>
  <div class="heart-scene w-full h-full relative rounded-xl overflow-hidden">
    <!-- ECG grid background -->
    <div class="absolute inset-0 ecg-grid-bg opacity-40" />

    <!-- Simulation label -->
    <div class="absolute top-3 left-3 z-10">
      <span class="sim-label text-xs">SIMULATION ONLY</span>
    </div>

    <!-- Mode badge -->
    <div class="absolute top-3 right-3 z-10 flex items-center gap-2">
      <span class="text-xs font-mono text-cardiac-electric">
        {{ operatingMode.toUpperCase().replace('_', ' ') }}
      </span>
      <div class="w-2 h-2 rounded-full bg-cardiac-red animate-pulse" />
    </div>

    <!-- Heart rate display -->
    <div v-if="heartRateBpm" class="absolute bottom-3 left-3 z-10">
      <div class="flex items-center gap-1.5">
        <svg class="w-3 h-3 text-cardiac-red animate-heartbeat" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 21.593c-5.63-5.539-11-10.297-11-14.402 0-3.791 3.068-5.191 5.281-5.191 1.312 0 4.151.501 5.719 4.457 1.59-3.968 4.464-4.447 5.726-4.447 2.54 0 5.274 1.621 5.274 5.181 0 4.069-5.136 8.625-11 14.402z"/>
        </svg>
        <span class="text-xs font-mono text-cardiac-red font-semibold">{{ heartRateBpm.toFixed(0) }} bpm</span>
      </div>
    </div>

    <!-- EF display -->
    <div v-if="ejectionFraction" class="absolute bottom-3 right-3 z-10">
      <span class="text-xs font-mono text-cardiac-electric">EF {{ ejectionFraction.toFixed(1) }}%</span>
    </div>

    <!-- 3D Scene -->
    <TresCanvas
      :alpha="true"
      :antialias="true"
      class="w-full h-full"
    >
      <TresPerspectiveCamera :position="[0, 0, 4]" :fov="45" />
      <TresOrbitControls :enable-damping="true" :damping-factor="0.05" />

      <!-- Ambient light -->
      <TresAmbientLight :intensity="0.4" :color="0x1A1A2E" />

      <!-- Key light (warm surgical) -->
      <TresPointLight :position="[2, 3, 3]" :intensity="1.2" :color="0xFFEEDD" />

      <!-- Fill light (cool blue) -->
      <TresPointLight :position="[-2, 1, 2]" :intensity="0.6" :color="0x1A6FFF" />

      <!-- Rim light -->
      <TresPointLight :position="[0, -2, -1]" :intensity="0.4" :color="0xE31B1B" />

      <!-- Rotating group -->
      <TresGroup :rotation="[rotation.x, rotation.y, 0]">
        <BeatingHeartMesh
          :heart-rate-bpm="heartRateBpm"
          :ejection-fraction="ejectionFraction"
          :contractility-index="contractilityIndex"
          :scar-fraction="scarFraction"
          :inflammation-index="inflammationIndex"
        />

        <DamageZoneOverlay
          v-if="showDamageZone"
          :scar-fraction="scarFraction"
          :damage-zone-location="damageZoneLocation"
        />

        <ElectricalWaveOverlay
          v-if="showElectricalOverlay"
          :heart-rate-bpm="heartRateBpm"
          :arrhythmia-instability="arrhythmiaInstability"
          :visible="true"
        />
      </TresGroup>

      <BloodFlowParticles
        v-if="showBloodFlow"
        :heart-rate-bpm="heartRateBpm"
        :oxygen-delivery-index="oxygenDeliveryIndex"
        :cardiac-output="cardiacOutput"
      />
    </TresCanvas>

    <!-- Empty state overlay -->
    <div v-if="isEmpty" class="absolute inset-0 flex flex-col items-center justify-center bg-cardiac-navy/70 z-20">
      <div class="text-center px-6">
        <div class="w-16 h-16 mx-auto mb-4 text-cardiac-red/40">
          <svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M32 10C32 10 10 22 10 38a22 22 0 0044 0C54 22 32 10 32 10z"/>
            <path d="M18 38c0-8 6-14 14-14s14 6 14 14"/>
            <path d="M22 42l4 6 6-12 4 6 2-3"/>
          </svg>
        </div>
        <p class="text-sm text-cardiac-muted">No cardiac state loaded</p>
        <p class="text-xs text-cardiac-muted/60 mt-1">Upload files and run extraction to build the twin</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive } from 'vue'
import type { CardiacTwinState, SimulationVisualization } from '~/types/heart'

const props = defineProps<{
  state?: CardiacTwinState | null
  visualization?: SimulationVisualization | null
  operatingMode?: string
  showDamageZone?: boolean
  showBloodFlow?: boolean
  showElectricalOverlay?: boolean
}>()

const operatingMode = computed(() => props.operatingMode || 'rest')
const isEmpty = computed(() => !props.state && !props.visualization)

const heartRateBpm = computed(() => {
  return props.visualization?.summary.heart_rate_bpm
    ?? props.state?.measurements.heart_rate_bpm?.value
    ?? null
})

const ejectionFraction = computed(() => {
  return props.visualization?.summary.ef_pct
    ?? props.state?.measurements.ejection_fraction_pct?.value
    ?? null
})

const cardiacOutput = computed(() => {
  return props.visualization?.summary.cardiac_output_l_min
    ?? props.state?.measurements.cardiac_output_l_min?.value
    ?? null
})

const contractilityIndex = computed(() => props.state?.hemodynamics.contractility_index?.value ?? 1.0)
const scarFraction = computed(() => props.state?.tissue_state.scar_fraction?.value ?? 0)
const inflammationIndex = computed(() => props.state?.tissue_state.inflammation_index?.value ?? 0.1)
const oxygenDeliveryIndex = computed(() => props.state?.tissue_state.oxygen_delivery_index?.value ?? 0.85)
const damageZoneLocation = computed(() => props.state?.tissue_state.damage_zone_location ?? null)
const arrhythmiaInstability = computed(() =>
  props.state?.electrophysiology.arrhythmia_instability_score?.value ?? 0.1
)

const showDamageZone = computed(() => props.showDamageZone ?? true)
const showBloodFlow = computed(() => props.showBloodFlow ?? true)
const showElectricalOverlay = computed(() => props.showElectricalOverlay ?? true)

const rotation = reactive({ x: 0, y: 0 })
let animFrame: number
const startTime = Date.now()

function animate() {
  const elapsed = (Date.now() - startTime) / 1000
  rotation.y = Math.sin(elapsed * 0.15) * 0.2
  rotation.x = Math.sin(elapsed * 0.1) * 0.08
  animFrame = requestAnimationFrame(animate)
}

onMounted(() => { animFrame = requestAnimationFrame(animate) })
onUnmounted(() => cancelAnimationFrame(animFrame))
</script>

<style scoped>
.heart-scene {
  min-height: 24rem;
  background:
    radial-gradient(circle at 50% 42%, rgba(255, 54, 95, 0.16), transparent 16rem),
    radial-gradient(circle at 70% 18%, rgba(56, 189, 248, 0.10), transparent 16rem),
    #030711;
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: inset 0 0 80px rgba(0, 0, 0, 0.62);
}

.heart-scene::after {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at center, transparent 40%, rgba(0, 0, 0, 0.44) 100%);
  content: "";
}

.sim-label {
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.55rem;
  color: var(--ht-cyan);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.26);
  border-radius: 999px;
  box-shadow: var(--ht-shadow-glow-blue);
}

@media (max-width: 768px) {
  .heart-scene {
    min-height: 20rem;
  }
}
</style>
