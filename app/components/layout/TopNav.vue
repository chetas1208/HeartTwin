<template>
  <nav
    class="top-nav fixed top-0 left-0 right-0 z-50 h-14"
    role="navigation"
    aria-label="HeartTwin Lab"
  >
    <div class="h-full flex items-center px-4 gap-3">

      <!-- Logo -->
      <NuxtLink to="/" class="flex items-center gap-2.5 shrink-0 group" aria-label="HeartTwin Lab home">
        <div class="w-7 h-7 relative">
          <svg viewBox="0 0 28 28" fill="none" class="w-full h-full">
            <path d="M14 4C14 4 4 9 4 16a10 10 0 0020 0C24 9 14 4 14 4z" fill="url(#hg)" opacity="0.9"/>
            <path d="M7 16c0-4 3-7 7-7s7 3 7 7" stroke="#e31b1b" stroke-width="1.5" stroke-linecap="round"/>
            <path d="M10 18l2 3 3-6 2 3 1-2" stroke="#00d4ff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <defs>
              <linearGradient id="hg" x1="4" y1="4" x2="24" y2="24">
                <stop offset="0%" stop-color="#e31b1b" stop-opacity="0.9"/>
                <stop offset="100%" stop-color="#1a6fff" stop-opacity="0.7"/>
              </linearGradient>
            </defs>
          </svg>
          <!-- Subtle heartbeat glow on hover -->
          <div
            class="absolute inset-0 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300"
            style="box-shadow: 0 0 12px rgba(227,27,27,0.5);"
            aria-hidden="true"
          />
        </div>
        <div class="flex items-baseline gap-1">
          <span class="font-mono font-bold text-sm tracking-widest text-white">
            HEART<span class="text-cardiac-red">TWIN</span>
          </span>
          <span class="font-mono text-xs tracking-wider" style="color:rgba(148,163,184,0.5)">LAB</span>
        </div>
      </NuxtLink>

      <!-- Divider -->
      <div class="h-5 w-px mx-0.5 shrink-0" style="background:rgba(16,42,80,0.8)" aria-hidden="true" />

      <!-- Nav links -->
      <div class="hidden md:flex items-center gap-0.5">
        <NuxtLink
          v-for="link in NAV_LINKS"
          :key="link.to"
          :to="link.to"
          class="px-3 py-1.5 rounded text-xs font-mono transition-colors duration-150"
          :style="{ color: 'rgba(148,163,184,0.7)' }"
          active-class="!text-white"
          exact-active-class="!text-white"
        >
          {{ link.label }}
        </NuxtLink>
      </div>

      <div class="flex-1" />

      <!-- System status chip -->
      <div
        class="engine-chip hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono"
        role="status"
        aria-label="Simulation engine active"
      >
        <span class="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse shrink-0" aria-hidden="true" />
        SIM ACTIVE
      </div>

      <!-- Safety chip -->
      <div class="safety-chip hidden md:flex shrink-0" role="status" aria-label="Educational simulation only">
        <svg class="w-2.5 h-2.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/>
        </svg>
        Sim Only
      </div>

      <!-- Open Lab CTA -->
      <NuxtLink to="/lab" aria-label="Open HeartTwin Lab">
        <button class="btn-primary text-xs px-3 py-1.5 rounded-lg shrink-0">Open Lab</button>
      </NuxtLink>
    </div>
  </nav>
</template>

<script setup lang="ts">
const NAV_LINKS = [
  { to: '/', label: 'Home' },
  { to: '/lab', label: 'Lab' },
  { to: '/about', label: 'About' },
]
</script>

<style scoped>
.top-nav {
  background:
    linear-gradient(180deg, rgba(3, 7, 17, 0.98), rgba(7, 17, 31, 0.94));
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.34);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.top-nav::after {
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--ht-red), var(--ht-blue), transparent);
  opacity: 0.55;
  content: "";
}

a:hover {
  color: var(--ht-text) !important;
}

.engine-chip {
  color: rgba(134, 239, 172, 0.88);
  background: rgba(34, 197, 94, 0.08);
  border: 1px solid rgba(34, 197, 94, 0.22);
}

.safety-chip {
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.625rem;
  color: rgba(251, 191, 36, 0.86);
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 0.72rem;
  background: rgba(245, 158, 11, 0.09);
  border: 1px solid rgba(245, 158, 11, 0.22);
  border-radius: 999px;
}

.btn-primary {
  color: #fff;
  font-weight: 700;
  background: linear-gradient(135deg, var(--ht-red), #cf123f);
  border: 1px solid rgba(255, 255, 255, 0.10);
  box-shadow: 0 0 22px rgba(255, 54, 95, 0.20);
  transition: transform 160ms ease, box-shadow 160ms ease;
}

.btn-primary:hover {
  box-shadow: 0 0 30px rgba(255, 54, 95, 0.34);
  transform: translateY(-1px);
}

@media (prefers-reduced-motion: reduce) {
  a,
  .btn-primary {
    transition: none;
  }

  .btn-primary:hover {
    transform: none;
  }
}
</style>
