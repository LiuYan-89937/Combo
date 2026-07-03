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

export function switchSessionCommand(sessionId: string, mode?: FactoryMode | null): FactoryFrontendCommand {
  return createCommand('switch_session', { session_id: sessionId, mode })
}

export function newSessionCommand(mode?: FactoryMode | null, packageId?: string | null): FactoryFrontendCommand {
  return createCommand('new_session', {
    mode,
    payload: packageId ? { package_id: packageId } : {},
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
  mode?: FactoryMode
  attachments?: RuntimeAttachmentInput[]
  runtimeOptions?: RuntimeMainModelOptions
}

export interface RuntimeMainModelOptions {
  mainModelProfileId?: string | null
}

export function sendMessageCommand(options: SendMessageOptions): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('send_message', {
    request_id: requestId,
    mode: options.mode,
    message: options.message,
    payload: runtimePayload(
      options.attachments ? { attachments: options.attachments } : {},
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
  runtimeOptions?: RuntimeMainModelOptions
): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('run_agent_package', {
    request_id: requestId,
    payload: runtimePayload(
      {
        package_id: packageId,
        message,
        session_id: sessionId,
        ...(attachments && attachments.length > 0 ? { attachments } : {}),
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
  runtimeOptions?: RuntimeMainModelOptions
): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('send_agent_package_message', {
    request_id: requestId,
    payload: runtimePayload(
      {
        package_id: packageId,
        message,
        session_id: sessionId,
        ...(attachments && attachments.length > 0 ? { attachments } : {}),
      },
      runtimeOptions
    ),
  })
}

export function runAgentEvolutionCommand(
  packageId: string,
  message: string,
  attachments?: RuntimeAttachmentInput[],
  runtimeOptions?: RuntimeMainModelOptions
): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('run_agent_evolution', {
    request_id: requestId,
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
  if (!profileId) return payload
  return {
    ...payload,
    user_config: {
      model_profile_overrides: {
        main: profileId,
      },
    },
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

export function resumeInterruptCommand(options: ResumeInterruptOptions): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('resume_interrupt', {
    request_id: requestId,
    payload: options,
  })
}

export function cancelRuntimeRequestCommand(
  reason = 'user_cancelled',
  targetRequestId: string | null = null,
  visibleOutput: Record<string, any> | null = null,
): FactoryFrontendCommand {
  return createCommand('cancel_runtime_request', {
    payload: {
      reason,
      ...(targetRequestId ? { target_request_id: targetRequestId } : {}),
      ...(visibleOutput ? { visible_output: visibleOutput } : {}),
    },
  })
}
