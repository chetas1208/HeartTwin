<template>
  <TresGroup :position="[0, 0, 0]">
    <!-- Left ventricle (main chamber) -->
    <TresMesh :scale="[scale * 1.0, scale * 1.15, scale * 0.9]" :position="[-0.15, -0.1, 0]">
      <TresSphereGeometry :args="[0.65, 32, 32]" />
      <TresMeshPhongMaterial
        :color="lvColor"
        :emissive="lvEmissive"
        :emissive-intensity="lvEmissiveIntensity"
        :shininess="80"
        :transparent="true"
        :opacity="0.92"
      />
    </TresMesh>

    <!-- Right ventricle -->
    <TresMesh :scale="[scale * 0.75, scale * 1.0, scale * 0.8]" :position="[0.45, -0.1, 0.05]">
      <TresSphereGeometry :args="[0.60, 24, 24]" />
      <TresMeshPhongMaterial
        :color="rvColor"
        :emissive="rvEmissive"
        :emissive-intensity="0.15"
        :shininess="60"
        :transparent="true"
        :opacity="0.85"
      />
    </TresMesh>

    <!-- Left atrium -->
    <TresMesh :scale="[scale * 0.65, scale * 0.65, scale * 0.65]" :position="[-0.25, 0.55, 0.1]">
      <TresSphereGeometry :args="[0.55, 20, 20]" />
      <TresMeshPhongMaterial
        :color="laColor"
        :emissive="laEmissive"
        :emissive-intensity="0.12"
        :shininess="50"
        :transparent="true"
        :opacity="0.80"
      />
    </TresMesh>

    <!-- Right atrium -->
    <TresMesh :scale="[scale * 0.60, scale * 0.60, scale * 0.60]" :position="[0.40, 0.50, 0.1]">
      <TresSphereGeometry :args="[0.52, 20, 20]" />
      <TresMeshPhongMaterial
        :color="raColor"
        :emissive="raEmissive"
        :emissive-intensity="0.10"
        :shininess="50"
        :transparent="true"
        :opacity="0.78"
      />
    </TresMesh>

    <!-- Aorta arc (simplified) -->
    <TresMesh :scale="[scale * 0.25, scale * 0.9, scale * 0.25]" :position="[0.0, 0.85, 0.0]" :rotation="[0, 0, 0.3]">
      <TresCylinderGeometry :args="[0.25, 0.3, 1.0, 16]" />
      <TresMeshPhongMaterial :color="0x8B1A1A" :shininess="40" :transparent="true" :opacity="0.75" />
    </TresMesh>
  </TresGroup>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  heartRateBpm?: number | null
  ejectionFraction?: number | null
  contractilityIndex?: number | null
  scarFraction?: number | null
  inflammationIndex?: number | null
}>()

const phase = ref(0)
let animFrame: number

function animate() {
  const bpm = props.heartRateBpm ?? 70
  const cycleMs = 60000 / bpm
  phase.value = (Date.now() % cycleMs) / cycleMs
  animFrame = requestAnimationFrame(animate)
}

onMounted(() => { animFrame = requestAnimationFrame(animate) })
onUnmounted(() => cancelAnimationFrame(animFrame))

const beatIntensity = computed(() => {
  const p = phase.value
  if (p < 0.15) return Math.sin((p / 0.15) * Math.PI)
  if (p < 0.30) return Math.sin(((p - 0.15) / 0.15) * Math.PI) * 0.5
  return 0
})

const contractility = computed(() => props.contractilityIndex ?? 1.0)
const ef = computed(() => (props.ejectionFraction ?? 60) / 100)

const scale = computed(() => {
  const base = 1.0
  const contraction = beatIntensity.value * contractility.value * 0.12 * Math.sqrt(ef.value * 1.5)
  return base + contraction
})

const lvColor = computed(() => {
  const scar = props.scarFraction ?? 0
  if (scar > 0.2) return 0x7A2020
  if (scar > 0.1) return 0x8B2424
  return 0xAB2B2B
})

const rvColor = computed(() => 0x9B3030)
const laColor = computed(() => 0xA03535)
const raColor = computed(() => 0x953030)

const lvEmissive = computed(() => {
  const infl = props.inflammationIndex ?? 0
  return infl > 0.3 ? 0xFF4400 : 0xCC2222
})

const rvEmissive = computed(() => 0xAA1515)
const laEmissive = computed(() => 0xAA1515)
const raEmissive = computed(() => 0xAA1515)

const lvEmissiveIntensity = computed(() => {
  return 0.08 + beatIntensity.value * 0.25 * contractility.value
})
</script>
