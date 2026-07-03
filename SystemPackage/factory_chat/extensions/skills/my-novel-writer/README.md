# Novel Writer v3.0

小说创作助手，支持人物设定、世界观管理、大纲控制和 AI 章节生成。

## 环境配置

```bash
# 必填
export NOVEL_API_KEY="your-api-key"
export NOVEL_API_BASE_URL="https://your-api.com/v1"

# 可选
export NOVEL_MODEL="gpt-3.5-turbo"
export NOVEL_TEMPERATURE="0.8"
export NOVEL_MAX_TOKENS=4096
export NOVEL_DEFAULT_STYLE="wuxia"
```

## 安装依赖

```bash
pip install openai pydantic
```

## 快速开始

```bash
# 1. 创建新小说
python core.py --new "我的奇幻世界"

# 2. 设定人物
python core.py --novel-title "我的奇幻世界" --set-character "林风" "主角，25岁，剑客"

# 3. 设定世界观
python core.py --novel-title "我的奇幻世界" --set-world "一个充满魔法的大陆"

# 4. 设定风格
python core.py --novel-title "我的奇幻世界" --set-style "wuxia"

# 5. 添加大纲
python core.py --novel-title "我的奇幻世界" --add-outline 1 "初遇" "林风在森林中救下受伤的少女"

# 6. 生成章节
python core.py --novel-title "我的奇幻世界" --generate 1 2300

# 7. 查看进度
python core.py --novel-title "我的奇幻世界" --status
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `--new TITLE` | 创建新小说项目 |
| `--novel-title TITLE` | 指定小说名称 |
| `--set-character NAME PROFILE` | 设定人物 |
| `--set-world SETTING` | 设定世界观 |
| `--set-style STYLE` | 设定写作风格 (wuxia/xianxia/scifi/mystery) |
| `--add-outline NUM TITLE SUMMARY` | 添加大纲 |
| `--import-outline FILE` | 从 JSON 导入大纲 |
| `--export-outline FILE` | 导出大纲到 JSON |
| `--generate NUM WORDS` | 生成章节 |
| `--generate-batch START END WORDS` | 批量生成章节 |
| `--regenerate NUM` | 重新生成章节 |
| `--status` | 查看创作进度 |
| `--stats` | 查看详细统计 |

## 高级功能

### 批量生成
```bash
python core.py --novel-title "我的小说" --generate-batch 1 10 2300
```

### 导入大纲 (JSON)
```bash
python core.py --novel-title "我的小说" --import-outline outline.json
```

大纲 JSON 格式:
```json
{
  "novel_title": "我的小说",
  "outline": [
    {"chapter": 1, "title": "初遇", "summary": "..."},
    {"chapter": 2, "title": "危机", "summary": "..."}
  ]
}
```

### 重新生成章节
```bash
python core.py --novel-title "我的小说" --regenerate 1
```

### 详细统计
```bash
python core.py --novel-title "我的小说" --stats
```

## 项目结构

```
novel_writer/
├── core.py              # 核心逻辑 + CLI
├── prompts.py           # Prompt 模板（优化生成质量）
├── config_models.py     # 配置验证 (pydantic)
├── text_processor.py    # 中文文本处理
├── config.json          # 配置（使用环境变量）
├── SKILL.md             # 详细文档
└── templates/           # 创作模板
```

## 功能特点

- **环境变量配置** - API 密钥不硬编码，安全可靠
- **Prompt 优化** - 模块化设计，提升生成质量
- **配置验证** - 使用 pydantic 防止配置错误
- **中文处理** - 智能摘要提取、字数统计
- **批量生成** - 连续生成多章
- **大纲导入导出** - JSON 格式管理大纲
- **章节重写** - 不满意可重新生成
- **日志记录** - 完整的操作日志
- **类型注解** - 完整的类型提示

## License

MIT