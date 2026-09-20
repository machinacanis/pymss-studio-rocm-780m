import type { AudioToolDefinition, AudioToolKey } from './types'

export const MACOS_HIDDEN_AUDIO_TOOL_IDS: ReadonlySet<AudioToolKey> = new Set(['asr'])

export function isAudioToolAvailable(tool: AudioToolDefinition, isMacOS: boolean) {
  if (tool.hidden) return false
  return !isMacOS || !MACOS_HIDDEN_AUDIO_TOOL_IDS.has(tool.id)
}
