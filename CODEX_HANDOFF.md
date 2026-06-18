# Codex Handoff Notes

Date: 2026-06-18  
Branch: `main`  
Remote: `origin https://github.com/LiuYan-89937/FastAgentFactory.git`

This document is written for the next Codex instance that will continue the work on another machine. Treat the current repository state as authoritative; inspect the worktree before acting.

## Working Rules From The User

- Do not make patch-style fixes that only silence one observed error.
- Reduce rule-based or regex-like special casing.
- Do not add business hardcoding.
- Do not run specialized business examples unless the user explicitly allows it.
- Syntax/static checks are allowed and preferred by default.
- Prefer existing project structures and lower coupling.
- Clean old unused code when replacing a chain.
- For create-agent and RuntimeKernel, the desired direction is simple ReAct-style control: prompt plus tool observations, with the LLM deciding the flow where appropriate.

## Current High-Level State

The previous goal was ended at the user's request so they can run real-chain tests. Code-level static checks were completed for the major areas, but real runtime validation is still expected from the user.

The current direction is:

1. `react_agent` is the primary default pattern.
2. `plan_and_execute` is the second built-in pattern.
3. Create-agent manufacturing should stay lightweight:
   - code creates the empty AgentPackage scaffold;
   - LLM edits or calls deterministic authoring tools;
   - LLM explicitly calls validation;
   - final publish remains gated by validation and user confirmation.
4. Package tools should be verified by real probe execution, preferably inside the same Docker/runtime shape as a published agent.
5. Frontend rendering should consume unified runtime events rather than guessing from raw internal state.

## Important Recent Work

### Runtime Session / Trace / Stdio

Main files:

- `agent_factory/runtime_kernel/session.py`
- `agent_factory/package_runtime/session_turns.py`
- `agent_factory/trace_system/references.py`
- `agent_factory/package_runtime/core.py`
- `agent_factory/agent_runtime_bridge/stdio_server.py`
- `agent_factory/factory_graph/frontend_bridge/stdio_server.py`
- `agent_factory/factory_graph/frontend_bridge/agent_package_runtime.py`

Current behavior:

- Agent sessions now store user-visible turn summaries:
  - `user_input`
  - `final_answer`
  - `status`
  - `created_at`
  - `index`
  - `trace_ref`
- Runtime refs point to runtime workspace areas:
  - sessions
  - checkpoints
  - tool outputs
  - state
  - memory
  - trace
- Stdio writers close quietly after `BrokenPipeError` / `EPIPE` and avoid secondary error spam.
- Session root handling was tightened:
  - `/runtime/...` and `.agent_runtime/...` resolve into the runtime workspace.
  - relative package paths must remain inside package root.
  - arbitrary absolute session paths are rejected.

Static checks already run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/fastagentfactory_pycache .venv/bin/python -m py_compile \
  agent_factory/runtime_kernel/session.py \
  agent_factory/package_runtime/session_turns.py \
  agent_factory/trace_system/references.py \
  agent_factory/package_runtime/core.py \
  agent_factory/agent_runtime_bridge/stdio_server.py \
  agent_factory/factory_graph/frontend_bridge/stdio_server.py \
  agent_factory/factory_graph/frontend_bridge/agent_package_runtime.py
```

Also verified with small static scripts:

- session root path safety
- session turn and trace ref shape
- BrokenPipe writer behavior

Still needs real validation:

- Run a published child agent.
- Confirm `.agentfactory/agent_runtime/<agent_id>/sessions/*.json` contains turns.
- Continue the same session.
- Confirm frontend disconnect/cancel does not produce BrokenPipe runtime spam.

### Plan-and-Execute Pattern

Main files:

- `agent_factory/runtime_kernel/patterns/builtins/plan_and_execute.yaml`
- `agent_factory/runtime_kernel/activation.py`
- `agent_factory/runtime_kernel/nodes/standard/intent_gate.py`
- `agent_factory/runtime_kernel/patterns/validator.py`
- `agent_factory/create_agent/authoring_tool.py`
- `agent_factory/create_agent/validator.py`

Current design:

```text
ingress
-> intent_gate
-> planner <-> tool_exec
-> executor <-> tool_exec
-> final_answer
-> commit
-> finalize
```

Intent gate is intended to prevent meaningless workflow execution for inputs like `你好`.

Responsibilities:

- `planner`: only `runtime_plan`
- `executor`: `runtime_plan` plus business tools
- `final_answer`: no tools
- activation config is required:
  - `workflow_goal`
  - `start_when`
  - `ask_when_missing`

Still needs real validation:

- Create or run a Plan-and-Execute package.
- Send `你好`.
- Confirm it does not call business tools or invent a paper path.
- Confirm meaningful task input enters planner correctly.

### Package Tool Probe

Main files:

- `agent_factory/create_agent/probe_tool.py`
- `agent_factory/create_agent/docker_probe_runner.py`
- `agent_factory/create_agent/package_paths.py`
- `agent_factory/create_agent/validation_state.py`
- `agent_factory/factory_graph/frontend_bridge/agent_runtime_launcher.py`
- `agent_factory/tooling/compiler.py`

Current behavior:

- Probe uses package digest that excludes runtime/private state such as `.factory`, `.agent_runtime`, caches, and pyc.
- Docker probe is intended to run close to published-agent shape:
  - package mounted to `/package:ro`
  - artifacts mounted to `/artifacts:rw`
  - workdir mounted to `/workdir:rw`
  - runtime mounted to `/runtime:rw`
  - extensions mounted to `/runtime/extensions:rw`
- Probe runner uses:
  - `PackageToolProvider`
  - `ToolCompiler`
  - `ToolExecutionGateway`
  - `ensure_dependencies`
  - `ToolOutputStore(RUNTIME_ROOT / "tool_outputs")`

Static checks already run:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/fastagentfactory_pycache .venv/bin/python -m py_compile \
  agent_factory/create_agent/docker_probe_runner.py \
  agent_factory/create_agent/probe_tool.py \
  agent_factory/factory_graph/frontend_bridge/agent_runtime_launcher.py \
  agent_factory/tooling/compiler.py
```

Also verified with small static scripts:

- Docker runtime/probe command construction.
- Docker probe runner resource mapping.

Still needs real validation:

- Build or confirm Docker image `agentfactory-runtime-python:3.12`.
- Manufacture a package tool.
- Probe it.
- Confirm missing dependency, path error, schema/envelope error, and success-path evidence behave as expected.
- Confirm full validation does not report fresh probe as stale.

### Deterministic Create-Agent Authoring

Main file:

- `agent_factory/create_agent/authoring_tool.py`

Current direction:

LLM should not hand-edit scattered cross-file contracts when a deterministic authoring action exists.

Important authoring actions:

- `set_identity`
- `configure_pattern_assembly`
- `upsert_package_tool`
- `remove_package_tool`
- `upsert_scheduler_seed`
- `upsert_resources`
- `upsert_knowledge_file`
- `upsert_state`
- `reset_contract`
- `materialize_mcp_inheritance`

The package tool action should update all relevant surfaces in one coherent operation:

- `tools/<id>/manifest.json`
- `tools/<id>/tool.py`
- `agent_package.json.tools`
- `contracts/tools.json`
- `contracts/dependencies.json`
- `assembly_spec.json` tool access

Known intended behavior:

- If generated tool code has third-party imports, require `python_requirements`.
- Scheduler seed must be written as `config.seeds`, not top-level `seeds`.
- Plan-and-Execute assembly should write activation and node bindings through the authoring tool.

Still needs real validation:

- During create-agent manufacturing, observe whether the LLM actually uses authoring tools instead of manual scattered writes.
- If it still hand-edits cross-file contracts, update prompt/skills to steer toward authoring tools without business hardcoding.

### Unified Frontend Runtime Events

Main files:

- `agent_factory/factory_graph/frontend_bridge/event_normalizer.py`
- `agent_factory/runtime_kernel/adapters/model.py`
- `cli/src/state/runtimeStore.ts`
- `cli/src/state/runtimeStore.test.ts`

Current direction:

- Frontend should consume unified event envelopes.
- Assistant final answer should render once.
- Internal context tags such as `<session_snapshot>` must stay internal and not display to users.
- Large tool outputs should render as summary/ref rather than raw content.

Checks previously run:

```bash
pnpm --dir cli typecheck
pnpm --dir cli test -- runtimeStore.test.ts
```

Still needs real validation:

- Run CLI with child agent and create-agent.
- Confirm no duplicate AssistantAnswer.
- Confirm internal session snapshot does not leak.
- Confirm large schema/tool output does not flood normal transcript.

## Known Recently Discussed Next Feature: File Reference Mechanism

The user raised a new issue:

> If the user provides a file path outside the workspace, what happens?

Current behavior:

- Built-in filesystem tools reject paths outside configured root.
- In create-agent, root is the create-agent workspace.
- In published-agent Docker runtime, builtin filesystem root is usually `/workdir`.
- Host paths like `/Users/admin/.../paper.pdf` are not automatically visible inside Docker.
- Tool approval does not bypass filesystem root boundaries.

Desired next design:

Introduce a controlled file reference mechanism instead of allowing arbitrary external paths.

Suggested design direction:

1. Frontend/runtime accepts user-provided file references as structured attachments/resources.
2. External files are copied or mounted into a controlled workspace area, probably `/workdir/input_files/...` or runtime artifact/resource space.
3. The LLM receives stable package/runtime-relative references, not raw host paths.
4. File references should carry metadata:
   - original display name
   - stable runtime path
   - MIME/type if available
   - size/hash if available
   - permission/source evidence
5. The LLM should use the safe runtime path.
6. If the path is not imported, tools should fail with a user-facing request to import/attach the file, not repeatedly try raw host paths.

This should be designed as infrastructure, not business-specific logic.

## Current Safety Boundary For Files

Main file:

- `agent_factory/tooling/builtins/filesystem/common.py`

Important behavior:

- `resolve_path(..., allow_external=False)` rejects path escapes.
- `builtin_allow_external_paths` defaults to false.
- `trust` / approval does not override this boundary.

Do not solve this by setting `builtin_allow_external_paths=true` globally.

## Docker Notes

Expected image tag:

```bash
docker build -t agentfactory-runtime-python:3.12 -f docker/agent-runtime/Dockerfile .
```

If Docker Hub syntax image fetch fails, the Dockerfile may need a mirrored Python base image:

```bash
docker build -t agentfactory-runtime-python:3.12 \
  --build-arg PYTHON_BASE_IMAGE=<python-3.12-slim-mirror> \
  -f docker/agent-runtime/Dockerfile .
```

Do not assume the image exists on a new machine; check with:

```bash
docker image inspect agentfactory-runtime-python:3.12
```

## Good Test Prompts

ReAct + tools + web:

```text
帮我创建一个个人投资研究助手：每天工作日上午 9 点给我一份中文简报，包含财经新闻、A股和美股市场变化、我关注股票的风险提醒和谨慎建议。支持我增删关注股票，初始关注苹果、英伟达、科大讯飞。可以用开放信息源联网查询。
```

Plan-and-Execute:

```text
我想做一个论文分析助手。用户给本地 PDF 路径或论文链接后，先制定分析计划，然后自动分析研究问题、方法、实验、结论、创新点、局限性和复现风险，最后输出 Markdown 中文报告，并支持后续追问。
```

After publishing the Plan-and-Execute package, test with:

```text
你好
```

Expected behavior:

- It should not invent `/home/ubuntu/paper.pdf`.
- It should not call analysis tools.
- It should ask for the paper path/link or respond conversationally.

## Suggested Immediate Next Steps

1. Commit/pull state on the new machine and inspect `git status`.
2. Build or verify Docker runtime image.
3. Run a simple create-agent manufacture using the Plan-and-Execute prompt above.
4. Verify the intent gate with `你好`.
5. Verify session records in `.agentfactory/agent_runtime/<agent_id>/sessions`.
6. Verify probe success-path freshness before publish.
7. Design and implement the file reference/import mechanism.

## Static Check Commands To Reuse

Core runtime/session:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/fastagentfactory_pycache .venv/bin/python -m py_compile \
  agent_factory/runtime_kernel/session.py \
  agent_factory/package_runtime/session_turns.py \
  agent_factory/trace_system/references.py \
  agent_factory/package_runtime/core.py \
  agent_factory/agent_runtime_bridge/stdio_server.py \
  agent_factory/factory_graph/frontend_bridge/stdio_server.py \
  agent_factory/factory_graph/frontend_bridge/agent_package_runtime.py
```

Probe:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/fastagentfactory_pycache .venv/bin/python -m py_compile \
  agent_factory/create_agent/docker_probe_runner.py \
  agent_factory/create_agent/probe_tool.py \
  agent_factory/factory_graph/frontend_bridge/agent_runtime_launcher.py \
  agent_factory/tooling/compiler.py
```

Frontend:

```bash
pnpm --dir cli typecheck
pnpm --dir cli test -- runtimeStore.test.ts
```

Full syntax sweep if needed:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/fastagentfactory_pycache .venv/bin/python -m compileall -q agent_factory
```

## Handoff Warning

Do not mark future work complete based only on static checks. The remaining uncertainty is mostly real runtime behavior:

- Docker probe execution
- child agent session persistence
- same-session continuation
- event rendering cleanliness
- Plan-and-Execute intent gating under real model behavior

The user will likely run real-chain tests and provide traces. Use those traces as the authority.
