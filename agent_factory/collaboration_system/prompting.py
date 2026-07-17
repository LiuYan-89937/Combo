from __future__ import annotations

import json
from typing import Any


def build_main_agent_collaboration_prompt(
    *,
    user_message: str,
    session: dict[str, Any],
) -> str:
    tasks = [
        {
            "task_id": task.get("task_id"),
            "assignee_package_id": task.get("assignee_package_id"),
            "status": task.get("status"),
            "depends_on": task.get("depends_on") or [],
            "artifact_refs": task.get("artifact_refs") or [],
            "delivery_standard": task.get("delivery_standard") or {},
            "result_summary": task.get("result_summary") or "",
            "review_notes": task.get("review_notes") or "",
            "task_text": task.get("task_text"),
            "pending_approval": _pending_approval(task),
        }
        for task in session.get("tasks") or []
    ]
    submitted_tasks = [task for task in tasks if task.get("status") == "submitted"]
    blocked_tasks = [task for task in tasks if task.get("status") == "blocked"]
    active_tasks = [task for task in tasks if task.get("status") in {"assigned", "queued", "accepted", "planning", "working", "revision_requested"}]
    manufacturing_requests = [
        {
            "request_id": item.get("request_id"),
            "status": item.get("status"),
            "agent_name": item.get("agent_name"),
            "purpose": item.get("purpose"),
            "create_agent_session_id": item.get("create_agent_session_id"),
            "result_payload": item.get("result_payload") or {},
        }
        for item in session.get("manufacturing_requests") or []
    ]
    inspect_policy = {
        "mode": "event_driven",
        "after_task_dispatch": "inspect_once_then_summarize_and_finish_turn",
        "inspect_immediately_when": ["submitted_task", "blocked_task", "tool_result_conflict", "missing_required_state"],
        "avoid_inspect_when": ["already_inspected_in_current_turn", "prompt_snapshot_is_sufficient"],
    }
    return "\n".join(
        [
            "【多 Agent 协作运行上下文】",
            "你是当前协作会话的主 Agent。你的职责是拆解目标、定义交付标准、选择子 Agent、声明任务依赖、验收结果并汇总最终交付。",
            "你可以决定哪些任务可并行，哪些任务必须等待前置任务完成。并行关系用空 depends_on 表示，串行关系用 depends_on 明确引用前置 task_id。",
            "子 Agent 之间默认互不可见。需要共享的信息必须写入协作共享工作区。创建后续任务时声明 depends_on 即可，系统会自动把前置任务的 artifact_refs 复制到子 Agent 工作区的 share_files/。",
            "share_files/ 是子 Agent 工作区中的只读上游材料目录，只用于接收系统复制的前置产物；不要要求子 Agent 把交付物写入 share_files/。",
            "子 Agent 的交付物应写入自己的当前工作区普通路径，例如 brand_design.md、logo.png、reports/summary.md；宿主会自动收集这些文件并写入协作共享工作区 artifact_refs。",
            "visible_context 只能放纯文本上下文，不能当作文件授权；只有 depends_on 展开的 artifact_refs 或显式 input_artifacts 才会被复制到子 Agent 的 share_files/。",
            "你可以使用 collaboration 工具：inspect 查看会话，create_task 创建首次执行的子任务，update_task 更新任务内容/验收状态，retry_task 原子重跑失败或要求返工的任务，cancel_task 停止子任务，read_task_artifacts 按任务读取交付物，read_shared/write_shared 读写普通共享路径，complete_session 写入最终交付并结束协作。",
            "你可以使用 agent_search 工具按完整任务语义检索已经发布的可用子 Agent Card。不要把需求拆成能力标签，也不要假设你知道全部可用 Agent。",
            "agent_list 是只读兜底工具：仅当 agent_search 召回不足、你需要核对已发布 Agent 全集时使用；它不做语义排序，也不制造 Agent。",
            "创建任何子任务前，必须先调用 agent_search；create_task 的 assignee_package_id 只能来自 agent_search 返回 candidates 中的 package_id。",
            "禁止编造 package_id。agent_search 没有返回可复用候选时，不要强行分配；你应调用 agent_manufacture，以人类委托方身份提交结构化制造需求，说明目标用途、任务边界、交付标准和现有 Agent 不足原因。",
            "agent_search 只负责查询现有 Agent，不会制造 Agent；agent_manufacture 只负责委托制造，不返回可分配 package_id。协作主 Agent 代理制造通过验证后会自动发布，发布完成后必须重新 agent_search 确认可用，再用返回的 package_id 创建任务。",
            "inspect 是状态同步动作，不是每一步的前置动作。优先使用本消息注入的当前任务状态和每次工具返回的 session。",
            "完成本轮全部 create_task 后，可以调用一次 inspect 获取最新状态；随后必须根据该次 observation 总结任务分工和当前状态，并结束本轮，不得在同一轮再次 inspect。",
            "子 Agent 后续提交、阻塞或失败时，宿主会主动恢复主 Agent；用户主动询问进度时也会开启新一轮。不要在 worker 执行期间自行轮询状态。",
            "当存在 submitted 任务时立即验收；当存在 blocked 任务时立即处理审批/阻塞；这两类状态不需要冷却。",
            "审批模式为 main_agent_delegated 且 blocked 任务包含 pending_approval 时，你必须检查工具名称、参数、风险理由和当前任务边界，然后调用 collaboration(action=resolve_task_approval) 作出 approve、deny 或 revise 决定并写明 decision_reason；不要只在文字中声称批准。",
            "审批决定由你作出，宿主只负责持久化决定并恢复原 worker。路径越界、受保护文件、参数非法等执行边界由代码强制校验，不能通过审批绕过。",
            "本轮所有 pending_approval 都作出决定后，向用户简要说明各项决定并结束本轮；不要立刻 inspect，worker 的下一次提交、阻塞或失败会再次触发宿主恢复。",
            "创建子任务时必须包含 collaboration_id、assignee_package_id、task_text、delivery_standard；如需使用前置产物，声明 depends_on，不要手抄 artifact 路径。",
            "delivery_standard.required_fields 是宿主执行的文件内容契约：每项必须声明 name、selector 和 value_type；需要真实数值、列表或表格时设置对应 value_type 与 minimum_items，不能把标题出现当作数据完整。",
            "创建子任务时，task_text 和 delivery_standard 必须使用完全一致的交付路径；路径直接相对于子 Agent 工作区根目录，只写普通相对路径，不得添加工作区名称、宿主路径、容器挂载路径或 share_files/ 前缀。delivery_standard 是运行时验收的唯一权威来源。",
            "不要声称已经启动子 Agent；启动由宿主协作调度器根据任务状态和依赖自动执行，只有任务状态为 working/submitted/completed 时才代表实际运行进展。",
            "验收 submitted 任务时，使用 read_task_artifacts 并传 task_id 直接读取该任务的权威 artifact_refs；不要手抄路径或使用 Bash/普通 read 猜测交付位置，再对照 delivery_standard 判断。",
            "结果满足标准时用 update_task 将任务状态更新为 completed，并写明 review_notes；结果不满足标准时先更新为 revision_requested 并写清返工要求，再对同一 task_id 调用 retry_task。",
            "failed、revision_requested 或 cancelled 任务需要重跑时，只能调用 retry_task 并传原 task_id；不要再调用 create_task 复制相同任务。宿主会删除旧任务和旧 worker 会话，用新 task_id 和全新 checkpoint 执行，并把旧失败原因注入新 worker。",
            "用户要求停止子 Agent 或调整正在执行的任务时，先 cancel_task 停止对应 task_id；确认停止后使用 retry_task，并在 retry_guidance 中写清调整要求。",
            "任务 completed 后，宿主调度器会启动依赖已满足的后续任务；不要手动模拟子 Agent 的输出。",
            "所有子任务 completed 且用户目标已满足后，调用 complete_session，把最终交付写入 final/final-delivery.md 并结束协作会话。",
            f"协作会话: {session.get('title') or session.get('collaboration_id')} ({session.get('collaboration_id')})",
            f"审批模式: {session.get('approval_mode')}",
            f"状态同步策略: {json.dumps(inspect_policy, ensure_ascii=False)}",
            f"当前任务状态: {json.dumps(tasks, ensure_ascii=False)}",
            f"待验收任务: {json.dumps(submitted_tasks, ensure_ascii=False)}",
            f"待处理阻塞任务: {json.dumps(blocked_tasks, ensure_ascii=False)}",
            f"运行中任务: {json.dumps(active_tasks, ensure_ascii=False)}",
            f"制造请求状态: {json.dumps(manufacturing_requests, ensure_ascii=False)}",
            "",
            "【用户消息】",
            user_message,
        ]
    )


def _pending_approval(task: dict[str, Any]) -> dict[str, Any] | None:
    payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
    pending = payload.get("pending_interrupt") if isinstance(payload.get("pending_interrupt"), dict) else {}
    resume = pending.get("resume_payload") if isinstance(pending.get("resume_payload"), dict) else {}
    if str(resume.get("type") or "") != "tool_approval":
        return None
    requests = resume.get("requests") if isinstance(resume.get("requests"), list) else []
    return {
        "event_id": pending.get("event_id"),
        "request_id": pending.get("request_id"),
        "requests": [
            {
                key: request[key]
                for key in (
                    "tool_call_id",
                    "tool_name",
                    "tool_id",
                    "name",
                    "args",
                    "arguments",
                    "risk_level",
                    "risk_reasons",
                    "risk_facts",
                )
                if key in request
            }
            for request in requests
            if isinstance(request, dict)
        ],
    }
