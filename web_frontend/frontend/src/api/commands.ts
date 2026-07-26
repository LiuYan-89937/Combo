/**
 * API 层 - 命令封装
 * 提供类型安全的命令发送接口
 */

import type { FactoryFrontendCommand, FactoryMode, RuntimeAttachmentInput } from '@/types/protocol'

let requestIdCounter = 0

export function generateRequestId(): string {
  return `web-${Date.now()}-${++requestIdCounter}-${Math.random().toString(36).slice(2, 9)}`
}

export function createCommand(
  type: FactoryFrontendCommand['type'],
  options: Partial<Omit<FactoryFrontendCommand, 'type'>> = {}
): FactoryFrontendCommand {
  return {
    type,
    request_id: options.request_id || null,
    session_id: options.session_id || null,
    resume_latest: options.resume_latest || false,
    mode: options.mode || null,
    message: options.message || null,
    payload: options.payload || {},
    options: options.options || {},
  }
}

// ============= Session Commands =============

export function startSessionCommand(
  resumeLatest = false,
  mode?: FactoryMode | null,
  packageId?: string | null
): FactoryFrontendCommand {
  return createCommand('start_session', {
    resume_latest: resumeLatest,
    mode,
    payload: packageId ? { package_id: packageId } : {},
  })
}

export function listSessionsCommand(): FactoryFrontendCommand {
  return createCommand('list_sessions')
}

export function switchSessionCommand(
  sessionId: string,
  mode?: FactoryMode | null,
  collaborationId?: string | null,
): FactoryFrontendCommand {
  return createCommand('switch_session', {
    session_id: sessionId,
    mode,
    payload: collaborationId ? { collaboration_id: collaborationId } : {},
  })
}

export function newSessionCommand(
  mode?: FactoryMode | null,
  packageId?: string | null,
  collaborationId?: string | null,
): FactoryFrontendCommand {
  return createCommand('new_session', {
    mode,
    payload: {
      ...(packageId ? { package_id: packageId } : {}),
      ...(collaborationId ? { collaboration_id: collaborationId } : {}),
    },
  })
}

export function deleteSessionCommand(sessionId: string, mode?: FactoryMode | null): FactoryFrontendCommand {
  return createCommand('delete_session', {
    session_id: sessionId,
    mode,
    payload: { session_id: sessionId, mode },
  })
}

export function setModeCommand(mode: FactoryMode): FactoryFrontendCommand {
  return createCommand('set_mode', { mode })
}

// ============= Message Commands =============

export interface SendMessageOptions {
  message: string
  sessionId?: string | null
  mode?: FactoryMode
  attachments?: RuntimeAttachmentInput[]
  runtimeOptions?: RuntimeMainModelOptions
  displayUserInput?: string | null
}

export interface RuntimeMainModelOptions {
  mainModelProfileId?: string | null
  reasoningIntensity?: number | null
  requestTimeoutSeconds?: number | null
  userConfig?: Record<string, unknown> | null
}

export function sendMessageCommand(options: SendMessageOptions): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('send_message', {
    request_id: requestId,
    session_id: options.sessionId,
    mode: options.mode,
    message: options.message,
    payload: runtimePayload(
      {
        ...(options.attachments ? { attachments: options.attachments } : {}),
        ...(options.displayUserInput ? { display_user_input: options.displayUserInput } : {}),
      },
      options.runtimeOptions
    ),
  })
}

// ============= Agent Package Runtime Commands =============

export function runAgentPackageCommand(
  packageId: string,
  message: string,
  sessionId?: string,
  attachments?: RuntimeAttachmentInput[],
  runtimeOptions?: RuntimeMainModelOptions,
  displayUserInput?: string | null
): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('run_agent_package', {
    request_id: requestId,
    session_id: sessionId,
    payload: runtimePayload(
      {
        package_id: packageId,
        message,
        session_id: sessionId,
        ...(attachments && attachments.length > 0 ? { attachments } : {}),
        ...(displayUserInput ? { display_user_input: displayUserInput } : {}),
      },
      runtimeOptions
    ),
  })
}

export function sendAgentPackageMessageCommand(
  packageId: string,
  message: string,
  sessionId?: string,
  attachments?: RuntimeAttachmentInput[],
  runtimeOptions?: RuntimeMainModelOptions,
  displayUserInput?: string | null
): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('send_agent_package_message', {
    request_id: requestId,
    session_id: sessionId,
    payload: runtimePayload(
      {
        package_id: packageId,
        message,
        session_id: sessionId,
        ...(attachments && attachments.length > 0 ? { attachments } : {}),
        ...(displayUserInput ? { display_user_input: displayUserInput } : {}),
      },
      runtimeOptions
    ),
  })
}

export function runAgentEvolutionCommand(
  packageId: string,
  message: string,
  attachments?: RuntimeAttachmentInput[],
  runtimeOptions?: RuntimeMainModelOptions,
  sessionId?: string | null,
): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('run_agent_evolution', {
    request_id: requestId,
    session_id: sessionId,
    payload: runtimePayload(
      {
        package_id: packageId,
        ...(attachments && attachments.length > 0 ? { attachments } : {}),
      },
      runtimeOptions
    ),
    message,
  })
}

function runtimePayload(payload: Record<string, unknown>, runtimeOptions?: RuntimeMainModelOptions): Record<string, unknown> {
  const profileId = String(runtimeOptions?.mainModelProfileId || '').trim()
  const reasoningIntensity = runtimeOptions?.reasoningIntensity
  const requestTimeoutSeconds = runtimeOptions?.requestTimeoutSeconds
  const payloadUserConfig = payload.user_config && typeof payload.user_config === 'object'
    ? payload.user_config as Record<string, unknown>
    : null
  const extraUserConfig = runtimeOptions?.userConfig && typeof runtimeOptions.userConfig === 'object'
    ? runtimeOptions.userConfig
    : null
  const hasRuntimeRequest = typeof requestTimeoutSeconds === 'number'
  const hasUserConfig = Boolean(profileId || reasoningIntensity != null || extraUserConfig || payloadUserConfig)
  if (!hasRuntimeRequest && !hasUserConfig) return payload
  return {
    ...payload,
    ...(hasRuntimeRequest
      ? {
          runtime_request: {
            timeout_seconds: Math.max(0, Math.round(requestTimeoutSeconds as number)),
          },
        }
      : {}),
    ...(hasUserConfig
      ? {
          user_config: {
            ...(payloadUserConfig || {}),
            ...(extraUserConfig || {}),
            ...(profileId
              ? {
                  model_profile_overrides: {
                    ...((extraUserConfig?.model_profile_overrides && typeof extraUserConfig.model_profile_overrides === 'object')
                      ? extraUserConfig.model_profile_overrides as Record<string, unknown>
                      : {}),
                    main: profileId,
                  },
                }
              : {}),
            ...(typeof reasoningIntensity === 'number'
              ? { reasoning_intensity: reasoningIntensity }
              : {}),
          },
        }
      : {}),
  }
}

// ============= Interrupt Commands =============

export interface ResumeInterruptOptions {
  action: 'approve' | 'deny' | 'trust_tool' | 'revise' | 'answer'
  approved?: boolean
  trust_scope?: 'tool' | 'tool_group'
  revision_guidance?: string
  input_text?: string
  answer?: string
  message?: string
  [key: string]: any
}

export function resumeInterruptCommand(
  options: ResumeInterruptOptions,
  sessionId?: string | null,
  runtimeOptions?: RuntimeMainModelOptions,
): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('resume_interrupt', {
    request_id: requestId,
    session_id: sessionId,
    payload: runtimePayload(options, runtimeOptions),
  })
}

export interface CancelRuntimeRequestOptions {
  reason?: string
  targetRequestId?: string | null
  sessionId?: string | null
  mode?: FactoryMode | null
  packageId?: string | null
  visibleOutput?: Record<string, any> | null
}

export function cancelRuntimeRequestCommand(options: CancelRuntimeRequestOptions = {}): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('cancel_runtime_request', {
    request_id: requestId,
    session_id: options.sessionId,
    mode: options.mode,
    payload: {
      reason: options.reason || 'user_cancelled',
      ...(options.targetRequestId ? { target_request_id: options.targetRequestId } : {}),
      ...(options.packageId ? { package_id: options.packageId } : {}),
      ...(options.visibleOutput ? { visible_output: options.visibleOutput } : {}),
    },
  })
}
