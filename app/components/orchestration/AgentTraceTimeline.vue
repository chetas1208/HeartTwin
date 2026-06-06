<template>
  <div class="space-y-0" :class="compact ? 'space-y-2' : 'space-y-4'">
    <div
      v-for="(stage, si) in stages"
      :key="si"
      class="relative"
    >
      <!-- Stage header row -->
      <div class="flex items-center gap-2 mb-2">
        <div
          class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono font-bold shrink-0 z-10"
          :class="stageNodeClass(stage.status)"
          :aria-label="`Stage ${stage.stage}: ${stage.status}`"
        >
          <svg v-if="stage.status === 'success'" class="w-3 h-3" fill="none" viewBox="0 0 12 12" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2 6l3 3 5-5"/>
          </svg>
          <svg v-else-if="stage.status === 'running'" class="w-2 h-2 animate-pulse" fill="currentColor" viewBox="0 0 8 8" aria-hidden="true">
            <circle cx="4" cy="4" r="3"/>
          </svg>
          <span v-else>{{ stage.stage }}</span>
        </div>

        <div class="flex-1 h-px" style="background:rgba(16,42,80,0.8)" aria-hidden="true" />

        <span class="text-[10px] font-mono shrink-0" style="color:rgba(148,163,184,0.4)">
          Stage {{ stage.stage }}
        </span>
        <span
          v-if="stage.agents.some(a => a.parallel)"
          class="text-[10px] font-mono shrink-0"
          style="color:rgba(148,163,184,0.35)"
        >
          &parallel;
        </span>
      </div>

      <!-- Agent cards -->
      <div
        :class="[
          !compact && stage.agents.length > 1 ? 'grid grid-cols-2 gap-2' : 'space-y-1.5',
          'pl-6',
          !compact && stage.agents.length > 1 && 'pl-0',
        ]"
      >
        <div v-for="row in agentRows(stage.agents)" :key="row.agent.name">
          <AgentDecisionCard
            v-if="row.response"
            :response="row.response"
            :compact="compact"
          />
          <div
            v-else
            class="flex items-center gap-2 px-3 py-2 rounded-lg"
            style="background:rgba(10,31,58,0.4); border:1px solid rgba(16,42,80,0.5);"
          >
            <div class="w-1.5 h-1.5 rounded-full shrink-0" style="background:rgba(148,163,184,0.2)" />
            <span class="text-[11px] font-mono" style="color:rgba(148,163,184,0.4)">{{ row.agent.displayName }}</span>
            <span class="text-[10px] font-mono ml-auto" style="color:rgba(148,163,184,0.3)">pending</span>
          </div>
        </div>
      </div>

      <!-- Connector to next stage -->
      <div
        v-if="si < stages.length - 1"
        class="absolute left-[9px] bottom-0 w-px"
        style="background:linear-gradient(to bottom, rgba(16,42,80,0.7), rgba(16,42,80,0.2)); top: 20px;"
        aria-hidden="true"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentResponse } from '~/types/api'
import { buildPipelineStages, type AgentStageInfo } from '~/types/agents'

const props = defineProps<{
  responses: AgentResponse[]
  agentStatuses?: Record<string, string>
  compact?: boolean
}>()

const responseMap = computed(() => {
  const map: Record<string, AgentResponse> = {}
  for (const r of props.responses) map[r.agent] = r
  return map
})

const allStatuses = computed(() => {
  const statuses = { ...(props.agentStatuses || {}) }
  for (const r of props.responses) statuses[r.agent] = r.status
  return statuses
})

const stages = computed(() => buildPipelineStages(allStatuses.value))

function agentRows(agents: AgentStageInfo[]) {
  return agents.map(agent => ({
    agent,
    response: responseMap.value[agent.name] ?? null,
  }))
}

function stageNodeClass(status: string) {
  if (status === 'success') return 'bg-green-900/60 text-green-400 border border-green-700/70'
  if (status === 'warning') return 'bg-amber-900/60 text-amber-400 border border-amber-700/70'
  if (status === 'failed')  return 'bg-red-900/60 text-red-400 border border-red-700/70'
  if (status === 'running') return 'bg-blue-900/60 text-blue-400 border border-blue-700/70'
  return 'bg-cardiac-navy-card border border-cardiac-navy-border text-cardiac-muted/50'
}
</script>

<style scoped>
.relative {
  isolation: isolate;
}

.rounded-lg {
  border-radius: var(--ht-radius-sm);
}

@media (prefers-reduced-motion: reduce) {
  .animate-pulse {
    animation: none;
  }
}
</style>
