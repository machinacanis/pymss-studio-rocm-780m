import assert from 'node:assert/strict'
import test, { after, afterEach } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createPinia } from 'pinia'
import { createServer } from 'vite'

const vite = await createServer({
  configFile: false,
  server: {
    middlewareMode: true,
    hmr: false,
    watch: { ignored: ['**/*'] },
  },
  appType: 'custom',
  optimizeDeps: { noDiscovery: true },
  resolve: { alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) } },
  plugins: [{
    name: 'stub-page-size-store-environment',
    enforce: 'pre',
    transform(_code, id) {
      const path = id.replaceAll('\\', '/')
      if (path.endsWith('/src/stores/settings.ts')) {
        return `export function useSettingsStore() {
          return { maxConcurrentSeparations: 1 }
        }`
      }
      if (path.endsWith('/src/i18n/index.ts')) {
        return `export default { global: { t: key => key } }`
      }
      return null
    },
  }],
})

after(() => vite.close())

const { useModelStore } = await vite.ssrLoadModule('/src/stores/model.ts')
const { useTaskStore } = await vite.ssrLoadModule('/src/stores/task.ts')

const stores = []

afterEach(async () => {
  // Hydration can schedule an existing Store watcher on Vue's next flush.
  // Let any debounced write finish before removing the browser storage shim.
  await waitForDebouncedSave()
  for (const store of stores.splice(0)) store.$dispose()
  Reflect.deleteProperty(globalThis, 'window')
  Reflect.deleteProperty(globalThis, 'localStorage')
})

function browserStorage(initial = {}) {
  const values = new Map(
    Object.entries(initial).map(([name, value]) => [
      `pymss-studio:${name}`,
      JSON.stringify(value),
    ]),
  )
  const writes = []
  globalThis.window = {}
  globalThis.localStorage = {
    getItem: key => values.get(key) ?? null,
    setItem(key, value) {
      values.set(key, value)
      writes.push({ key, value: JSON.parse(value) })
    },
  }
  return { writes }
}

function newModelStore() {
  const store = useModelStore(createPinia())
  stores.push(store)
  return store
}

function newTaskStore() {
  const store = useTaskStore(createPinia())
  stores.push(store)
  return store
}

const waitForDebouncedSave = () => new Promise(resolve => setTimeout(resolve, 180))

test('model library restores and persists its page size preference', async () => {
  const storage = browserStorage({ 'model-state': { modelPageSize: 48 } })
  const store = newModelStore()

  await store.initialize()
  assert.equal(store.modelPageSize, 48)

  store.modelPageSize = 96
  await waitForDebouncedSave()

  assert.equal(storage.writes.at(-1)?.key, 'pymss-studio:model-state')
  assert.equal(storage.writes.at(-1)?.value.modelPageSize, 96)
})

test('separation model list restores and persists its page size preference', async () => {
  const storage = browserStorage({ 'separate-state': { modelListPageSize: 24 } })
  const store = newTaskStore()

  await store.initialize()
  assert.equal(store.modelListPageSize, 24)

  store.modelListPageSize = 8
  await waitForDebouncedSave()

  assert.equal(storage.writes.at(-1)?.key, 'pymss-studio:separate-state')
  assert.equal(storage.writes.at(-1)?.value.modelListPageSize, 8)
})

test('invalid stored page sizes fall back to each view default', async () => {
  browserStorage({
    'model-state': { modelPageSize: 13 },
    'separate-state': { modelListPageSize: '24' },
  })
  const modelStore = newModelStore()
  const taskStore = newTaskStore()

  await Promise.all([modelStore.initialize(), taskStore.initialize()])

  assert.equal(modelStore.modelPageSize, 24)
  assert.equal(taskStore.modelListPageSize, 12)
})
