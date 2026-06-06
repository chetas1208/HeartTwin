<template>
  <TresGroup v-if="visible">
    <TresMesh
      v-for="(arc, i) in arcs"
      :key="i"
      :position="arc.pos"
      :scale="[arc.scale, arc.scale, arc.scale]"
      :rotation="arc.rot"
    >
      <TresTorusGeometry :args="[1, 0.015, 8, 32, Math.PI * arc.arc]" />
      <TresMeshBasicMaterial
        :color="arc.color"
        :transparent="true"
        :opacity="arc.opacity"
      />
    </TresMesh>
  </TresGroup>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps<{
  heartRateBpm?: number | null
  arrhythmiaInstability?: number | null
  visible?: boolean
}>()

const time = ref(0)
let animFrame: number

function animate() {
  time.value += 0.02
  animFrame = requestAnimationFrame(animate)
}

onMounted(() => { animFrame = requestAnimationFrame(animate) })
onUnmounted(() => cancelAnimationFrame(animFrame))

const ARC_COUNT = 4
const arcs = computed(() => {
  const bpm = props.heartRateBpm ?? 70
  const instability = props.arrhythmiaInstability ?? 0.1
  const cycleSpeed = bpm / 60

  return Array.from({ length: ARC_COUNT }, (_, i) => {
    const offset = i / ARC_COUNT
    const phase = (time.value * cycleSpeed + offset) % 1.0
    const opacity = Math.max(0, Math.sin(phase * Math.PI) * 0.6)
    const scale = 0.7 + phase * 0.8
    const jitter = instability * 0.1 * Math.sin(time.value * 3 + i)

    return {
      pos: [jitter, 0, 0] as [number, number, number],
      scale: scale + jitter * 0.1,
      rot: [Math.PI / 2, time.value * 0.2 + i * Math.PI / 2, 0] as [number, number, number],
      color: instability > 0.4 ? 0xFFAA00 : 0x00D4FF,
      opacity: opacity,
      arc: 1.0 - instability * 0.3,
    }
  })
})
</script>
