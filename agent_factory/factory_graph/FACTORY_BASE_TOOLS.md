# Factory Base Tools v0

本文档整理配给 Factory Agent 的基础工具。

这里的工具是给工厂使用的工程工具，不是被生成 Agent 的业务工具。

---

## 工具分层

- Safe probe
  只读、低风险，用于环境嗅探和工程理解。

- Workspace mutation
  修改工作区文件或生成构件，需要可审计。

- Execution / network
  运行命令、访问网络、调用外部服务，需要 sandbox、权限和报告。

---

## 文件与目录

| Tool | 用途 | 风险 |
|---|---|---|
| `file.read` | 读取 Assembly、GraphDSL、wrapper、schema、报告 | 低 |
| `file.write` | 写 Assembly draft、ToolPackage、harness、summary | 中 |
| `file.patch` | 局部修复 Assembly、ToolPackage、Harness | 中 |
| `file.list` | 发现 patterns、wrappers、tools、examples | 低 |
| `file.exists` | 判断路径或资源是否存在 | 低 |
| `file.mkdir` | 创建 package、report、harness 目录 | 中 |

要求：

- mutation 类工具必须记录路径、来源和 diff。
- 不允许覆盖用户文件，除非 repair plan 明确要求。

---

## 搜索与理解

| Tool | 用途 | 风险 |
|---|---|---|
| `search.rg` | 搜索 wrapper id、tool id、schema 字段、已有实现 | 低 |
| `search.files` | 查找 docs、examples、contracts、reports | 低 |
| `search.symbol` | 查 Python 类、函数、`@wrap_node` 注册点 | 低 |

要求：

- 搜索结果必须能回溯到文件路径。
- Factory 阶段不能靠自然语言猜测已有能力，必须先搜索。

---

## Shell 与命令

| Tool | 用途 | 风险 |
|---|---|---|
| `shell.which` | 检查本地命令是否存在 | 低 |
| `shell.env` | 查看允许范围内的环境变量状态 | 中 |
| `shell.run` | 运行测试、编译、沙箱命令 | 高 |

要求：

- `shell.env` 默认只返回是否存在，不返回 secret 明文。
- `shell.run` 必须走 sandbox / approval / allowlist。
- 命令输出需要进入报告，供 repair 使用。

---

## Python 工具

| Tool | 用途 | 风险 |
|---|---|---|
| `python.import_check` | 判断工具依赖 package 是否可用 | 低 |
| `python.compile_check` | 检查生成代码语法 | 中 |
| `python.run` | 执行工具单测、schema 校验、小型探针 | 高 |

要求：

- `python.run` 只运行受控脚本。
- 生成工具必须至少经过 compile check。

---

## 网络与 HTTP

| Tool | 用途 | 风险 |
|---|---|---|
| `http.head` | 探测 URL/API 是否可达 | 中 |
| `http.get` | 拉公开文档、OpenAPI schema、测试 fixture | 中到高 |
| `http.post` | 调测试 API 或服务 profile | 高 |
| `http.healthcheck` | 检查服务 endpoint 健康状态 | 中 |

要求：

- 网络访问必须记录来源 URL。
- `http.post` 默认不开放，必须由 ResourceContract 声明。

---

## 环境与资源嗅探

| Tool | 用途 | 风险 |
|---|---|---|
| `env.has` | 判断 API key、DB URL、OAuth profile 是否存在 | 低 |
| `env.get` | 读取允许范围内的非 secret 配置 | 高 |
| `resource.probe` | 统一资源探针 | 中 |

`resource.probe` 建议支持：

- command exists
- env exists
- python package exists
- file permission
- directory permission
- network reachable
- service profile exists

输出结构：

```yaml
resource_id: string
status: available | missing | blocked | unknown
reason: string
evidence: {}
```

对应阶段：

- `identify_conditions`
- `plan_resource_needs`
- `build_resource_contracts`
- `decide_readiness`

---

## Schema 与契约校验

| Tool | 用途 | 风险 |
|---|---|---|
| `schema.validate_json` | 校验 JSON 报告和 metadata | 低 |
| `schema.validate_yaml` | 校验 Assembly、GraphDSL、harness YAML | 低 |
| `schema.validate_pydantic` | 调 Pydantic schema 校验对象 | 低 |

要求：

- 校验失败必须返回 `message / location / reason`。
- 校验报告要能进入 repair 阶段。

---

## Assembly 专用工具

| Tool | 用途 | 对应阶段 |
|---|---|---|
| `assembly.load` | 读取 AgentAssemblySpec | `generate_package_specs` |
| `assembly.validate` | 调 AgentAssemblyValidator | `decide_readiness`, `sandbox_test_and_repair` |
| `assembly.compile` | 调 AgentAssemblyCompiler | `generate_package_specs`, `sandbox_test_and_repair` |
| `assembly.run_harness` | 调 AgentAssemblyRunner.run_spec/run_path | `sandbox_test_and_repair` |
| `assembly.run_invocation` | 回放真实运行故障 | `sandbox_test_and_repair` |
| `assembly.patch` | 受控修改 AssemblySpec | `generate_package_specs`, `sandbox_test_and_repair` |

要求：

- Assembly 工具产出的失败报告必须保留 `final_state_snapshot` 和 `event_log`。
- 返厂 repair 优先消费 Assembly/Harness/Invocation report。

---

## ToolPackage 专用工具

| Tool | 用途 | 对应阶段 |
|---|---|---|
| `tool_contract.create` | 从资源需求生成工具契约草案 | `build_resource_contracts` |
| `tool_contract.validate` | 校验 id、输入、输出、风险、依赖资源 | `build_resource_contracts`, `decide_readiness` |
| `tool_package.generate` | 根据 ToolContract 生成实现或 adapter | `generate_tools` |
| `tool_package.test` | 运行工具沙箱测试 | `sandbox_test_and_repair` |
| `tool_package.register` | 注册通过测试的工具 id | `generate_tools`, `sandbox_test_and_repair` |

工具沙箱测试至少覆盖：

- schema input/output
- fake input
- error case
- timeout
- missing resource

---

## 报告与维修

| Tool | 用途 | 对应阶段 |
|---|---|---|
| `report.write` | 写 HarnessReport、InvocationReport、ToolTestReport | `sandbox_test_and_repair`, `complete_summary` |
| `report.read` | 读取已有报告 | `sandbox_test_and_repair`, `complete_summary` |
| `report.extract_repair_signals` | 提取返厂维修线索 | `sandbox_test_and_repair` |

`report.extract_repair_signals` 输出：

```yaml
repair_target: assembly | tool_package | resource_contract | harness | requirement
location: string
reason: string
suggested_stage: string
```

---

## v0 最小工具集合

第一批建议先实现：

```text
file.read
file.write
file.patch
file.list
file.exists
search.rg
search.files
shell.which
shell.run
env.has
python.import_check
python.compile_check
http.head
resource.probe
schema.validate_yaml
assembly.load
assembly.validate
assembly.compile
assembly.run_harness
assembly.run_invocation
assembly.patch
tool_contract.validate
tool_package.generate
tool_package.test
report.write
report.extract_repair_signals
```
