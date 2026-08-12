export type ComboMascotState = 'idle' | 'thinking' | 'working' | 'waiting' | 'complete' | 'error'
export type ComboCharacter = 'paired' | 'lead' | 'companion'
export type ComboCharacterAction = 'idle' | 'running' | 'jumping'
export type ComboAnimationAction = ComboMascotState | ComboCharacterAction

export interface ComboAnimationDefinition {
  frameCount: number
  defaultFps: number
  width: number
  height: number
}

export const COMBO_MASCOT_ANIMATIONS = {
  paired: {
    idle: { frameCount: 6, defaultFps: 4, width: 192, height: 208 },
    thinking: { frameCount: 6, defaultFps: 4, width: 192, height: 208 },
    waiting: { frameCount: 6, defaultFps: 4, width: 192, height: 208 },
    complete: { frameCount: 4, defaultFps: 4, width: 192, height: 208 },
    error: { frameCount: 8, defaultFps: 5, width: 192, height: 208 },
  },
  lead: {
    idle: { frameCount: 6, defaultFps: 4, width: 192, height: 208 },
    running: { frameCount: 8, defaultFps: 7, width: 192, height: 208 },
    jumping: { frameCount: 5, defaultFps: 5, width: 192, height: 208 },
  },
  companion: {
    idle: { frameCount: 6, defaultFps: 4, width: 192, height: 208 },
    running: { frameCount: 8, defaultFps: 7, width: 192, height: 208 },
    jumping: { frameCount: 5, defaultFps: 5, width: 192, height: 208 },
  },
} as const satisfies Record<ComboCharacter, Partial<Record<ComboAnimationAction, ComboAnimationDefinition>>>

export function getComboAnimation(
  character: ComboCharacter,
  action: ComboAnimationAction,
): ComboAnimationDefinition {
  const definition = COMBO_MASCOT_ANIMATIONS[character][action as keyof typeof COMBO_MASCOT_ANIMATIONS[typeof character]]
  if (!definition) throw new Error(`Unknown Combo animation: ${character}/${action}`)
  return definition
}

export function getComboMascotFrameSource(
  character: ComboCharacter,
  action: ComboAnimationAction,
  frameIndex: number,
) {
  const frameNumber = String(frameIndex + 1).padStart(2, '0')
  return `/brand/combo/frames/${character}/${action}/frame-${frameNumber}.png`
}
