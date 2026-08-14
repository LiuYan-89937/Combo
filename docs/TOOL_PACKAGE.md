# ToolPackage 文件协议

Combo 使用“一目录一个工具”的 `tool_package.v1` 协议。内置工具、用户上传工具和后续在线创建工具共享同一份能力定义、发布、索引和执行网关；来源仅决定信任等级与运行隔离方式。

```text
my-tool/
├── TOOL.yaml
├── main.py
├── requirements.txt
└── resources/
```

- `TOOL.yaml`：模型可见说明、输入/输出 JSON Schema、权限、并发、超时与输出策略。
- `main.py`：必须提供同步函数 `run(arguments, context)`。
- `requirements.txt`：可选；只接受标准 Python requirement，不接受 pip 命令行参数。
- `resources/`：可选；运行时通过 `context["resources_path"]` 获得绝对路径。

## TOOL.yaml

```yaml
schema_version: tool_package.v1
name: my-tool
model_alias: my_tool
display_name: 我的工具
description: 清楚说明适用条件、行为和结果，供模型检索与选择。
keywords: [example]
entrypoint: main:run
input_schema:
  type: object
  additionalProperties: false
  properties:
    value:
      type: string
      description: 要处理的文本
  required: [value]
output_schema:
  type: object
  additionalProperties: false
  properties:
    result:
      type: string
      description: 处理结果
  required: [result]
permissions:
  approval: inherit
  risk_level: low
  effects: [read]
  read_only: true
  sensitive_argument_paths: []
execution:
  allow_parallel_calls: true
  max_parallel_calls: 2
  timeout_seconds: 300
  output_projection: compress
  output_max_model_chars: 50000
  retain_raw_output: true
runtime:
  platforms: [any]
  required_input_modalities: [text]
  output_modalities: [structured]
  platform_resources: []
  system_available: false
```

## main.py

```python
def run(arguments, context):
    value = arguments["value"]
    workspace = context["workspace_path"]
    resources = context["resources_path"]
    return {"result": value, "workspace": workspace, "resources": resources}
```

用户函数返回普通 JSON 对象即可。平台适配器负责封装内部执行信封，用户代码不依赖 Combo 的内部协议。

`platform_resources` 与 `system_available` 是内置 ToolPackage 的受信字段。本地上传工具必须保持空值/`false`，通过 `context` 中的工作区和资源目录工作，不能把 Web 后端对象注入用户进程。

## 发布边界

上传时先完成路径、大小、UTF-8、Manifest、JSON Schema、入口函数与依赖声明校验，再在依赖池中准备不可变环境。通过后才原子发布能力 revision 并重建搜索索引；失败不会覆盖已发布版本。

运行时从内容寻址 Blob 还原不可变目录，在独立子进程中执行。工作目录默认为当前会话工作区，环境变量只继承平台允许列表；暂停、超时会终止工具子进程。
