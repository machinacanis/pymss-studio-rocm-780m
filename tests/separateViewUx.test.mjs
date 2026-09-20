import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { parse } from 'vue/compiler-sfc'

const path = new URL('../src/views/SeparateView.vue', import.meta.url)
const { descriptor } = parse(readFileSync(path, 'utf8'))
const template = descriptor.template?.content || ''
const script = ts.createSourceFile('SeparateView.ts', descriptor.scriptSetup.content, ts.ScriptTarget.Latest, true)
const names = new Set([
  'modelPanelHasModels',
  'modelPanelLoading',
  'getOutputPlayback',
  'setOutputPlayback',
  'touchPreviewAudio',
  'releasePreviewAudio',
  'trimPreviewAudioCache',
  'getAudio',
  'syncOutputPreviewAudio',
])
const selected = script.statements.filter(statement => (
  ts.isFunctionDeclaration(statement) ? names.has(statement.name?.text)
    : ts.isVariableStatement(statement) && statement.declarationList.declarations.some(item => names.has(item.name.getText(script)))
))
assert.equal(selected.length, names.size)
const code = ts.transpileModule(selected.map(statement => statement.getText(script)).join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText

function computed(read) {
  return { get value() { return read() } }
}

test('model and workflow targets keep their keyed transition boundary', () => {
  const transitionTag = '<transition name="stage-swap" mode="out-in">'
  const modelBranch = '<div v-if="runMode === \'model\'" key="model"'
  const workflowBranch = '<div v-else key="workflow"'
  const modelIndex = template.indexOf(modelBranch)
  const transitionIndex = template.lastIndexOf(transitionTag, modelIndex)
  const readyIndex = template.lastIndexOf('<section v-else key="ready"', modelIndex)
  const workflowIndex = template.indexOf(workflowBranch, modelIndex)
  const closingIndex = template.indexOf('</transition>', workflowIndex)

  assert.equal(template.split(transitionTag).length - 1, 2)
  assert.ok(modelIndex > 0)
  assert.ok(transitionIndex > readyIndex)
  assert.ok(workflowIndex > modelIndex)
  assert.ok(closingIndex > workflowIndex)
})

test('model panel waits for the live model load instead of showing cached rows', () => {
  const context = {
    computed,
    modelsLoaded: { value: false },
    downloadedModels: { value: [{ name: 'cached-model' }] },
    isLoading: { value: true },
    modelError: { value: null },
    app: { envLoading: false },
  }
  const result = vm.runInNewContext(`${code}\n({ modelPanelHasModels, modelPanelLoading })`, context)

  assert.equal(result.modelPanelHasModels.value, false)
  assert.equal(result.modelPanelLoading.value, true)
  context.modelsLoaded.value = true
  context.isLoading.value = false
  assert.equal(result.modelPanelHasModels.value, true)
  assert.equal(result.modelPanelLoading.value, false)
})

test('preview audio requests metadata before playback', () => {
  const calls = []
  class FakeAudio {
    listeners = new Map()
    duration = 70.471
    currentTime = 0
    paused = true

    set preload(value) { calls.push(['preload', value]) }
    set src(value) { calls.push(['src', value]) }
    addEventListener(name, callback) { this.listeners.set(name, callback) }
    pause() { calls.push(['pause']) }
    removeAttribute(name) { calls.push(['removeAttribute', name]) }
    load() {
      calls.push(['load'])
      this.listeners.get('loadedmetadata')?.()
    }
  }
  const context = {
    computed,
    modelsLoaded: { value: true },
    downloadedModels: { value: [] },
    isLoading: { value: false },
    modelError: { value: null },
    app: { envLoading: false },
    Audio: FakeAudio,
    audioElements: new Map(),
    audioAccessOrder: [],
    PREVIEW_AUDIO_CACHE_LIMIT: 8,
    outputPlayback: { value: {} },
    playingOutputPath: { value: '' },
    convertFileSrc: value => `asset:${value}`,
  }
  const result = vm.runInNewContext(`${code}\n({ getAudio, getOutputPlayback })`, context)
  result.getAudio('output.wav')

  assert.deepEqual(calls, [
    ['preload', 'metadata'],
    ['src', 'asset:output.wav'],
    ['load'],
  ])
  assert.equal(result.getOutputPlayback('output.wav').duration, 70.471)
})

test('preview audio preload is bounded and stale players are released', () => {
  class FakeAudio {
    listeners = new Map()
    duration = 12
    currentTime = 0
    paused = true

    set preload(_value) {}
    set src(_value) {}
    addEventListener(name, callback) { this.listeners.set(name, callback) }
    pause() { this.paused = true }
    removeAttribute(_name) {}
    load() { this.listeners.get('loadedmetadata')?.() }
  }
  const context = {
    computed,
    modelsLoaded: { value: true },
    downloadedModels: { value: [] },
    isLoading: { value: false },
    modelError: { value: null },
    app: { envLoading: false },
    Audio: FakeAudio,
    audioElements: new Map(),
    audioAccessOrder: [],
    PREVIEW_AUDIO_CACHE_LIMIT: 8,
    outputPlayback: { value: {} },
    playingOutputPath: { value: '' },
    convertFileSrc: value => `asset:${value}`,
  }
  const result = vm.runInNewContext(`${code}\n({ syncOutputPreviewAudio })`, context)
  result.syncOutputPreviewAudio(Array.from({ length: 20 }, (_, index) => ({ path: `output-${index}.wav` })))
  assert.equal(context.audioElements.size, 8)
  assert.deepEqual([...context.audioElements.keys()], Array.from({ length: 8 }, (_, index) => `output-${index}.wav`))

  result.syncOutputPreviewAudio([{ path: 'replacement.wav' }])
  assert.deepEqual([...context.audioElements.keys()], ['replacement.wav'])
  assert.deepEqual(context.audioAccessOrder, ['replacement.wav'])
})

test('released audio cannot restore stale playback state', () => {
  const instances = []
  class FakeAudio {
    listeners = new Map()
    duration = 12
    currentTime = 0
    paused = true

    constructor() { instances.push(this) }
    set preload(_value) {}
    set src(_value) {}
    addEventListener(name, callback) { this.listeners.set(name, callback) }
    pause() { this.paused = true }
    removeAttribute(_name) {}
    load() {}
  }
  const context = {
    computed,
    modelsLoaded: { value: true },
    downloadedModels: { value: [] },
    isLoading: { value: false },
    modelError: { value: null },
    app: { envLoading: false },
    Audio: FakeAudio,
    audioElements: new Map(),
    audioAccessOrder: [],
    PREVIEW_AUDIO_CACHE_LIMIT: 8,
    outputPlayback: { value: {} },
    playingOutputPath: { value: '' },
    convertFileSrc: value => `asset:${value}`,
  }
  const result = vm.runInNewContext(`${code}\n({ syncOutputPreviewAudio })`, context)
  result.syncOutputPreviewAudio([{ path: 'old.wav' }])
  const oldAudio = instances[0]
  result.syncOutputPreviewAudio([{ path: 'replacement.wav' }])

  oldAudio.duration = 99
  oldAudio.currentTime = 42
  oldAudio.listeners.get('loadedmetadata')?.()
  oldAudio.listeners.get('timeupdate')?.()
  assert.equal(context.outputPlayback.value['old.wav'], undefined)
  assert.deepEqual([...context.audioElements.keys()], ['replacement.wav'])
})
