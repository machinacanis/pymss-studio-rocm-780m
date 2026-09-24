import {
  SIMPLE_ENSEMBLE_ALGORITHMS,
  type SimpleDraft,
  type SimpleEnsembleDraft,
  type SimpleStepDraft,
} from '@/utils/workflowSimple'

export type SimpleConnectionSource = 'input' | `${string}.${string}`
export type SimpleConnectionTarget =
  | `step:${string}`
  | `ensemble:${string}:${number}`
  | `save`
  | `save:${string}.${string}`

export type SimpleConnectionCheck =
  | { ok: true }
  | { ok: false; reason: 'missing-source' | 'missing-target' | 'invalid-source' | 'forward-link' | 'self-link' | 'duplicate-source' | 'invalid-save-target' }

export function simpleStepInputTarget(stepId: string): `step:${string}` {
  return `step:${stepId}`
}

export function simpleSaveTarget(stepId: string, stem: string): `save:${string}.${string}` {
  return `save:${stepId}.${stem}`
}

export function simpleEnsembleInputTarget(ensembleId: string, index: number): `ensemble:${string}:${number}` {
  return `ensemble:${ensembleId}:${index}`
}

export function simpleOutputRef(stepId: string, stem: string): `${string}.${string}` {
  return `${stepId}.${stem}`
}

export function simpleSourceStepId(source: string): string {
  const separator = source.indexOf('.')
  return separator > 0 ? source.slice(0, separator) : ''
}

export function simpleSourceStem(source: string): string {
  const separator = source.indexOf('.')
  return separator > 0 ? source.slice(separator + 1) : ''
}

export function updateSimpleEnsembleOutputStem(
  draft: SimpleDraft,
  ensemble: SimpleEnsembleDraft,
  value: string,
): void {
  const nextStem = value.trim()
  ensemble.outputStem = value
  if (!nextStem) return

  const nextSource = simpleOutputRef(ensemble.id, nextStem)
  draft.steps.forEach((step) => {
    if (simpleSourceStepId(step.input).toLowerCase() === ensemble.id.toLowerCase()) {
      step.input = nextSource
    }
  })
}

type ResolvedSimpleSource =
  | { kind: 'step'; step: SimpleStepDraft; stem: string }
  | { kind: 'ensemble'; ensemble: SimpleEnsembleDraft; stem: string }

function resolveSource(draft: SimpleDraft, source: string): ResolvedSimpleSource | null {
  if (source === 'input') return null
  const sourceId = simpleSourceStepId(source)
  const stem = simpleSourceStem(source)
  const step = draft.steps.find(item => item.id === sourceId)
  if (step && stem && step.stems.some(item => item.toLowerCase() === stem.toLowerCase())) {
    return { kind: 'step', step, stem }
  }
  const ensemble = draft.ensembles.find(item => item.id === sourceId)
  if (ensemble && stem && ensemble.outputStem.trim().toLowerCase() === stem.toLowerCase()) {
    return { kind: 'ensemble', ensemble, stem: ensemble.outputStem.trim() }
  }
  return null
}

function ensembleTarget(draft: SimpleDraft, target: string) {
  const match = /^ensemble:(.+):(\d+)$/.exec(target)
  if (!match) return null
  const ensemble = draft.ensembles.find(item => item.id === match[1])
  const index = Number(match[2])
  return ensemble && Number.isInteger(index) && index >= 0 && index < ensemble.inputs.length
    ? { ensemble, index }
    : null
}

export function canConnectSimple(
  draft: SimpleDraft,
  source: string,
  target: SimpleConnectionTarget,
): SimpleConnectionCheck {
  const rawSource = source.trim()
  if (!rawSource) return { ok: false, reason: 'missing-source' }
  const sourceValue = rawSource === 'input' ? null : resolveSource(draft, rawSource)
  if (rawSource !== 'input' && !sourceValue) return { ok: false, reason: 'invalid-source' }

  if (target === 'step:') return { ok: false, reason: 'missing-target' }
  if (target.startsWith('step:')) {
    const targetId = target.slice('step:'.length)
    const targetIndex = draft.steps.findIndex(step => step.id === targetId)
    if (targetIndex < 0) return { ok: false, reason: 'missing-target' }
    if (rawSource === 'input') return { ok: true }
    if (sourceValue?.kind === 'ensemble') {
      for (const input of sourceValue.ensemble.inputs) {
        const dependency = input.source.trim()
        if (dependency === 'input') continue
        const resolvedDependency = resolveSource(draft, dependency)
        if (resolvedDependency?.kind !== 'step') return { ok: false, reason: 'invalid-source' }
        const dependencyIndex = draft.steps.findIndex(step => step.id === resolvedDependency.step.id)
        if (dependencyIndex < 0) return { ok: false, reason: 'invalid-source' }
        if (dependencyIndex >= targetIndex) return { ok: false, reason: 'forward-link' }
      }
      return { ok: true }
    }
    if (sourceValue?.kind !== 'step') return { ok: false, reason: 'invalid-source' }
    const sourceId = simpleSourceStepId(rawSource)
    const sourceIndex = draft.steps.findIndex(step => step.id === sourceId)
    if (sourceIndex < 0) return { ok: false, reason: 'invalid-source' }
    if (sourceId === targetId) return { ok: false, reason: 'self-link' }
    if (sourceIndex >= targetIndex) return { ok: false, reason: 'forward-link' }
    return { ok: true }
  }

  if (target.startsWith('ensemble:')) {
    const resolvedTarget = ensembleTarget(draft, target)
    if (!resolvedTarget) return { ok: false, reason: 'missing-target' }
    if (rawSource !== 'input' && sourceValue?.kind !== 'step') return { ok: false, reason: 'invalid-source' }
    if (resolvedTarget.ensemble.inputs.some((input, index) => index !== resolvedTarget.index && input.source.toLowerCase() === rawSource.toLowerCase())) {
      return { ok: false, reason: 'duplicate-source' }
    }
    return { ok: true }
  }

  if (target === 'save') {
    if (rawSource === 'input') return { ok: false, reason: 'invalid-save-target' }
    if (!sourceValue) return { ok: false, reason: 'invalid-save-target' }
    return { ok: true }
  }
  if (!target.startsWith('save:')) return { ok: false, reason: 'missing-target' }
  if (rawSource === 'input') return { ok: false, reason: 'invalid-save-target' }
  const value = target.slice('save:'.length)
  if (!sourceValue || value.toLowerCase() !== rawSource.toLowerCase()) {
    return { ok: false, reason: 'invalid-save-target' }
  }
  return { ok: true }
}

export function connectSimple(
  draft: SimpleDraft,
  source: string,
  target: SimpleConnectionTarget,
): SimpleConnectionCheck {
  const check = canConnectSimple(draft, source, target)
  if (!check.ok) return check
  if (target.startsWith('step:')) {
    const step = draft.steps.find(item => item.id === target.slice('step:'.length))
    if (step) step.input = source.trim()
    return check
  }
  if (target.startsWith('ensemble:')) {
    const resolvedTarget = ensembleTarget(draft, target)
    if (resolvedTarget) resolvedTarget.ensemble.inputs[resolvedTarget.index].source = source.trim()
    return check
  }
  const value = target === 'save' ? source.trim() : target.slice('save:'.length)
  const sourceId = simpleSourceStepId(value)
  const stem = simpleSourceStem(value)
  const step = draft.steps.find(item => item.id === sourceId)
  if (step) {
    step.save = { ...step.save, [stem]: step.save[stem] || 'Default' }
    step.outputNames = { ...step.outputNames, [stem]: step.outputNames[stem] || '%filename%_%stem%_%model%' }
    return check
  }
  const ensemble = draft.ensembles.find(item => item.id === sourceId)
  if (ensemble && ensemble.outputStem.trim().toLowerCase() === stem.toLowerCase()) {
    ensemble.save = true
    if (!ensemble.outputName.trim()) ensemble.outputName = '%filename%_%stem%_Ensemble'
  }
  return check
}

export function disconnectSimple(draft: SimpleDraft, target: SimpleConnectionTarget): boolean {
  if (target.startsWith('step:')) {
    const step = draft.steps.find(item => item.id === target.slice('step:'.length))
    if (!step) return false
    step.input = ''
    return true
  }
  if (target.startsWith('ensemble:')) {
    const resolvedTarget = ensembleTarget(draft, target)
    if (!resolvedTarget) return false
    resolvedTarget.ensemble.inputs[resolvedTarget.index].source = ''
    return true
  }
  if (!target.startsWith('save:')) return false
  const value = target.slice('save:'.length)
  const sourceId = simpleSourceStepId(value)
  const step = draft.steps.find(item => item.id === sourceId)
  const stem = simpleSourceStem(value)
  if (step && stem && stem in step.save) {
    const nextSave = { ...step.save }
    delete nextSave[stem]
    step.save = nextSave
    return true
  }
  const ensemble = draft.ensembles.find(item => item.id === sourceId)
  if (!ensemble || !ensemble.save || ensemble.outputStem.trim().toLowerCase() !== stem.toLowerCase()) return false
  ensemble.save = false
  return true
}

export function cleanupSimpleDraft(draft: SimpleDraft): void {
  if (!Array.isArray(draft.ensembles)) draft.ensembles = []
  draft.ensembles.forEach((ensemble) => {
    if (!SIMPLE_ENSEMBLE_ALGORITHMS.includes(ensemble.algorithm)) ensemble.algorithm = 'avg_wave'
    ensemble.outputStem = ensemble.outputStem.trim()
    ensemble.outputName = ensemble.outputName.trim() || '%filename%_%stem%_Ensemble'
    const seen = new Set<string>()
    ensemble.inputs = ensemble.inputs.slice(0, 10).map((input) => {
      const source = input.source.trim()
      const resolved = resolveSource(draft, source)
      const sourceKey = source.toLowerCase()
      const validSource = source === 'input' || resolved?.kind === 'step'
      const valid = validSource && !seen.has(sourceKey)
      if (valid) seen.add(sourceKey)
      return {
        source: valid ? source : '',
        weight: Number.isFinite(input.weight) && input.weight > 0 ? input.weight : 1,
      }
    })
    while (ensemble.inputs.length < 2) ensemble.inputs.push({ source: '', weight: 1 })
  })
  draft.steps.forEach((step) => {
    const input = step.input.trim()
    const sourceId = simpleSourceStepId(input)
    const hasPendingEnsembleSource = draft.ensembles.some(ensemble => (
      !ensemble.outputStem
      && ensemble.id.toLowerCase() === sourceId.toLowerCase()
    ))
    if (input !== 'input'
      && !hasPendingEnsembleSource
      && !canConnectSimple(draft, input, simpleStepInputTarget(step.id)).ok) {
      step.input = ''
    }
    const saveByStem = new Map(Object.entries(step.save || {}).map(([stem, value]) => [stem.toLowerCase(), value]))
    const nextSave: Record<string, string> = {}
    step.stems.forEach((stem) => {
      const value = saveByStem.get(stem.toLowerCase())
      if (value?.trim()) nextSave[stem] = value
    })
    step.save = nextSave
    const namesByStem = new Map(Object.entries(step.outputNames || {}).map(([stem, value]) => [stem.toLowerCase(), value]))
    const nextNames: Record<string, string> = {}
    step.stems.forEach((stem) => {
      const value = namesByStem.get(stem.toLowerCase())
      if (value?.trim()) nextNames[stem] = value
    })
    step.outputNames = nextNames
  })
}
