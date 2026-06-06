<template>
  <TresGroup>
    <TresMesh
      v-for="(p, i) in particles"
      :key="i"
      :position="p.pos"
      :scale="[p.size, p.size, p.size]"
    >
      <TresSphereGeometry :args="[1, 6, 6]" />
      <TresMeshBasicMaterial :color="p.color" :transparent="true" :opacity="p.opacity" />
    </TresMesh>
  </TresGroup>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

const props = defineProps<{
  heartRateBpm?: number | null
  oxygenDeliveryIndex?: number | null
  cardiacOutput?: number | null
}>()

const time = ref(0)
let animFrame: number
const PARTICLE_COUNT = 20

interface Particle {
  pos: [number, number, number]
  size: number
  color: number
  opacity: number
  angle: number
  radius: number
  speed: number
  oxygenated: boolean
}

const baseParticles: Particle[] = Array.from({ length: PARTICLE_COUNT }, (_, i) => {
  const oxygenated = i < PARTICLE_COUNT * 0.7
  const angle = (i / PARTICLE_COUNT) * Math.PI * 2
  const radius = 0.4 + Math.random() * 0.5
  return {
    pos: [0, 0, 0],
    size: 0.04 + Math.random() * 0.03,
    color: oxygenated ? 0x1A6FFF : 0x442244,
    opacity: 0.6 + Math.random() * 0.3,
    angle,
    radius,
    speed: 0.5 + Math.random() * 0.5,
    oxygenated,
  }
})

function updateParticles(t: number) {
  const _bpm = props.heartRateBpm ?? 70
  const coMod = Math.min(2.0, (props.cardiacOutput ?? 5.0) / 5.0)
  const o2Mod = props.oxygenDeliveryIndex ?? 0.85

  return baseParticles.map((p) => {
    const a = p.angle + t * p.speed * coMod * 0.8
    const x = Math.cos(a) * p.radius * 0.8
    const y = Math.sin(a * 0.7) * p.radius * 0.5
    const z = Math.sin(a * 1.3) * p.radius * 0.3

    const oxyColor = p.oxygenated
      ? Math.round(0x1A + o2Mod * 0x40) * 0x10000 + 0x006FFF
      : 0x442244

    return { ...p, pos: [x, y, z] as [number, number, number], color: oxyColor }
  })
}

const particles = ref(updateParticles(0))

function animate() {
  time.value += 0.016
  particles.value = updateParticles(time.value)
  animFrame = requestAnimationFrame(animate)
}

onMounted(() => { animFrame = requestAnimationFrame(animate) })
onUnmounted(() => cancelAnimationFrame(animFrame))
</script>
