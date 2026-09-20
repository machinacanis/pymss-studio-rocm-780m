<script setup lang="ts">
import { computed, onMounted, provide, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { audioTools } from '@/features/audio-tools/registry'
import { isAudioToolAvailable } from '@/features/audio-tools/availability'
import { audioToolRuntimeKey, createAudioToolRuntime } from '@/features/audio-tools/runtime'
import { loadAudioToolsState, updateAudioToolsState } from '@/features/audio-tools/state'
import type { AudioToolCategory, AudioToolKey } from '@/features/audio-tools/types'
import { useAppStore } from '@/stores/app'
import { detectRuntimePlatform } from '@/utils/runtime'
defineOptions({ name: 'ToolsView' })
const { t } = useI18n()
const app = useAppStore()
const runtime = createAudioToolRuntime()
provide(audioToolRuntimeKey, runtime)
const activeTool = ref<AudioToolKey>('convert')
const isMacOS = computed(() => detectRuntimePlatform(app.runtimeInfo).isMac)
const visibleAudioTools = computed(() => audioTools.filter(tool => isAudioToolAvailable(tool, isMacOS.value)))
const activeDefinition = computed(() => visibleAudioTools.value.find(tool => tool.id === activeTool.value) || visibleAudioTools.value[0] || audioTools[0])
const mobileToolOptions = computed(() => visibleAudioTools.value
  .map(tool => ({ label: t(tool.titleKey), value: tool.id })))
const categories: Array<{ id: AudioToolCategory; titleKey: string }> = [
  { id: 'convert', titleKey: 'tools.categoryConvert' },
  { id: 'analyze', titleKey: 'tools.categoryAnalyze' },
  { id: 'recognize', titleKey: 'tools.categoryRecognize' },
  { id: 'edit', titleKey: 'tools.categoryEdit' },
]
const toolsByCategory = (category: AudioToolCategory) => visibleAudioTools.value.filter(tool => tool.category === category)
let restored = false
onMounted(async () => { const stored = await loadAudioToolsState(); if (stored?.activeTool && visibleAudioTools.value.some(tool => tool.id === stored.activeTool)) activeTool.value = stored.activeTool; restored = true; await runtime.start() })
watch(visibleAudioTools, tools => { if (!tools.some(tool => tool.id === activeTool.value) && tools[0]) activeTool.value = tools[0].id }, { immediate: true })
watch(activeTool, value => { if (restored) void updateAudioToolsState({ activeTool: value }) })
</script>
<template><div class="page tools-page audio-tools-page"><div class="page-header-compact"><div><h1>{{ t('tools.title') }}</h1><p>{{ t('tools.subtitle') }}</p></div></div>
  <n-select v-model:value="activeTool" class="audio-tools-mobile-select" :options="mobileToolOptions" />
  <div class="audio-tools-workspace"><nav class="audio-tools-nav" :aria-label="t('tools.toolNavigation')"><section v-for="category in categories" :key="category.id"><strong>{{ t(category.titleKey) }}</strong><button v-for="tool in toolsByCategory(category.id)" :key="tool.id" type="button" :class="{ active: activeTool === tool.id }" @click="activeTool = tool.id"><n-icon :component="tool.icon" /><span>{{ t(tool.titleKey) }}</span></button></section></nav>
    <main class="audio-tools-content"><KeepAlive><component :is="activeDefinition.component" :key="activeDefinition.id" /></KeepAlive></main>
  </div>
</div></template>
<style src="@/features/audio-tools/styles.css"></style>
