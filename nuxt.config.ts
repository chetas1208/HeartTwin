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
    blobReadWriteToken: process.env.BLOB_READ_WRITE_TOKEN,
    upstashRedisRestUrl: process.env.UPSTASH_REDIS_REST_URL,
    upstashRedisRestToken: process.env.UPSTASH_REDIS_REST_TOKEN,
    public: {
      appName: process.env.NUXT_PUBLIC_APP_NAME || 'HeartTwin Lab',
      apiBase:
        process.env.NUXT_PUBLIC_API_BASE ||
        process.env.NEXT_PUBLIC_API_BASE ||
        process.env.API_BASE ||
        '/api/v1',
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
