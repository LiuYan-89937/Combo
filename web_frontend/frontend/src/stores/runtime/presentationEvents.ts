import type { RuntimeFrontendEvent, RuntimeViewState } from '@/types/protocol'
import {
  applyContextActivityEvent,
  applyKnowledgeActivityEvent,
  applyMemoryActivityEvent,
  applyRuntimeActivityEvent,
  applySchedulerActivityEvent,
  recordDebugEvent,
} from './activityMutations'
import {
  applyNodeCompleted,
  applyNodeFailed,
  applyNodeProgress,
  applyNodeStarted,
  applyStageCompleted,
  applyStageFailed,
  applyStageStarted,
} from './graphMutations'
import {
  applyMessageCompleted,
  applyMessagePartCompleted,
  applyMessagePartDelta,
  applyMessageStarted,
} from './messageMutations'
import {
  applyModelCallStarted,
  applyModelMessageCompleted,
  applyModelReasoningCompleted,
  applyModelReasoningDelta,
  applyModelStreamDelta,
} from './modelMutations'
import { applyExtensionsEvent, applyWorkspaceEvent } from './resourceMutations'
import { applyToolLifecycleEvent } from './toolMutations'

/** Pure view projections. Request ownership, approvals and session transitions stay in the store. */
export function applyPresentationEvent(state: RuntimeViewState, event: RuntimeFrontendEvent): boolean {
  switch (event.event_type) {
    case 'stage_started': applyStageStarted(state, event); return true
    case 'stage_completed': applyStageCompleted(state, event); return true
    case 'stage_failed': applyStageFailed(state, event); return true
    case 'node_started': applyNodeStarted(state, event); return true
    case 'node_progress': applyNodeProgress(state, event); return true
    case 'node_completed': applyNodeCompleted(state, event); return true
    case 'node_failed': applyNodeFailed(state, event); return true
    case 'runtime_activity_updated': applyRuntimeActivityEvent(state, event); return true
    case 'message_started': applyMessageStarted(state, event); return true
    case 'message_part_delta': applyMessagePartDelta(state, event); return true
    case 'message_part_completed': applyMessagePartCompleted(state, event); return true
    case 'message_completed': applyMessageCompleted(state, event); return true
    case 'model_call_started': applyModelCallStarted(state, event); return true
    case 'model_reasoning_delta': applyModelReasoningDelta(state, event); return true
    case 'model_reasoning_completed': applyModelReasoningCompleted(state, event); return true
    case 'model_stream_delta': applyModelStreamDelta(state, event); return true
    case 'model_message_completed': applyModelMessageCompleted(state, event); return true
    case 'tool_call_proposed': applyToolLifecycleEvent(state, event, 'proposed'); return true
    case 'tool_call_started':
    case 'tool_call_output_delta': applyToolLifecycleEvent(state, event, 'started'); return true
    case 'tool_call_completed': applyToolLifecycleEvent(state, event, 'completed'); return true
    case 'tool_call_cancelled': applyToolLifecycleEvent(state, event, 'cancelled'); return true
    case 'tool_call_failed':
    case 'tool_contract_invalid': applyToolLifecycleEvent(state, event, 'failed'); return true
    case 'tool_observation_available': applyToolLifecycleEvent(state, event, 'observed'); return true
    case 'extension_configs_listed':
    case 'extension_config_updated':
    case 'extension_config_tested':
    case 'extension_config_test_output_delta':
    case 'extension_skillhub_result': applyExtensionsEvent(state, event); return true
    case 'debug_patch': recordDebugEvent(state, event); return true
  }

  if (event.event_type.startsWith('context_')) applyContextActivityEvent(state, event)
  else if (event.event_type.startsWith('memory_')) applyMemoryActivityEvent(state, event)
  else if (event.event_type.startsWith('knowledge_')) applyKnowledgeActivityEvent(state, event)
  else if (event.event_type.startsWith('workspace_')) applyWorkspaceEvent(state, event)
  else if (event.event_type.startsWith('scheduler_')) applySchedulerActivityEvent(state, event)
  else return false
  return true
}
