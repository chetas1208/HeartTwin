<template>
  <TresMesh
    v-if="scarFraction && scarFraction > 0.01"
    :position="damagePos"
    :scale="[scarScale, scarScale * 0.8, scarScale]"
    :rotation="[0.3, 0.5, 0]"
  >
    <TresSphereGeometry :args="[0.55, 12, 12]" />
    <TresMeshPhongMaterial
      :color="0x442244"
      :emissive="0x220022"
      :emissive-intensity="0.3"
      :transparent="true"
      :opacity="damageOpacity"
      :wireframe="false"
    />
  </TresMesh>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  scarFraction?: number | null
  damageZoneLocation?: string | null
}>()

const scarFraction = computed(() => props.scarFraction ?? 0)

const damagePos = computed((): [number, number, number] => {
  const loc = props.damageZoneLocation?.toLowerCase() || ''
  if (loc.includes('anterior')) return [-0.2, 0.1, 0.5]
  if (loc.includes('inferior')) return [-0.1, -0.5, 0.1]
  if (loc.includes('lateral')) return [0.5, 0.0, 0.0]
  if (loc.includes('posterior')) return [-0.1, 0.0, -0.5]
  return [-0.2, -0.1, 0.3]
})

const scarScale = computed(() => Math.min(0.8, scarFraction.value * 1.5 + 0.1))
const damageOpacity = computed(() => Math.min(0.65, scarFraction.value * 1.2 + 0.15))
</script>
