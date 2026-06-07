export default defineNuxtConfig({
  compatibilityDate: '2024-11-01',

  future: {
    compatibilityVersion: 4,
  },

  modules: [
    '@pinia/nuxt',
    '@tresjs/nuxt',
    '@nuxtjs/tailwindcss',
    '@vueuse/nuxt',
  ],

  components: [
    {
      path: '~/components',
      pathPrefix: false,
    },
  ],

  tailwindcss: {
    cssPath: '~/assets/css/tailwind.css',
    configPath: 'tailwind.config.ts',
  },

  runtimeConfig: {
    openaiApiKey: process.env.OPENAI_API_KEY,
    wandbApiKey: process.env.WANDB_API_KEY,
    wandbEntity: process.env.WANDB_ENTITY,
    wandbProject: process.env.WANDB_PROJECT || 'hearttwin-weavehacks',
    blobReadWriteToken: process.env.BLOB_READ_WRITE_TOKEN,
    upstashRedisRestUrl: process.env.UPSTASH_REDIS_REST_URL,
    upstashRedisRestToken: process.env.UPSTASH_REDIS_REST_TOKEN,
    apiBase: process.env.API_BASE || '/api/v1',
    vista3dApiBase: process.env.VISTA3D_API_BASE,
    vista3dApiKey: process.env.VISTA3D_API_KEY,
    vista3dTimeoutSeconds: process.env.VISTA3D_TIMEOUT_SECONDS || '120',
    vista3dEnabled: process.env.VISTA3D_ENABLED || 'false',
    hearttwinSafetyMode: process.env.HEARTTWIN_SAFETY_MODE || 'strict',
    hearttwinTraceMode: process.env.HEARTTWIN_TRACE_MODE || 'weave_with_local_fallback',
    hearttwinRedisMemoryEnabled: process.env.HEARTTWIN_REDIS_MEMORY_ENABLED || 'true',
    public: {
      appName: process.env.NUXT_PUBLIC_APP_NAME || 'HeartTwin Lab',
      apiBase:
        process.env.NUXT_PUBLIC_API_BASE ||
        process.env.API_BASE ||
        process.env.NEXT_PUBLIC_API_BASE ||
        '/api/v1',
      weaveProjectUrl: process.env.NUXT_PUBLIC_WEAVE_PROJECT_URL,
    },
  },

  typescript: {
    strict: true,
    typeCheck: false,
  },

  app: {
    head: {
      title: 'HeartTwin Lab',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        {
          name: 'description',
          content:
            'Agentic cardiac digital twin simulator. Educational simulation only — not for diagnosis.',
        },
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
      ],
    },
  },

  ssr: true,

  vite: {
    optimizeDeps: {
      include: ['plotly.js-dist-min'],
    },
  },
})
