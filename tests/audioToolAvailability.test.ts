import assert from 'node:assert/strict'
import test from 'node:test'
import { isAudioToolAvailable, MACOS_HIDDEN_AUDIO_TOOL_IDS } from '../src/features/audio-tools/availability.ts'
import type { AudioToolDefinition } from '../src/features/audio-tools/types.ts'

function tool(id: AudioToolDefinition['id'], hidden = false) {
  return { id, hidden } as AudioToolDefinition
}

test('macOS hides FunASR while other platforms keep it available', () => {
  assert.equal(MACOS_HIDDEN_AUDIO_TOOL_IDS.has('asr'), true)
  assert.equal(isAudioToolAvailable(tool('asr'), true), false)
  assert.equal(isAudioToolAvailable(tool('asr'), false), true)
  assert.equal(isAudioToolAvailable(tool('midi'), true), true)
})

test('globally hidden audio tools stay hidden on every platform', () => {
  assert.equal(isAudioToolAvailable(tool('convert', true), false), false)
  assert.equal(isAudioToolAvailable(tool('convert', true), true), false)
})
