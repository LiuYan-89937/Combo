<template>
  <main class="library-page">
    <header class="library-header">
      <div class="title-block">
        <span class="eyebrow">CAPABILITY LIBRARY</span>
        <h1>{{ activeHeading.title }}</h1>
        <p>{{ activeHeading.description }}</p>
      </div>
      <div class="header-tools">
        <n-input v-model:value="query" clearable placeholder="搜索名称、说明或关键词" class="search-input">
          <template #prefix><n-icon><SearchOutline /></n-icon></template>
        </n-input>
        <n-button quaternary circle :loading="loading" aria-label="刷新扩展列表" @click="loadAll">
          <template #icon><n-icon><Refresh /></n-icon></template>
        </n-button>
      </div>
    </header>

    <n-alert v-if="loadError" type="error" closable class="page-alert" @close="loadError = ''">{{ loadError }}</n-alert>
    <div v-if="activePool === 'mcp' && probeResult" class="mcp-probe-notice">
      <span>✓</span>
      <strong>{{ probeSummary }}</strong>
      <button type="button" aria-label="关闭" @click="clearProbeNotice">×</button>
    </div>

    <section class="pool-surface">
      <div class="pool-heading">
        <div>
          <span class="pool-kicker">{{ activeHeading.kicker }}</span>
          <h2>{{ activeHeading.listTitle }}</h2>
          <p>{{ visibleItems.length }} 项已载入，可搜索并打开编辑。</p>
        </div>
        <n-button v-if="activePool === 'mcp'" type="primary" round @click="openAddMcp">
          <template #icon><n-icon><Add /></n-icon></template>
          {{ t('extensions.addServer') }}
        </n-button>
        <template v-else-if="activePool === 'tools'">
          <n-space>
            <input ref="toolFolderInput" class="hidden-folder-input" type="file" webkitdirectory directory multiple @change="importToolFolder" />
            <n-button round :loading="importingTool" @click="toolFolderInput?.click()">
              {{ t('toolPreparation.importFolder') }}
            </n-button>
            <n-button type="primary" round @click="openToolCreator">
              <template #icon><n-icon><Add /></n-icon></template>
              新建工具
            </n-button>
          </n-space>
        </template>
        <n-space v-else-if="activePool === 'skills'">
          <input ref="skillFolderInput" class="hidden-folder-input" type="file" webkitdirectory directory multiple @change="importSkillFolder" />
          <n-button round :loading="importingSkill" @click="skillFolderInput?.click()">上传文件夹</n-button>
          <n-button type="primary" round @click="openSkillHub">
            <template #icon><n-icon><Add /></n-icon></template>
            从 SkillHub 添加
          </n-button>
        </n-space>
      </div>

      <div v-if="visibleItems.length" class="card-grid">
        <article
          v-for="item in visibleItems"
          :key="itemKey(item)"
          class="pool-card"
          tabindex="0"
          @click="openItem(item)"
          @keydown.enter="openItem(item)"
        >
          <div class="card-header">
            <span class="type-pill">{{ itemType(item) }}</span>
            <div class="card-statuses">
              <span v-if="item.indexing.vector" class="status indexed"><i />{{ t('capabilityPools.indexed') }}</span>
              <span class="status" :class="{ muted: !itemEnabled(item) }">
                <i />{{ itemEnabled(item) ? t('capabilityPools.available') : t('capabilityPools.disabled') }}
              </span>
            </div>
          </div>
          <div class="card-body">
            <div class="card-title-line">
              <span v-if="item.kind === 'tool'" class="card-tool-icon">
                <ToolIcon :name="toolPresentation(itemModelAlias(item), {}).icon" :size="19" />
              </span>
              <h3>{{ itemName(item) }}</h3>
            </div>
            <p>{{ itemDescription(item) }}</p>
          </div>
          <div class="card-facts">
            <span v-for="fact in itemFacts(item)" :key="fact">{{ fact }}</span>
          </div>
          <footer class="card-footer">
            <span>{{ itemSource(item) }}</span>
            <div class="card-buttons">
              <n-button
                v-if="isMcpServer(item)"
                size="small"
                quaternary
                :loading="probingId === item.capability_id"
                @click.stop="probeMcp(item)"
              >测试</n-button>
              <n-button size="small" quaternary @click.stop="editItem(item)">
                编辑
              </n-button>
              <n-popconfirm
                v-if="canDeleteItem(item)"
                positive-text="删除"
                negative-text="取消"
                @positive-click="deleteItem(item)"
              >
                <template #trigger>
                  <n-button
                    size="small"
                    quaternary
                    :loading="deletingId === item.capability_id"
                    @click.stop
                  >删除</n-button>
                </template>
                {{ deleteConfirmation(item) }}
              </n-popconfirm>
            </div>
          </footer>
        </article>
      </div>
      <n-empty v-else class="empty-state" :description="query.trim() ? '没有匹配的结果' : activeHeading.empty" />
    </section>

    <n-drawer v-model:show="showToolEditor" :width="600" placement="right">
      <n-drawer-content title="工具配置" closable>
        <template v-if="editingTool">
          <div class="editor-intro">
            <span class="type-pill">{{ editingTool.kind === 'mcp_tool' ? 'MCP TOOL' : 'TOOL' }}</span>
            <p>这里的设置会进入下一次能力快照，并直接约束运行时执行。</p>
            <n-button v-if="editingTool.trust_level === 'local_user' && editingTool.details.implementation_kind === 'python_package'" size="small" secondary @click="openToolPackageEditor(editingTool)">编辑源码、依赖与资源</n-button>
          </div>
          <n-form label-placement="top" class="editor-form">
            <section class="form-section">
              <div class="section-title"><strong>呈现给模型的信息</strong><span>名称用于识别，说明会进入模型上下文。</span></div>
              <n-form-item label="显示名称"><n-input v-model:value="toolForm.display_name" /></n-form-item>
              <n-form-item label="工具说明">
                <n-input v-model:value="toolForm.description" type="textarea" :autosize="{ minRows: 4, maxRows: 9 }" />
              </n-form-item>
            </section>
            <section class="form-section two-column">
              <div class="section-title full"><strong>权限与风险</strong><span>对话的三档权限仍是上层规则，这里定义单个工具的边界。</span></div>
              <n-form-item label="审批策略">
                <n-select v-model:value="toolForm.approval" :options="approvalOptions" />
              </n-form-item>
              <n-form-item label="风险级别">
                <n-select v-model:value="toolForm.risk_level" :options="riskOptions" />
              </n-form-item>
            </section>
            <section class="form-section">
              <div class="section-row">
                <div class="section-title"><strong>并发调用</strong><span>允许同一工具同时处理多个请求。</span></div>
                <n-switch v-model:value="toolForm.allow_parallel_calls" @update:value="normalizeParallel" />
              </div>
              <n-form-item v-if="toolForm.allow_parallel_calls" label="最大并发请求数">
                <n-input-number v-model:value="toolForm.max_parallel_calls" :min="1" :max="128" />
              </n-form-item>
              <n-form-item label="单次调用超时（秒）">
                <n-input-number v-model:value="toolForm.timeout_seconds" :min="1" :max="3600" />
              </n-form-item>
            </section>
            <section class="form-section">
              <div class="section-title"><strong>输出控制</strong><span>限制进入模型上下文的工具结果，原始结果可独立保留。</span></div>
              <n-form-item label="输出处理">
                <n-radio-group v-model:value="toolForm.output_projection">
                  <n-space><n-radio value="compress">超限压缩</n-radio><n-radio value="passthrough">原样传递</n-radio></n-space>
                </n-radio-group>
              </n-form-item>
              <n-form-item v-if="toolForm.output_projection === 'compress'" label="模型可见字符上限">
                <n-input-number v-model:value="toolForm.output_max_model_chars" :min="1000" :max="1000000" :step="1000" />
              </n-form-item>
              <div class="switch-line"><span><strong>保留原始输出</strong><small>压缩前的完整结果仍可通过输出工具读取。</small></span><n-switch v-model:value="toolForm.retain_raw_output" /></div>
            </section>
          </n-form>
        </template>
        <template #footer>
          <n-space justify="end"><n-button @click="showToolEditor = false">取消</n-button><n-button type="primary" :loading="savingTool" @click="saveTool">保存并发布</n-button></n-space>
        </template>
      </n-drawer-content>
    </n-drawer>

    <n-drawer v-model:show="showMcpDetails" :width="620" placement="right">
      <n-drawer-content title="MCP 服务" closable>
        <template v-if="selectedMcpDetails">
          <div class="mcp-detail-hero">
            <div><span class="type-pill">MCP</span><h2>{{ itemName(selectedMcpDetails) }}</h2></div>
            <span class="status" :class="{ muted: selectedMcpDetails.details.connection_status !== 'connected' }"><i />{{ selectedMcpDetails.details.connection_status === 'connected' ? '已连接' : '未连接' }}</span>
            <p>{{ itemDescription(selectedMcpDetails) }}</p>
          </div>
          <section class="mcp-connection-facts">
            <div><small>协议</small><strong>{{ selectedMcpDetails.details.protocol_version || '—' }}</strong></div>
            <div><small>传输</small><strong>{{ transportLabel(selectedMcpDetails) }}</strong></div>
            <div><small>服务端</small><strong>{{ selectedMcpDetails.details.server_name || '—' }}</strong></div>
            <div><small>版本</small><strong>{{ selectedMcpDetails.details.server_version || '—' }}</strong></div>
          </section>
          <n-tabs type="line" animated class="mcp-detail-tabs">
            <n-tab-pane v-if="selectedMcpToolCount > 0" name="tools" :tab="`工具 ${selectedMcpToolCount}`">
              <div class="mcp-catalog-list">
                <article v-for="tool in mcpToolsFor(selectedMcpDetails.capability_id)" :key="tool.capability_id"><strong>{{ capabilityName(tool) }}</strong><p>{{ itemDescription(tool) }}</p></article>
                <n-empty v-if="!mcpToolsFor(selectedMcpDetails.capability_id).length" description="该服务没有暴露工具" />
              </div>
            </n-tab-pane>
            <n-tab-pane v-if="selectedMcpResourceCount > 0" name="resources" :tab="`资源 ${selectedMcpResourceCount}`">
              <div class="mcp-catalog-list">
                <article v-for="resource in selectedMcpResources" :key="String(resource.uri)" class="mcp-resource-row"><strong>{{ resource.name || resource.uri }}</strong><p>{{ resource.description || resource.uri }}</p><code>{{ resource.uri }}</code><n-button size="tiny" secondary :loading="readingMcpResourceUri === String(resource.uri)" @click="readMcpResource(resource)">预览</n-button></article>
                <article v-for="resource in selectedMcpResourceTemplates" :key="String(resource.uri_template)" class="mcp-catalog-configurable">
                  <strong>{{ resource.name || resource.uri_template }}</strong><p>{{ resource.description || '参数化资源模板' }}</p><code>{{ resource.uri_template }}</code>
                  <div v-if="resourceTemplateVariables(resource).length" class="mcp-argument-grid">
                    <n-input v-for="name in resourceTemplateVariables(resource)" :key="name" v-model:value="mcpResourceTemplateArguments[resourceArgumentKey(resource, name)]" size="small" :placeholder="name" />
                  </div>
                  <n-button size="tiny" secondary :loading="readingMcpResourceUri === String(resource.uri_template)" :disabled="!resourceTemplateReady(resource)" @click="readMcpResourceTemplate(resource)">预览</n-button>
                </article>
                <n-empty v-if="!selectedMcpResources.length && !selectedMcpResourceTemplates.length" description="该服务没有暴露资源" />
              </div>
              <section v-if="mcpResourcePreview" class="mcp-resource-preview">
                <img v-if="mcpResourcePreview.kind === 'image'" :src="mcpResourcePreview.content" :alt="mcpResourcePreview.name" />
                <pre v-else-if="mcpResourcePreview.kind === 'text'">{{ mcpResourcePreview.content }}</pre>
                <div v-else><strong>{{ mcpResourcePreview.name }}</strong><p>该资源是二进制内容，当前类型不支持内嵌预览。</p></div>
              </section>
            </n-tab-pane>
            <n-tab-pane v-if="selectedMcpPromptCount > 0" name="prompts" :tab="`Prompts ${selectedMcpPromptCount}`">
              <div class="mcp-catalog-list">
                <article v-for="prompt in selectedMcpPrompts" :key="String(prompt.name)" class="mcp-catalog-configurable">
                  <strong>{{ prompt.name }}</strong><p>{{ prompt.description || '模型可按需加载这个 Prompt' }}</p>
                  <div v-if="promptArguments(prompt).length" class="mcp-argument-grid">
                    <n-input v-for="argument in promptArguments(prompt)" :key="String(argument.name)" v-model:value="mcpPromptArguments[promptArgumentKey(prompt, argument)]" size="small" :placeholder="`${argument.name}${argument.required ? ' *' : ''}`" />
                  </div>
                  <n-button size="tiny" secondary :loading="readingMcpPromptName === String(prompt.name)" :disabled="!promptReady(prompt)" @click="readMcpPrompt(prompt)">预览</n-button>
                </article>
                <n-empty v-if="!selectedMcpPrompts.length" description="该服务没有暴露 Prompt" />
              </div>
              <section v-if="mcpPromptPreview" class="mcp-resource-preview mcp-prompt-preview">
                <strong>{{ mcpPromptPreview.name }}</strong>
                <article v-for="(part, index) in mcpPromptPreview.parts" :key="index">
                  <small>{{ part.role }}</small>
                  <img v-if="part.kind === 'image'" :src="part.content" :alt="mcpPromptPreview.name" />
                  <pre v-else>{{ part.content }}</pre>
                </article>
              </section>
            </n-tab-pane>
            <n-tab-pane name="logs" tab="日志">
              <div class="mcp-log-list"><p v-for="(entry, index) in selectedMcpLogs" :key="index"><span>{{ entry.level }}</span><code>{{ formatMcpLog(entry) }}</code></p><n-empty v-if="!selectedMcpLogs.length" description="服务暂未发送协议日志" /></div>
            </n-tab-pane>
          </n-tabs>
        </template>
        <template #footer><n-space justify="end"><n-button v-if="selectedMcpDetails" @click="editItem(selectedMcpDetails)">编辑连接</n-button><n-button type="primary" :loading="probingId === selectedMcpDetails?.capability_id" @click="selectedMcpDetails && probeMcp(selectedMcpDetails)">重新发现</n-button></n-space></template>
      </n-drawer-content>
    </n-drawer>

    <n-modal v-model:show="showToolCreator" preset="card" class="tool-creator" :style="{ width: 'min(1120px, calc(100vw - 48px))' }" title="新建工具" :bordered="false">
      <div class="creator-layout">
        <n-form label-placement="top" class="creator-form">
          <section class="form-section two-column">
            <div class="section-title full"><strong>基本信息</strong><span>系统会据此生成并校验 TOOL.yaml。</span></div>
            <n-form-item label="工具标识 *"><n-input v-model:value="toolCreateForm.name" placeholder="lowercase-kebab-case" /></n-form-item>
            <n-form-item label="模型调用名称 *"><n-input v-model:value="toolCreateForm.model_alias" placeholder="lowercase_snake_case" /></n-form-item>
            <n-form-item label="显示名称 *"><n-input v-model:value="toolCreateForm.display_name" /></n-form-item>
            <n-form-item label="关键词"><n-dynamic-tags v-model:value="toolCreateForm.keywords" /></n-form-item>
            <n-form-item class="full" label="工具说明 *"><n-input v-model:value="toolCreateForm.description" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" /></n-form-item>
          </section>
          <section class="form-section">
            <div class="section-row"><div class="section-title"><strong>输入参数</strong><span>参数会生成 JSON Schema，并进入能力检索索引。</span></div><n-button size="small" @click="addToolParameter">添加参数</n-button></div>
            <div v-for="(parameter, index) in toolCreateForm.parameters" :key="index" class="parameter-card">
              <div class="parameter-head">
                <span>参数 {{ index + 1 }}</span>
                <n-button size="tiny" quaternary @click="toolCreateForm.parameters.splice(index, 1)">移除</n-button>
              </div>
              <div class="parameter-fields">
                <n-form-item label="参数名"><n-input v-model:value="parameter.name" placeholder="例如 query" /></n-form-item>
                <n-form-item label="数据类型"><n-select v-model:value="parameter.type" :options="parameterTypeOptions" /></n-form-item>
                <n-form-item label="是否必填" class="required-field">
                  <n-switch v-model:value="parameter.required"><template #checked>必填</template><template #unchecked>可选</template></n-switch>
                </n-form-item>
                <n-form-item label="参数说明" class="parameter-description">
                  <n-input v-model:value="parameter.description" placeholder="说明参数的含义、格式与使用约束，帮助模型正确填写" />
                </n-form-item>
              </div>
            </div>
            <n-empty v-if="!toolCreateForm.parameters.length" description="该工具没有输入参数" />
          </section>
          <section class="form-section">
            <div class="section-title"><strong>Python 依赖</strong><span>每项使用标准 requirement 格式，例如 requests&gt;=2.32。</span></div>
            <n-dynamic-tags v-model:value="toolCreateForm.dependencies" />
          </section>
        </n-form>
        <section class="source-pane">
          <div class="section-row"><div class="pane-note"><strong>main.py *</strong><span>必须定义同步函数 run(arguments, context)，并返回 JSON 对象。</span></div><label class="file-button">上传 main.py<input type="file" accept=".py,text/x-python" @change="loadToolMainFile" /></label></div>
          <CodeEditor v-model="toolCreateForm.main_source" language="python" :min-height="600" />
        </section>
      </div>
      <ToolDependencyProgress
        v-if="toolPreparationOwner === 'create'"
        class="creator-progress"
        :status="toolPreparation.status"
        :stage="toolPreparation.stage"
        :logs="toolPreparation.logs"
        :requirements="toolPreparation.requirements"
        :error="toolPreparation.error"
      />
      <template #footer>
        <n-space justify="end">
          <n-button :disabled="creatingTool" @click="showToolCreator = false">取消</n-button>
          <n-button
            v-if="toolPreparationOwner === 'create' && toolPreparation.status === 'succeeded'"
            type="primary"
            @click="showToolCreator = false"
          >{{ t('toolPreparation.close') }}</n-button>
          <n-button v-else type="primary" :loading="creatingTool" @click="createToolPackage">
            {{ toolPreparationOwner === 'create' && toolPreparation.status === 'failed' ? t('toolPreparation.retry') : '校验并发布' }}
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal
      v-model:show="showToolImportProgress"
      preset="card"
      :mask-closable="!importingTool"
      :close-on-esc="!importingTool"
      :closable="!importingTool"
      :style="{ width: 'min(620px, calc(100vw - 32px))' }"
      :title="t('toolPreparation.importFolder')"
    >
      <ToolDependencyProgress
        :status="toolPreparation.status"
        :stage="toolPreparation.stage"
        :logs="toolPreparation.logs"
        :requirements="toolPreparation.requirements"
        :error="toolPreparation.error"
      />
      <template #footer>
        <n-space justify="end">
          <n-button :disabled="importingTool" @click="showToolImportProgress = false">
            {{ t('toolPreparation.close') }}
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showToolPackageEditor" preset="card" class="skill-editor" :style="{ width: 'min(1120px, calc(100vw - 48px))' }" title="ToolPackage 编辑器" :bordered="false">
      <n-spin :show="loadingToolPackage">
        <template v-if="toolPackageDocument">
          <div class="skill-editor-header">
            <div><span class="type-pill">TOOL PACKAGE</span><strong>{{ toolPackageDocument.entrypoint }}</strong></div>
            <span>{{ toolPackageDocument.source_path }}</span>
          </div>
          <div class="package-summary">
            <span>{{ toolPackageDocument.files.length }} 个文件</span>
            <span>{{ toolPackageDocument.python_requirements.length }} 项 Python 依赖</span>
            <span>保存时重新校验、构建依赖并原子发布</span>
          </div>
          <div class="resource-editor">
            <aside>
              <button v-for="file in toolPackageDocument.files" :key="file.path" type="button" :class="{ active: selectedToolFilePath === file.path }" @click="selectedToolFilePath = file.path">
                <span>{{ file.path }}</span><small>{{ formatBytes(file.size_bytes) }}{{ file.editable ? '' : ' · 只读' }}</small>
              </button>
            </aside>
            <section v-if="selectedToolFile" class="resource-content">
              <div class="pane-note"><strong>{{ selectedToolFile.path }}</strong><span>{{ selectedToolFile.editable ? 'UTF-8 文本；修改不会影响当前 revision，保存后才发布新 revision' : '二进制文件不能在线编辑' }}</span></div>
              <n-input v-if="selectedToolFile.editable" v-model:value="toolPackageFiles[selectedToolFile.path]" type="textarea" class="code-editor" :autosize="{ minRows: 22, maxRows: 36 }" />
              <n-empty v-else description="该文件只能通过重新上传 ToolPackage 更新" />
            </section>
          </div>
        </template>
      </n-spin>
      <template #footer><n-space justify="end"><n-button @click="showToolPackageEditor = false">取消</n-button><n-button type="primary" :loading="savingToolPackage" :disabled="!toolPackageDocument" @click="saveToolPackageContent">校验并发布</n-button></n-space></template>
    </n-modal>

    <n-modal v-model:show="showSkillEditor" preset="card" class="skill-editor" :style="{ width: 'min(1040px, calc(100vw - 48px))' }" title="Skill 编辑器" :bordered="false">
      <n-spin :show="loadingSkill">
        <template v-if="skillDocument">
          <div class="skill-editor-header">
            <div><span class="type-pill">SKILL</span><strong>{{ String(skillForm.metadata.display_name || skillForm.metadata.name || '') }}</strong></div>
            <span>{{ skillDocument.source_path }}</span>
          </div>
          <n-tabs v-model:value="skillTab" type="line" animated>
            <n-tab-pane name="metadata" tab="基本信息">
              <div class="skill-pane narrow-pane">
                <n-form label-placement="top">
                  <n-form-item label="标识"><n-input :value="String(skillForm.metadata.name || '')" disabled /></n-form-item>
                  <n-form-item label="显示名称"><n-input v-model:value="skillDisplayName" placeholder="可选；留空时使用标识" /></n-form-item>
                  <n-form-item label="能力说明"><n-input v-model:value="skillDescription" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" /></n-form-item>
                  <n-form-item label="关键词"><n-dynamic-tags v-model:value="skillKeywords" /></n-form-item>
                </n-form>
              </div>
            </n-tab-pane>
            <n-tab-pane name="instructions" tab="指令正文">
              <div class="skill-pane instruction-pane">
                <div class="pane-note"><strong>SKILL.md</strong><span>使用 Markdown 编写完整执行约束、流程和交付标准。</span></div>
                <n-input v-model:value="skillForm.instructions" type="textarea" class="code-editor" :autosize="{ minRows: 22, maxRows: 34 }" />
              </div>
            </n-tab-pane>
            <n-tab-pane name="resources" :tab="`资源文件 · ${skillDocument.resources.length}`">
              <div class="resource-editor">
                <aside>
                  <button
                    v-for="resource in skillDocument.resources"
                    :key="resource.path"
                    type="button"
                    :class="{ active: selectedResourcePath === resource.path }"
                    @click="selectedResourcePath = resource.path"
                  >
                    <span>{{ resource.path }}</span><small>{{ formatBytes(resource.size_bytes) }}{{ resource.editable ? '' : ' · 只读' }}</small>
                  </button>
                </aside>
                <section v-if="selectedResource" class="resource-content">
                  <div class="pane-note"><strong>{{ selectedResource.path }}</strong><span>{{ selectedResource.editable ? '文本资源，可直接编辑' : '二进制资源，仅展示文件信息' }}</span></div>
                  <n-input v-if="selectedResource.editable" v-model:value="skillResources[selectedResource.path]" type="textarea" class="code-editor" :autosize="{ minRows: 20, maxRows: 32 }" />
                  <n-empty v-else description="该资源不是 UTF-8 文本，不能在此编辑" />
                </section>
                <n-empty v-else class="resource-empty" description="选择一个资源文件" />
              </div>
            </n-tab-pane>
          </n-tabs>
        </template>
      </n-spin>
      <template #footer><n-space justify="end"><n-button @click="showSkillEditor = false">取消</n-button><n-button type="primary" :loading="savingSkill" :disabled="!skillDocument" @click="saveSkillContent">保存并发布</n-button></n-space></template>
    </n-modal>

    <n-modal v-model:show="showSkillHub" preset="card" class="skillhub-modal" :style="{ width: 'min(820px, calc(100vw - 32px))' }" :bordered="false">
      <div class="skillhub-panel">
        <header class="skillhub-header">
          <div>
            <span class="pool-kicker">SKILL DISCOVERY</span>
            <h2>从 SkillHub 添加</h2>
            <p>搜索社区 Skill，安装后会进入当前能力池。</p>
          </div>
          <span class="skillhub-connection" :class="{ ready: skillHubResult?.cli_available }">
            <i />{{ skillHubResult?.cli_available ? '已连接' : '不可用' }}
          </span>
        </header>
        <div class="skillhub-search" :class="{ disabled: !skillHubResult?.cli_available }">
          <n-icon :size="20"><SearchOutline /></n-icon>
          <input
            v-model="skillHubQuery"
            :disabled="!skillHubResult?.cli_available"
            type="search"
            autocomplete="off"
            placeholder="搜索能力，例如 ppt design"
            aria-label="搜索 SkillHub"
            @keyup.enter="searchSkillHub"
          />
          <button
            type="button"
            :disabled="!skillHubQuery.trim() || !skillHubResult?.cli_available || searchingSkillHub"
            @click="searchSkillHub"
          >
            {{ searchingSkillHub ? '搜索中' : '搜索' }}
          </button>
        </div>
        <p v-if="!skillHubResult?.cli_available" class="skillhub-unavailable">
          {{ skillHubResult?.cli_version || skillHubResult?.message || '正在检查本机 SkillHub CLI' }}
        </p>
        <div v-if="skillHubResult?.items?.length" class="skillhub-results">
          <div class="skillhub-results-head">
            <strong>搜索结果</strong>
            <span>{{ skillHubResult.items.length }} 项</span>
          </div>
          <article
            v-for="item in skillHubResult.items"
            :key="item.install_name"
            tabindex="0"
            role="button"
            :aria-label="`预览 ${item.name}`"
            @click="previewSkillHub(item)"
            @keydown.enter="previewSkillHub(item)"
          >
            <div class="skillhub-result-mark">{{ item.name.slice(0, 1).toUpperCase() }}</div>
            <div class="skillhub-result-copy">
              <div>
                <strong>{{ item.name }}</strong>
                <small>{{ skillHubSourceLabel(item.source) }}<template v-if="item.version"> · {{ item.version }}</template></small>
              </div>
              <p>{{ item.summary || '暂无说明' }}</p>
              <code>{{ item.install_name }}</code>
            </div>
            <div class="skillhub-result-actions">
              <n-button text @click.stop="previewSkillHub(item)">预览</n-button>
              <n-button round type="primary" :loading="installingSkill === item.install_name" :disabled="Boolean(installingSkill)" @click.stop="installSkillHub(item.install_name)">安装</n-button>
            </div>
          </article>
        </div>
        <div v-else-if="skillHubResult?.action === 'search'" class="skillhub-empty">
          <strong>没有找到匹配的 Skill</strong>
          <span>换一个更短、更明确的能力关键词试试。</span>
        </div>
        <div v-else-if="skillHubResult?.cli_available" class="skillhub-empty initial">
          <strong>查找可以直接加入能力池的 Skill</strong>
          <span>使用一到三个关键词描述需要的能力。</span>
        </div>
      </div>
    </n-modal>

    <n-modal
      v-model:show="showSkillHubPreview"
      preset="card"
      class="skillhub-preview-modal"
      :style="{ width: 'min(620px, calc(100vw - 32px))' }"
      :bordered="false"
    >
      <div v-if="selectedSkillHubItem" class="skillhub-preview">
        <header>
          <div class="skillhub-preview-mark">{{ selectedSkillHubItem.name.slice(0, 1).toUpperCase() }}</div>
          <div>
            <span>{{ skillHubSourceLabel(selectedSkillHubItem.source) }}</span>
            <h2>{{ selectedSkillHubItem.name }}</h2>
          </div>
        </header>
        <p class="skillhub-preview-summary">{{ selectedSkillHubItem.summary || '该 Skill 暂未提供说明。' }}</p>
        <dl>
          <div><dt>安装标识</dt><dd><code>{{ selectedSkillHubItem.install_name }}</code></dd></div>
          <div><dt>版本</dt><dd>{{ selectedSkillHubItem.version || '由 SkillHub 提供最新版本' }}</dd></div>
          <div><dt>来源</dt><dd>{{ skillHubSourceLabel(selectedSkillHubItem.source) }}</dd></div>
        </dl>
        <footer>
          <span>安装后会直接进入 Skill 池，可继续查看并编辑完整指令与资源。</span>
          <n-button
            round
            type="primary"
            :loading="installingSkill === selectedSkillHubItem.install_name"
            :disabled="Boolean(installingSkill)"
            @click="installSkillHub(selectedSkillHubItem.install_name)"
          >安装 Skill</n-button>
        </footer>
      </div>
    </n-modal>

    <McpConfigModal
      v-model:show="showMcpModal"
      :item="editingMcpItem"
      :edit-config="editingMcpConfig"
      :busy="savingMcp"
      :stopping="stoppingMcp"
      :install-result="mcpInstallSession"
      @submit="saveMcpServers"
      @cancel-install="cancelMcpInstall"
    />
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  NAlert, NButton, NDrawer, NDrawerContent, NDynamicTags, NEmpty, NForm, NFormItem, NIcon,
  NInput, NInputNumber, NModal, NRadio, NRadioGroup, NSelect, NSpace, NSpin, NSwitch,
  NTabPane, NTabs, NPopconfirm, useMessage,
} from 'naive-ui'
import { Add, Refresh, SearchOutline } from '@/components/icons'
import McpConfigModal from '@/components/extensions/McpConfigModal.vue'
import ToolDependencyProgress from '@/components/extensions/ToolDependencyProgress.vue'
import CodeEditor from '@/components/common/CodeEditor.vue'
import ToolIcon from '@/components/common/ToolIcon.vue'
import {
  capabilityPoolsApi,
  type CapabilityPoolItem,
  type CapabilityPoolSnapshot,
  type McpProbeResult,
  type SkillEditorDocument,
  type SkillEditorResource,
  type SkillHubResult,
  type ToolRuntimePolicyInput,
  type ToolPackageEditorDocument,
  type ToolPackageCreateInput,
} from '@/api/capabilityPools'
import type { McpServerConfig } from '@/api/resourceTypes'
import type { OperationProgress } from '@/api/http'
import type { ExtensionItemView } from '@/types/protocol'
import { useI18n } from '@/composables/useI18n'
import { toolPresentation } from '@/utils/toolPresentation'

type PoolName = 'mcp' | 'tools' | 'skills'
type PoolItem = CapabilityPoolItem
const props = defineProps<{ pool: PoolName }>()
const { t } = useI18n()
const message = useMessage()
const snapshot = ref<CapabilityPoolSnapshot | null>(null)
const loading = ref(false)
const loadError = ref('')
const query = ref('')
const activePool = computed(() => props.pool)
const probingId = ref('')
const probeResult = ref<McpProbeResult | null>(null)
let probeNoticeTimer: ReturnType<typeof setTimeout> | null = null
const deletingId = ref('')
const showMcpModal = ref(false)
const savingMcp = ref(false)
const stoppingMcp = ref(false)
const mcpInstallController = ref<AbortController | null>(null)
const mcpInstallSession = ref<Record<string, unknown> | null>(null)
const editingMcp = ref<CapabilityPoolItem | null>(null)
const showMcpDetails = ref(false)
const selectedMcpDetails = ref<CapabilityPoolItem | null>(null)
const showToolEditor = ref(false)
const savingTool = ref(false)
const editingTool = ref<CapabilityPoolItem | null>(null)
const showSkillEditor = ref(false)
const loadingSkill = ref(false)
const savingSkill = ref(false)
const skillDocument = ref<SkillEditorDocument | null>(null)
const skillTab = ref('metadata')
const selectedResourcePath = ref('')
const skillResources = reactive<Record<string, string>>({})
const showSkillHub = ref(false)
const skillHubQuery = ref('')
const skillHubResult = ref<SkillHubResult | null>(null)
const showSkillHubPreview = ref(false)
const selectedSkillHubItem = ref<SkillHubResult['items'][number] | null>(null)
const searchingSkillHub = ref(false)
const installingSkill = ref('')
const importingSkill = ref(false)
const skillFolderInput = ref<HTMLInputElement | null>(null)
const showToolCreator = ref(false)
const creatingTool = ref(false)
const importingTool = ref(false)
const toolFolderInput = ref<HTMLInputElement | null>(null)
const showToolImportProgress = ref(false)
const toolPreparationOwner = ref<'create' | 'import' | null>(null)
const toolPreparation = reactive<{
  status: 'running' | 'succeeded' | 'failed'
  stage: string
  logs: string[]
  requirements: string[]
  error: string
}>({ status: 'running', stage: 'preparing', logs: [], requirements: [], error: '' })
const showToolPackageEditor = ref(false)
const loadingToolPackage = ref(false)
const savingToolPackage = ref(false)
const toolPackageDocument = ref<ToolPackageEditorDocument | null>(null)
const selectedToolFilePath = ref('')
const toolPackageFiles = reactive<Record<string, string>>({})
const toolCreateForm = reactive<ToolPackageCreateInput & { main_source: string }>({
  name: '', model_alias: '', display_name: '', description: '', keywords: [], parameters: [], dependencies: [],
  main_source: 'def run(arguments, context):\n    return {"result": ""}\n',
  runtime_policy: {
    approval: 'inherit', risk_level: 'low', allow_parallel_calls: true, max_parallel_calls: 1,
    timeout_seconds: 300, output_projection: 'compress', output_max_model_chars: 50000, retain_raw_output: true,
  },
})
const skillForm = reactive<{ metadata: Record<string, unknown>; instructions: string }>({ metadata: {}, instructions: '' })
const toolForm = reactive<ToolRuntimePolicyInput & { display_name: string; description: string }>({
  display_name: '', description: '', approval: 'inherit', risk_level: 'low', allow_parallel_calls: true,
  max_parallel_calls: 1, timeout_seconds: 300, output_projection: 'compress', output_max_model_chars: 50000,
  retain_raw_output: true,
})

const mcpServers = computed(() => capabilitiesOf('mcp_server'))
const tools = computed(() => (snapshot.value?.capabilities || []).filter(item => item.kind === 'tool' || item.kind === 'mcp_tool'))
const skills = computed(() => capabilitiesOf('skill'))
const filteredMcp = computed(() => filterCapabilities(mcpServers.value))
const filteredTools = computed(() => filterCapabilities(tools.value))
const filteredSkills = computed(() => filterCapabilities(skills.value))
const visibleItems = computed<PoolItem[]>(() => ({ mcp: filteredMcp.value, tools: filteredTools.value, skills: filteredSkills.value })[activePool.value])
const headings: Record<PoolName, { kicker: string; title: string; listTitle: string; description: string; empty: string }> = {
  mcp: { kicker: 'CONNECTIONS', title: 'MCP 池', listTitle: '已注册服务', description: '管理服务连接、凭据引用、超时、并发与发现到的工具。', empty: '暂无 MCP 服务' },
  tools: { kicker: 'EXECUTION', title: '工具池', listTitle: '运行时工具', description: '统一管理内置工具与 MCP 工具的说明、权限、输出和并发策略。', empty: '暂无可用工具' },
  skills: { kicker: 'INSTRUCTIONS', title: 'Skill 池', listTitle: '已解析 Skill', description: '编辑 Skill 元信息、完整指令正文以及随附资源文件。', empty: '暂无 Skill' },
}
const activeHeading = computed(() => headings[activePool.value])
const editingMcpConfig = computed(() => editingMcp.value?.details.registry_config as Record<string, unknown> | undefined || null)
const editingMcpItem = computed<ExtensionItemView | null>(() => editingMcp.value ? ({ name: editingMcp.value.display_name, kind: 'mcp', enabled: true, payload: { ...(editingMcpConfig.value || {}), server_id: serverId(editingMcp.value), display_name: editingMcp.value.display_name, description: editingMcp.value.description } }) : null)
const selectedMcpResources = computed<Array<Record<string, unknown>>>(() => Array.isArray(selectedMcpDetails.value?.details.resources) ? selectedMcpDetails.value!.details.resources as Array<Record<string, unknown>> : [])
const selectedMcpResourceTemplates = computed<Array<Record<string, unknown>>>(() => Array.isArray(selectedMcpDetails.value?.details.resource_templates) ? selectedMcpDetails.value!.details.resource_templates as Array<Record<string, unknown>> : [])
const selectedMcpPrompts = computed<Array<Record<string, unknown>>>(() => Array.isArray(selectedMcpDetails.value?.details.prompts) ? selectedMcpDetails.value!.details.prompts as Array<Record<string, unknown>> : [])
const selectedMcpLogs = computed<Array<Record<string, unknown>>>(() => Array.isArray(selectedMcpDetails.value?.details.logs) ? selectedMcpDetails.value!.details.logs as Array<Record<string, unknown>> : [])
const readingMcpResourceUri = ref('')
const mcpResourcePreview = ref<{ kind: 'image' | 'text' | 'binary'; name: string; content: string } | null>(null)
const mcpResourceTemplateArguments = reactive<Record<string, string>>({})
const readingMcpPromptName = ref('')
const mcpPromptArguments = reactive<Record<string, string>>({})
const mcpPromptPreview = ref<{ name: string; parts: Array<{ role: string; kind: 'image' | 'text'; content: string }> } | null>(null)
const selectedMcpToolCount = computed(() => Number(selectedMcpDetails.value?.details.tool_count ?? (selectedMcpDetails.value ? mcpToolCount(selectedMcpDetails.value.capability_id) : 0)))
const selectedMcpResourceCount = computed(() => selectedMcpResources.value.length + selectedMcpResourceTemplates.value.length)
const selectedMcpPromptCount = computed(() => selectedMcpPrompts.value.length)
const probeSummary = computed(() => {
  if (!probeResult.value) return ''
  const result = probeResult.value
  const facts = [
    result.protocol_version ? `MCP ${result.protocol_version}` : '',
    result.tool_count > 0 ? `${result.tool_count} 个工具` : '',
    result.resource_count + result.resource_template_count > 0
      ? `${result.resource_count + result.resource_template_count} 个资源`
      : '',
    result.prompt_count > 0 ? `${result.prompt_count} 个 Prompt` : '',
  ].filter(Boolean)
  return [result.server_name || 'MCP', ...facts].join(' · ')
})
const selectedResource = computed<SkillEditorResource | null>(() => skillDocument.value?.resources.find(item => item.path === selectedResourcePath.value) || null)
const selectedToolFile = computed<SkillEditorResource | null>(() => toolPackageDocument.value?.files.find(item => item.path === selectedToolFilePath.value) || null)
const approvalOptions = [
  { label: '跟随对话权限', value: 'inherit' }, { label: '自动放行', value: 'allow' },
  { label: '每次确认', value: 'ask' }, { label: '禁止调用', value: 'deny' },
]
const riskOptions = [{ label: '低风险', value: 'low' }, { label: '中风险', value: 'medium' }, { label: '高风险', value: 'high' }]
const parameterTypeOptions = ['string', 'integer', 'number', 'boolean', 'object', 'array'].map(value => ({ label: value, value }))
const skillDisplayName = computed({ get: () => String(skillForm.metadata.display_name || ''), set: value => { if (value.trim()) skillForm.metadata.display_name = value; else delete skillForm.metadata.display_name } })
const skillDescription = computed({ get: () => String(skillForm.metadata.description || ''), set: value => { skillForm.metadata.description = value } })
const skillKeywords = computed<string[]>({
  get: () => { const value = skillForm.metadata.keywords || skillForm.metadata.tags || []; return Array.isArray(value) ? value.map(String) : [] },
  set: value => { skillForm.metadata.keywords = value; delete skillForm.metadata.tags },
})

function capabilitiesOf(kind: CapabilityPoolItem['kind']) { return (snapshot.value?.capabilities || []).filter(item => item.kind === kind) }
function matches(values: unknown[]) { const needle = query.value.trim().toLocaleLowerCase(); return !needle || values.some(value => String(value || '').toLocaleLowerCase().includes(needle)) }
function filterCapabilities(items: CapabilityPoolItem[]) { return items.filter(item => matches([item.display_name, item.description, item.namespace, ...item.keywords, capabilityName(item)])) }
function isMcpServer(item: PoolItem): item is CapabilityPoolItem { return item.kind === 'mcp_server' }
function canDeleteItem(item: PoolItem) {
  return item.kind === 'mcp_server'
    || (item.kind === 'skill' && item.trust_level === 'local_user')
    || (item.kind === 'tool' && item.trust_level === 'local_user' && item.details.implementation_kind === 'python_package')
}
function deleteConfirmation(item: PoolItem) {
  if (item.kind === 'mcp_server') return `删除 ${itemName(item)}，并移除该服务发现的全部工具？`
  return `删除 ${itemName(item)}？此操作会移除对应的本地文件。`
}
function itemKey(item: PoolItem) { return item.capability_id }
function itemName(item: PoolItem) { return capabilityName(item) }
function itemDescription(item: PoolItem) { return item.description || t('common.noDescription') }
function itemEnabled(item: PoolItem) { return item.health === 'healthy' || item.health === null }
function itemType(item: PoolItem) { return ({ mcp_server: 'MCP', mcp_tool: 'MCP TOOL', tool: 'TOOL', skill: 'SKILL' } as const)[item.kind] }
function itemSource(item: PoolItem) { if (item.kind === 'mcp_tool') return '来自 MCP'; if (item.kind === 'tool') return item.trust_level === 'local_user' ? '本地 ToolPackage' : '内置运行时'; if (item.kind === 'skill') return item.trust_level === 'local_user' ? '本地 Skill' : item.trust_level; return transportLabel(item) }
function itemFacts(item: PoolItem) {
  if (item.kind === 'mcp_server') {
    const toolCount = Number(item.details.tool_count ?? mcpToolCount(item.capability_id))
    const resourceCount = Number(item.details.resource_count || 0) + Number(item.details.resource_template_count || 0)
    const promptCount = Number(item.details.prompt_count || 0)
    return [
      toolCount > 0 ? `${toolCount} 个工具` : '',
      resourceCount > 0 ? `${resourceCount} 个资源` : '',
      promptCount > 0 ? `${promptCount} 个 Prompt` : '',
      String(item.details.protocol_version || transportLabel(item)),
    ].filter(Boolean)
  }
  if (item.kind === 'skill') return [`${item.details.content_count || 1} 个文件`, formatBytes(Number(item.details.total_size_bytes || 0))]
  return [item.details.system_available ? '主 Agent' : '按需装配', riskLabel(item.details.risk_level), item.details.allow_parallel_calls ? `${item.details.max_parallel_calls || 1} 并发` : '串行', outputLabel(item)]
}
function itemModelAlias(item: CapabilityPoolItem) { return String(item.details.model_alias || item.details.upstream_tool_name || item.display_name) }
function capabilityName(item: CapabilityPoolItem) {
  if (item.kind === 'mcp_tool') return String(item.details.upstream_tool_name || item.display_name)
  if (item.kind !== 'tool' || item.trust_level !== 'builtin') return item.display_name
  const presentation = toolPresentation(itemModelAlias(item), {})
  return presentation.labelKey ? t(presentation.labelKey as any) : item.display_name
}
function serverId(item: CapabilityPoolItem) { return item.capability_id.replace(/^mcp-server:\/\//, '') }
function mcpToolCount(id: string) { return tools.value.filter(item => item.kind === 'mcp_tool' && item.details.server_capability_id === id).length }
function mcpToolsFor(id: string) { return tools.value.filter(item => item.kind === 'mcp_tool' && item.details.server_capability_id === id) }
function transportLabel(item: CapabilityPoolItem) { return ({ stdio: '本地进程', streamable_http: 'Streamable HTTP', sse: 'SSE' } as Record<string, string>)[String(item.details.transport)] || 'MCP' }
function riskLabel(value: unknown) { return ({ low: '低风险', medium: '中风险', high: '高风险' } as Record<string, string>)[String(value)] || '风险未标注' }
function outputLabel(item: CapabilityPoolItem) { return item.details.output_projection === 'passthrough' ? '原样输出' : `压缩至 ${Number(item.details.output_max_model_chars || 50000).toLocaleString()} 字符` }
function formatBytes(value: number) { if (value < 1024) return `${value} B`; if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`; return `${(value / 1024 / 1024).toFixed(1)} MB` }
function formatMcpLog(entry: Record<string, unknown>) { return typeof entry.data === 'string' ? entry.data : JSON.stringify(entry.data) }
async function readMcpResource(resource: Record<string, unknown>) {
  if (!selectedMcpDetails.value) return
  const uri = String(resource.uri || '')
  if (!uri || readingMcpResourceUri.value) return
  readingMcpResourceUri.value = uri
  mcpResourcePreview.value = null
  try {
    const response = await capabilityPoolsApi.readMcpResource(selectedMcpDetails.value.capability_id, { uri })
    mcpResourcePreview.value = mcpResourcePreviewFrom(response.result, String(resource.name || uri))
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    readingMcpResourceUri.value = ''
  }
}
function resourceTemplateVariables(resource: Record<string, unknown>) {
  const names = new Set<string>()
  for (const expression of String(resource.uri_template || '').matchAll(/\{([^}]+)\}/g)) {
    for (const variable of expression[1].replace(/^[+#./;?&]/, '').split(',')) {
      const name = variable.replace(/[:*].*$/, '').trim()
      if (name) names.add(name)
    }
  }
  return [...names]
}
function resourceArgumentKey(resource: Record<string, unknown>, name: string) { return `${String(resource.uri_template)}\0${name}` }
function resourceTemplateReady(resource: Record<string, unknown>) { return resourceTemplateVariables(resource).every(name => Boolean(mcpResourceTemplateArguments[resourceArgumentKey(resource, name)]?.trim())) }
async function readMcpResourceTemplate(resource: Record<string, unknown>) {
  if (!selectedMcpDetails.value) return
  const uriTemplate = String(resource.uri_template || '')
  if (!uriTemplate || readingMcpResourceUri.value || !resourceTemplateReady(resource)) return
  const arguments_: Record<string, string> = {}
  for (const name of resourceTemplateVariables(resource)) arguments_[name] = mcpResourceTemplateArguments[resourceArgumentKey(resource, name)]
  readingMcpResourceUri.value = uriTemplate
  mcpResourcePreview.value = null
  try {
    const response = await capabilityPoolsApi.readMcpResource(selectedMcpDetails.value.capability_id, { uri_template: uriTemplate, arguments: arguments_ })
    mcpResourcePreview.value = mcpResourcePreviewFrom(response.result, String(resource.name || response.uri))
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    readingMcpResourceUri.value = ''
  }
}
function promptArguments(prompt: Record<string, unknown>) { return Array.isArray(prompt.arguments) ? prompt.arguments as Array<Record<string, unknown>> : [] }
function promptArgumentKey(prompt: Record<string, unknown>, argument: Record<string, unknown>) { return `${String(prompt.name)}\0${String(argument.name)}` }
function promptReady(prompt: Record<string, unknown>) { return promptArguments(prompt).filter(argument => argument.required).every(argument => Boolean(mcpPromptArguments[promptArgumentKey(prompt, argument)]?.trim())) }
async function readMcpPrompt(prompt: Record<string, unknown>) {
  if (!selectedMcpDetails.value) return
  const name = String(prompt.name || '')
  if (!name || readingMcpPromptName.value || !promptReady(prompt)) return
  const arguments_: Record<string, string> = {}
  for (const argument of promptArguments(prompt)) {
    const value = mcpPromptArguments[promptArgumentKey(prompt, argument)]?.trim()
    if (value) arguments_[String(argument.name)] = value
  }
  readingMcpPromptName.value = name
  mcpPromptPreview.value = null
  try {
    const response = await capabilityPoolsApi.getMcpPrompt(selectedMcpDetails.value.capability_id, name, arguments_)
    mcpPromptPreview.value = mcpPromptPreviewFrom(response.result, name)
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    readingMcpPromptName.value = ''
  }
}
function mcpResourcePreviewFrom(result: Record<string, unknown>, name: string) {
  const contents = Array.isArray(result.contents) ? result.contents : []
  const content = contents.find(item => item && typeof item === 'object') as Record<string, unknown> | undefined
  if (!content) return { kind: 'binary' as const, name, content: '' }
  const mimeType = String(content.mimeType || content.mime_type || '')
  const textContent = typeof content.text === 'string' ? content.text : ''
  const blob = typeof content.blob === 'string' ? content.blob : ''
  if (mimeType.startsWith('image/') && blob) {
    return { kind: 'image' as const, name, content: `data:${mimeType};base64,${blob}` }
  }
  if (textContent) return { kind: 'text' as const, name, content: textContent }
  return { kind: 'binary' as const, name, content: '' }
}
function mcpPromptPreviewFrom(result: Record<string, unknown>, name: string) {
  const parts: Array<{ role: string; kind: 'image' | 'text'; content: string }> = []
  for (const messageItem of Array.isArray(result.messages) ? result.messages : []) {
    if (!messageItem || typeof messageItem !== 'object') continue
    const messageRecord = messageItem as Record<string, unknown>
    const role = String(messageRecord.role || 'message')
    const contentItems = Array.isArray(messageRecord.content) ? messageRecord.content : [messageRecord.content]
    for (const contentItem of contentItems) {
      if (!contentItem || typeof contentItem !== 'object') continue
      const content = contentItem as Record<string, unknown>
      if (typeof content.text === 'string') parts.push({ role, kind: 'text', content: content.text })
      else if (typeof content.data === 'string' && String(content.mimeType || content.mime_type).startsWith('image/')) parts.push({ role, kind: 'image', content: `data:${String(content.mimeType || content.mime_type)};base64,${content.data}` })
      else parts.push({ role, kind: 'text', content: JSON.stringify(content, null, 2) })
    }
  }
  if (!parts.length) parts.push({ role: 'result', kind: 'text', content: JSON.stringify(result, null, 2) })
  return { name, parts }
}

async function loadAll() { loading.value = true; loadError.value = ''; try { snapshot.value = await capabilityPoolsApi.snapshot() } catch (error) { loadError.value = error instanceof Error ? error.message : String(error) } finally { loading.value = false } }
function clearProbeNotice() {
  probeResult.value = null
  if (probeNoticeTimer) clearTimeout(probeNoticeTimer)
  probeNoticeTimer = null
}
function showProbeNotice(result: McpProbeResult) {
  clearProbeNotice()
  probeResult.value = result
  probeNoticeTimer = setTimeout(clearProbeNotice, 5000)
}
async function probeMcp(item: CapabilityPoolItem) { probingId.value = item.capability_id; clearProbeNotice(); try { showProbeNotice(await capabilityPoolsApi.probeMcp(item.capability_id)) } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } finally { probingId.value = '' } }
async function deleteItem(item: PoolItem) {
  if (!snapshot.value || deletingId.value || !canDeleteItem(item)) return
  deletingId.value = item.capability_id
  try {
    if (item.kind === 'mcp_server') {
      snapshot.value = await capabilityPoolsApi.deleteMcp(serverId(item), snapshot.value.mcp_registry_digest)
    } else if (item.kind === 'skill') {
      snapshot.value = await capabilityPoolsApi.deleteSkill(item)
    } else {
      snapshot.value = await capabilityPoolsApi.deleteTool(item)
    }
    message.success(`${itemName(item)} 已删除`)
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    deletingId.value = ''
  }
}
function openAddMcp() { editingMcp.value = null; mcpInstallSession.value = null; showMcpModal.value = true }
async function openSkillHub() { showSkillHub.value = true; try { skillHubResult.value = await capabilityPoolsApi.skillHubStatus() } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } }
async function searchSkillHub() { const query = skillHubQuery.value.trim(); if (!query || searchingSkillHub.value) return; searchingSkillHub.value = true; try { skillHubResult.value = await capabilityPoolsApi.searchSkillHub(query) } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } finally { searchingSkillHub.value = false } }
function previewSkillHub(item: SkillHubResult['items'][number]) { selectedSkillHubItem.value = item; showSkillHubPreview.value = true }
function skillHubSourceLabel(source: string) { return source.startsWith('@') ? `企业源 ${source}` : 'SkillHub 社区' }
async function installSkillHub(skill: string) { if (!skill || installingSkill.value) return; installingSkill.value = skill; try { const result = await capabilityPoolsApi.installSkillHub(skill); snapshot.value = result.capability_pool; skillHubResult.value = result.skillhub; message.success(`Skill 已安装并发布：${skill}`) } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } finally { installingSkill.value = '' } }
async function importSkillFolder(event: Event) {
  const selection = selectedFolder(event)
  if (!selection || importingSkill.value) return
  const { rootName, files } = selection
  if (!rootName || !files.some(item => item.relativePath === 'SKILL.md')) {
    message.error('请选择根目录包含 SKILL.md 的 Skill 文件夹')
    return
  }
  importingSkill.value = true
  try {
    snapshot.value = await capabilityPoolsApi.importSkillFolder(rootName, files)
    message.success(`Skill 已上传并发布：${rootName}`)
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    importingSkill.value = false
  }
}
function openToolCreator() {
  toolPreparationOwner.value = null
  showToolCreator.value = true
}
function addToolParameter() { toolCreateForm.parameters.push({ name: '', type: 'string', description: '', required: true }) }
async function loadToolMainFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  toolCreateForm.main_source = await file.text()
}
async function createToolPackage() {
  if (creatingTool.value) return
  creatingTool.value = true
  beginToolPreparation('create', toolCreateForm.dependencies)
  try {
    const { main_source, ...input } = toolCreateForm
    snapshot.value = await capabilityPoolsApi.createToolPackage(
      structuredClone(input),
      main_source,
      updateToolPreparation,
    )
    toolPreparation.status = 'succeeded'
    toolPreparation.stage = 'tool_package_published'
    message.success('工具已通过格式、入口与依赖校验并发布')
  } catch (error) {
    toolPreparation.status = 'failed'
    toolPreparation.error = error instanceof Error ? error.message : String(error)
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    creatingTool.value = false
  }
}
async function importToolFolder(event: Event) {
  const selection = selectedFolder(event)
  if (!selection || importingTool.value) return
  const { rootName, files } = selection
  if (!files.some(item => item.relativePath === 'TOOL.yaml') || !files.some(item => item.relativePath === 'main.py')) {
    message.error('请选择根目录包含 TOOL.yaml 和 main.py 的 ToolPackage 文件夹')
    return
  }
  const requirementsFile = files.find(item => item.relativePath === 'requirements.txt')?.file
  const requirements = requirementsFile
    ? (await requirementsFile.text()).split(/\r?\n/).map(line => line.trim()).filter(line => line && !line.startsWith('#'))
    : []
  importingTool.value = true
  showToolImportProgress.value = true
  beginToolPreparation('import', requirements)
  toolPreparation.stage = 'uploading_tool_package'
  try {
    snapshot.value = await capabilityPoolsApi.importToolFolder(
      rootName,
      files,
      updateToolPreparation,
    )
    toolPreparation.status = 'succeeded'
    toolPreparation.stage = 'tool_package_published'
    message.success(`ToolPackage 已发布：${rootName}`)
  } catch (error) {
    toolPreparation.status = 'failed'
    toolPreparation.error = error instanceof Error ? error.message : String(error)
    message.error(toolPreparation.error)
  } finally {
    importingTool.value = false
  }
}
function beginToolPreparation(owner: 'create' | 'import', requirements: string[]) {
  toolPreparationOwner.value = owner
  toolPreparation.status = 'running'
  toolPreparation.stage = owner === 'import' ? 'uploading_tool_package' : 'assembling_tool_package'
  toolPreparation.logs = []
  toolPreparation.requirements = [...requirements]
  toolPreparation.error = ''
}
function updateToolPreparation(progress: OperationProgress) {
  toolPreparation.stage = progress.stage
  if (progress.stage !== 'dependency_process_output') return
  const messageText = String(progress.detail.message || '').trim()
  if (!messageText) return
  toolPreparation.logs = [...toolPreparation.logs.slice(-79), messageText]
}
function selectedFolder(event: Event): { rootName: string; files: Array<{ file: File; relativePath: string }> } | null {
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files || [])
  input.value = ''
  if (!selected.length) return null
  const firstPath = (selected[0] as File & { webkitRelativePath?: string }).webkitRelativePath || selected[0].name
  const rootName = firstPath.split('/')[0] || ''
  const files = selected.map(file => {
    const path = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    const parts = path.split('/')
    return { file, relativePath: parts.length > 1 ? parts.slice(1).join('/') : parts[0] }
  })
  return rootName ? { rootName, files } : null
}
function openItem(item: PoolItem) { if (item.kind === 'mcp_server') { selectedMcpDetails.value = item; showMcpDetails.value = true; return } editItem(item) }
function editItem(item: PoolItem) { if (item.kind === 'mcp_server') { editingMcp.value = item; mcpInstallSession.value = null; showMcpModal.value = true; return } if (item.kind === 'skill') { void openSkillEditor(item); return } openToolEditor(item) }
function openToolEditor(item: CapabilityPoolItem) { editingTool.value = item; Object.assign(toolForm, { display_name: item.display_name, description: item.description, approval: item.details.approval || 'inherit', risk_level: item.details.risk_level || 'low', allow_parallel_calls: item.details.allow_parallel_calls !== false, max_parallel_calls: Number(item.details.max_parallel_calls || 1), timeout_seconds: Number(item.details.timeout_seconds || 300), output_projection: item.details.output_projection || 'compress', output_max_model_chars: Number(item.details.output_max_model_chars || 50000), retain_raw_output: item.details.retain_raw_output !== false }); showToolEditor.value = true }
function normalizeParallel(value: boolean) { if (!value) toolForm.max_parallel_calls = 1 }
async function saveTool() { if (!editingTool.value) return; savingTool.value = true; try { snapshot.value = await capabilityPoolsApi.updateTool(editingTool.value, { display_name: toolForm.display_name.trim(), description: toolForm.description.trim(), runtime_policy: { approval: toolForm.approval, risk_level: toolForm.risk_level, allow_parallel_calls: toolForm.allow_parallel_calls, max_parallel_calls: toolForm.allow_parallel_calls ? toolForm.max_parallel_calls : 1, timeout_seconds: toolForm.timeout_seconds, output_projection: toolForm.output_projection, output_max_model_chars: toolForm.output_max_model_chars, retain_raw_output: toolForm.retain_raw_output } }); showToolEditor.value = false; message.success('工具配置已发布') } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } finally { savingTool.value = false } }
async function openToolPackageEditor(item: CapabilityPoolItem) {
  showToolPackageEditor.value = true
  loadingToolPackage.value = true
  toolPackageDocument.value = null
  try {
    const document = await capabilityPoolsApi.toolPackageEditor(item.capability_id)
    toolPackageDocument.value = document
    for (const key of Object.keys(toolPackageFiles)) delete toolPackageFiles[key]
    document.files.filter(file => file.editable).forEach(file => { toolPackageFiles[file.path] = file.content || '' })
    selectedToolFilePath.value = document.files.find(file => file.path === 'main.py')?.path || document.files[0]?.path || ''
  } catch (error) {
    showToolPackageEditor.value = false
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    loadingToolPackage.value = false
  }
}
async function saveToolPackageContent() {
  if (!toolPackageDocument.value) return
  savingToolPackage.value = true
  try {
    snapshot.value = await capabilityPoolsApi.updateToolPackageContent(toolPackageDocument.value, { ...toolPackageFiles })
    showToolPackageEditor.value = false
    showToolEditor.value = false
    message.success('ToolPackage 已重新校验并发布')
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    savingToolPackage.value = false
  }
}
async function openSkillEditor(item: CapabilityPoolItem) { showSkillEditor.value = true; loadingSkill.value = true; skillDocument.value = null; skillTab.value = 'metadata'; try { const document = await capabilityPoolsApi.skillEditor(item.capability_id); skillDocument.value = document; skillForm.metadata = structuredClone(document.metadata); skillForm.instructions = document.instructions; for (const key of Object.keys(skillResources)) delete skillResources[key]; document.resources.filter(resource => resource.editable).forEach(resource => { skillResources[resource.path] = resource.content || '' }); selectedResourcePath.value = document.resources[0]?.path || '' } catch (error) { showSkillEditor.value = false; message.error(error instanceof Error ? error.message : String(error)) } finally { loadingSkill.value = false } }
async function saveSkillContent() { if (!skillDocument.value) return; savingSkill.value = true; try { snapshot.value = await capabilityPoolsApi.updateSkillContent(skillDocument.value, { metadata: skillForm.metadata, instructions: skillForm.instructions, resources: { ...skillResources } }); showSkillEditor.value = false; message.success('Skill 已校验并发布') } catch (error) { message.error(error instanceof Error ? error.message : String(error)) } finally { savingSkill.value = false } }
async function saveMcpServers(servers: McpServerConfig[]) {
  if (!snapshot.value) return
  const controller = new AbortController()
  mcpInstallController.value = controller
  savingMcp.value = true
  stoppingMcp.value = false
  mcpInstallSession.value = { status: 'running', stage: 'validating', logs: [], servers: [] }
  try {
    let current = snapshot.value
    if (editingMcp.value) {
      if (servers.length !== 1) throw new Error('编辑 MCP 时只能提交一个服务')
      current = await capabilityPoolsApi.updateMcp(
        serverId(editingMcp.value),
        servers[0],
        current.mcp_registry_digest,
        progress => appendMcpProgress(progress.stage, progress.detail),
        controller.signal,
      )
    } else {
      for (const server of servers) {
        current = await capabilityPoolsApi.addMcp(
          server,
          current.mcp_registry_digest,
          progress => appendMcpProgress(progress.stage, progress.detail),
          controller.signal,
        )
      }
    }
    snapshot.value = current
    mcpInstallSession.value = { ...(mcpInstallSession.value || {}), status: 'ok', stage: 'published' }
    editingMcp.value = null
    message.success('MCP 已校验并发布')
  } catch (error) {
    const cancelled = controller.signal.aborted
    mcpInstallSession.value = {
      ...(mcpInstallSession.value || {}),
      status: cancelled ? 'cancelled' : 'failed',
      error: cancelled ? '' : error instanceof Error ? error.message : String(error),
    }
  } finally {
    savingMcp.value = false
    stoppingMcp.value = false
    mcpInstallController.value = null
  }
}

function appendMcpProgress(stage: string, detail: Record<string, unknown>) {
  const current = mcpInstallSession.value || { status: 'running', logs: [], servers: [] }
  const logs = Array.isArray(current.logs) ? [...current.logs] : []
  logs.push({ stage, detail, at: new Date().toISOString() })
  mcpInstallSession.value = { ...current, status: 'running', stage, logs }
}

function cancelMcpInstall() {
  if (!mcpInstallController.value || stoppingMcp.value) return
  stoppingMcp.value = true
  mcpInstallController.value.abort('user_cancelled')
}

watch(activePool, pool => {
  if (pool !== 'mcp') clearProbeNotice()
})
onMounted(loadAll)
onBeforeUnmount(clearProbeNotice)
</script>

<style scoped>
.hidden-folder-input { display: none; }
.library-page { min-height: 100%; padding: clamp(28px, 4vw, 52px); color: var(--app-text); background: var(--app-surface); }
.library-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 32px; max-width: 1540px; margin: 0 auto 28px; }
.title-block { max-width: 760px; }.eyebrow,.pool-kicker { display: block; margin-bottom: 9px; color: var(--app-text-muted); font-size: 10px; font-weight: 800; letter-spacing: .16em; }.title-block h1 { margin: 0; font-size: clamp(32px, 4vw, 48px); line-height: 1; letter-spacing: -.045em; }.title-block p,.pool-heading p { margin: 13px 0 0; color: var(--app-text-secondary); font-size: 13px; line-height: 1.6; }.header-tools { display: flex; align-items: center; gap: 8px; }.search-input { width: min(360px, 34vw); }
.pool-switcher { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; max-width: 1540px; margin: 0 auto 16px; }.pool-switch { display: grid; grid-template-columns: 1fr auto; gap: 5px 14px; min-width: 0; padding: 16px 18px; color: inherit; text-align: left; border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface); cursor: pointer; transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }.pool-switch:hover { transform: translateY(-1px); border-color: var(--app-border-focus); }.pool-switch.active { border-color: color-mix(in srgb, var(--app-text) 38%, var(--app-border)); box-shadow: inset 0 -2px 0 var(--app-text); }.switch-label { font-size: 12px; font-weight: 750; }.pool-switch strong { grid-row: span 2; align-self: center; font-size: 26px; letter-spacing: -.04em; }.pool-switch small { overflow: hidden; color: var(--app-text-muted); text-overflow: ellipsis; white-space: nowrap; }
.page-alert { max-width: 1540px; margin: 12px auto; }.mcp-probe-notice { display: grid; grid-template-columns: 24px minmax(0, 1fr) 24px; max-width: 1540px; align-items: center; gap: 10px; box-sizing: border-box; margin: 12px auto; padding: 11px 13px; color: #fff; border: 1px solid #000; border-radius: 10px; background: #000; }.mcp-probe-notice > span { display: grid; width: 19px; height: 19px; place-items: center; color: #000; border-radius: 50%; background: #fff; font-size: 10px; }.mcp-probe-notice strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.mcp-probe-notice button { padding: 0; color: #fff; border: 0; background: transparent; font-size: 20px; line-height: 1; cursor: pointer; }.pool-surface { max-width: 1540px; margin: 0 auto; padding: 24px; border: 1px solid var(--app-border); border-radius: 20px; background: var(--app-surface); }.pool-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 2px 2px 22px; border-bottom: 1px solid var(--app-border); }.pool-heading h2 { margin: 0; font-size: 22px; letter-spacing: -.02em; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding-top: 18px; }.pool-card { display: flex; min-height: 214px; flex-direction: column; padding: 17px 18px 14px; border: 1px solid var(--app-border); border-radius: 15px; background: var(--app-surface); cursor: pointer; transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }.pool-card:hover,.pool-card:focus-visible { transform: translateY(-3px); border-color: var(--app-border-focus); box-shadow: 0 14px 30px color-mix(in srgb, var(--app-text) 7%, transparent); outline: none; }.card-header,.card-footer,.card-statuses,.status,.card-buttons,.skill-editor-header,.skill-editor-header > div,.section-row,.switch-line,.card-title-line { display: flex; align-items: center; }.card-header,.card-footer,.section-row,.switch-line { justify-content: space-between; }.card-statuses { gap: 10px; }.type-pill { display: inline-flex; width: fit-content; padding: 4px 7px; border-radius: 6px; background: var(--app-text); color: var(--app-surface); font-size: 9px; font-weight: 800; letter-spacing: .08em; }.status { gap: 6px; color: var(--app-text-muted); font-size: 10px; }.status i { width: 6px; height: 6px; border-radius: 50%; background: var(--app-success); }.status.indexed i { background: var(--app-text); box-shadow: none; }.status.muted i { background: var(--app-text-muted); }.card-body { flex: 1; padding: 22px 0 14px; }.card-title-line { min-width: 0; gap: 9px; }.card-tool-icon { display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; width: 30px; height: 30px; border: 1px solid var(--app-border); border-radius: 9px; background: color-mix(in srgb, var(--app-text) 4%, transparent); color: var(--app-text); }.card-body h3 { margin: 0; overflow: hidden; font-size: 16px; letter-spacing: -.01em; text-overflow: ellipsis; white-space: nowrap; }.card-body p { display: -webkit-box; margin: 8px 0 0; overflow: hidden; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }.card-facts { display: flex; min-height: 24px; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }.card-facts span { padding: 3px 7px; border-radius: 6px; background: color-mix(in srgb, var(--app-text) 5%, transparent); color: var(--app-text-muted); font-size: 9px; }.card-footer { min-height: 30px; padding-top: 11px; border-top: 1px solid var(--app-border); color: var(--app-text-muted); font-size: 10px; }.card-buttons { gap: 1px; }.empty-state { padding: 90px 0; }
.editor-intro { padding: 2px 0 22px; border-bottom: 1px solid var(--app-border); }.editor-intro p { margin: 12px 0 0; color: var(--app-text-secondary); font-size: 12px; }.editor-form { display: grid; gap: 14px; padding-top: 18px; }.form-section { padding: 17px; border: 1px solid var(--app-border); border-radius: 13px; }.form-section.two-column { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }.section-title { display: grid; gap: 3px; margin-bottom: 15px; }.section-title.full { grid-column: 1 / -1; }.section-title strong,.switch-line strong { font-size: 13px; }.section-title span,.switch-line small { color: var(--app-text-muted); font-size: 10px; line-height: 1.5; }.section-row .section-title { margin-bottom: 10px; }.switch-line > span { display: grid; gap: 3px; }
.editor-intro .n-button { margin-top: 14px; }.package-summary { display: flex; flex-wrap: wrap; gap: 8px; padding: 14px 0 0; }.package-summary span { padding: 5px 8px; border: 1px solid var(--app-border); border-radius: 7px; color: var(--app-text-secondary); font-size: 10px; }
.creator-layout { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(0, .92fr); align-items: start; gap: 18px; max-height: 76vh; overflow: auto; }.creator-form { display: grid; min-width: 0; align-content: start; gap: 14px; }.creator-form .form-section,.source-pane { box-sizing: border-box; min-width: 0; }.parameter-card { margin-top: 10px; padding: 14px; border: 1px solid var(--app-border); border-radius: 11px; background: var(--app-surface-subtle, color-mix(in srgb, var(--app-text) 2%, transparent)); }.parameter-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 11px; }.parameter-head > span { color: var(--app-text-secondary); font-size: 11px; font-weight: 700; }.parameter-fields { display: grid; grid-template-columns: minmax(0, 1fr) 140px 82px; gap: 0 10px; }.parameter-fields :deep(.n-form-item) { min-width: 0; margin-bottom: 10px; }.parameter-description { grid-column: 1 / -1; }.required-field :deep(.n-form-item-blank) { align-items: center; }.source-pane { position: sticky; top: 0; padding: 17px; border: 1px solid var(--app-border); border-radius: 13px; }.file-button { position: relative; flex: none; padding: 6px 10px; border: 1px solid var(--app-border); border-radius: 8px; font-size: 11px; cursor: pointer; }.file-button input { position: absolute; width: 1px; height: 1px; opacity: 0; }.full { grid-column: 1 / -1; }
.creator-progress { margin-top: 16px; }
.skill-editor :deep(.n-card__content) { padding-top: 4px; }.skill-editor-header { justify-content: space-between; gap: 20px; min-width: 0; padding: 0 0 16px; border-bottom: 1px solid var(--app-border); }.skill-editor-header > div { gap: 10px; }.skill-editor-header > span { overflow: hidden; color: var(--app-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.skill-pane { padding-top: 18px; }.narrow-pane { width: min(650px, 100%); }.pane-note { display: grid; gap: 3px; margin-bottom: 10px; }.pane-note span { color: var(--app-text-muted); font-size: 10px; }.code-editor :deep(textarea) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; line-height: 1.65; }.resource-editor { display: grid; grid-template-columns: 260px minmax(0, 1fr); min-height: 470px; margin-top: 18px; overflow: hidden; border: 1px solid var(--app-border); border-radius: 12px; }.resource-editor aside { padding: 8px; overflow-y: auto; border-right: 1px solid var(--app-border); background: var(--app-surface-subtle, color-mix(in srgb, var(--app-text) 3%, transparent)); }.resource-editor aside button { display: grid; width: 100%; gap: 3px; padding: 10px; color: inherit; text-align: left; border: 0; border-radius: 8px; background: transparent; cursor: pointer; }.resource-editor aside button:hover,.resource-editor aside button.active { background: var(--app-surface); }.resource-editor aside span { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.resource-editor aside small { color: var(--app-text-muted); font-size: 9px; }.resource-content { min-width: 0; padding: 15px; }.resource-empty { align-self: center; }
.skillhub-modal :deep(.n-card-header),.skillhub-preview-modal :deep(.n-card-header) { display: none; }
.skillhub-modal :deep(.n-card__content),.skillhub-preview-modal :deep(.n-card__content) { padding: 0; }
.skillhub-panel { display: grid; gap: 20px; padding: 30px; }
.skillhub-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.skillhub-header h2 { margin: 0; font-size: 25px; letter-spacing: -.035em; }
.skillhub-header p { margin: 8px 0 0; color: var(--app-text); font-size: 12px; }
.skillhub-connection { display: inline-flex; flex: none; align-items: center; gap: 7px; margin-top: 3px; padding: 6px 10px; color: var(--app-text); border: 1px solid var(--app-border); border-radius: 999px; background: var(--app-surface); font-size: 10px; }
.skillhub-connection i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.skillhub-connection.ready { color: var(--app-surface); border-color: var(--app-text); background: var(--app-text); }
.skillhub-search { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; min-height: 58px; padding: 7px 8px 7px 18px; border: 1px solid var(--app-text); border-radius: 18px; background: var(--app-surface); }
.skillhub-search.disabled { border-style: dashed; }
.skillhub-search input { min-width: 0; padding: 0; color: var(--app-text); border: 0; outline: 0; background: transparent; font: inherit; font-size: 14px; }
.skillhub-search input::placeholder { color: var(--app-text); }
.skillhub-search button { min-width: 78px; height: 42px; padding: 0 18px; color: var(--app-surface); border: 1px solid var(--app-text); border-radius: 13px; background: var(--app-text); font-size: 12px; font-weight: 750; cursor: pointer; }
.skillhub-search button:disabled { color: var(--app-text); background: var(--app-surface); cursor: default; }
.skillhub-unavailable { margin: -8px 2px 0; color: var(--app-text); font-size: 10px; }
.skillhub-results { display: grid; gap: 10px; max-height: 470px; padding-right: 3px; overflow-y: auto; }
.skillhub-results-head { display: flex; align-items: center; justify-content: space-between; padding: 0 2px 4px; }
.skillhub-results-head strong,.skillhub-results-head span { color: var(--app-text); font-size: 11px; }
.skillhub-results article { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; align-items: center; gap: 14px; padding: 16px; border: 1px solid var(--app-border); border-radius: 16px; background: var(--app-surface); cursor: pointer; transition: border-color .16s ease, transform .16s ease; }
.skillhub-results article:hover,.skillhub-results article:focus-visible { border-color: var(--app-text); outline: none; transform: translateY(-1px); }
.skillhub-result-mark,.skillhub-preview-mark { display: grid; place-items: center; color: var(--app-surface); background: var(--app-text); font-weight: 800; }
.skillhub-result-mark { width: 42px; height: 42px; border-radius: 13px; font-size: 15px; }
.skillhub-result-copy { display: grid; min-width: 0; gap: 5px; }
.skillhub-result-copy > div { display: flex; min-width: 0; align-items: baseline; gap: 8px; }
.skillhub-result-copy strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.skillhub-result-copy small,.skillhub-result-copy p,.skillhub-result-copy code { color: var(--app-text); }
.skillhub-result-copy small { flex: none; font-size: 9px; }
.skillhub-result-copy p { display: -webkit-box; margin: 0; overflow: hidden; font-size: 11px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.skillhub-result-copy code { overflow: hidden; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.skillhub-result-actions { display: flex; align-items: center; gap: 8px; }
.skillhub-empty { display: grid; min-height: 180px; place-content: center; gap: 6px; color: var(--app-text); text-align: center; border: 1px dashed var(--app-border); border-radius: 16px; }
.skillhub-empty.initial { min-height: 150px; }
.skillhub-empty strong { color: var(--app-text); font-size: 12px; }
.skillhub-empty span { color: var(--app-text); font-size: 10px; }
.skillhub-preview { display: grid; gap: 24px; padding: 30px; color: var(--app-text); }
.skillhub-preview > header { display: flex; align-items: center; gap: 14px; }
.skillhub-preview-mark { width: 52px; height: 52px; border-radius: 16px; font-size: 18px; }
.skillhub-preview header span { font-size: 10px; font-weight: 750; letter-spacing: .08em; }
.skillhub-preview h2 { margin: 3px 0 0; font-size: 24px; letter-spacing: -.03em; }
.skillhub-preview-summary { margin: 0; font-size: 14px; line-height: 1.75; white-space: pre-wrap; }
.skillhub-preview dl { display: grid; border-top: 1px solid var(--app-border); }
.skillhub-preview dl > div { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 18px; padding: 13px 0; border-bottom: 1px solid var(--app-border); }
.skillhub-preview dt { font-size: 10px; font-weight: 750; }
.skillhub-preview dd { min-width: 0; margin: 0; font-size: 11px; overflow-wrap: anywhere; }
.skillhub-preview footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.skillhub-preview footer > span { max-width: 390px; font-size: 10px; line-height: 1.6; }
.mcp-detail-hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px 18px; padding-bottom: 18px; border-bottom: 1px solid var(--app-border); }.mcp-detail-hero > div { display: flex; min-width: 0; align-items: center; gap: 10px; }.mcp-detail-hero h2 { margin: 0; overflow: hidden; font-size: 20px; text-overflow: ellipsis; white-space: nowrap; }.mcp-detail-hero p { grid-column: 1 / -1; margin: 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; }.mcp-connection-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; margin-top: 18px; overflow: hidden; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-border); }.mcp-connection-facts > div { display: grid; gap: 4px; padding: 13px; background: var(--app-surface); }.mcp-connection-facts small { color: var(--app-text-muted); font-size: 9px; }.mcp-connection-facts strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.mcp-detail-tabs { margin-top: 18px; }.mcp-catalog-list { display: grid; gap: 8px; padding-top: 8px; }.mcp-catalog-list article { display: grid; gap: 5px; padding: 13px; border: 1px solid var(--app-border); border-radius: 11px; }.mcp-catalog-list strong { font-size: 12px; }.mcp-catalog-list p { margin: 0; color: var(--app-text-secondary); font-size: 10px; line-height: 1.55; }.mcp-catalog-list code { overflow-wrap: anywhere; color: var(--app-text-muted); font-size: 9px; }
.mcp-log-list { display: grid; gap: 6px; padding-top: 8px; }.mcp-log-list > p { display: grid; grid-template-columns: 62px minmax(0, 1fr); gap: 10px; margin: 0; padding: 9px 11px; border: 1px solid var(--app-border); border-radius: 9px; }.mcp-log-list span { color: var(--app-text-muted); font-size: 9px; text-transform: uppercase; }.mcp-log-list code { overflow-wrap: anywhere; font-size: 9px; }
.mcp-resource-row { grid-template-columns: minmax(0, 1fr) auto; }.mcp-resource-row > p,.mcp-resource-row > code { grid-column: 1; }.mcp-resource-row > .n-button { grid-column: 2; grid-row: 1 / span 3; align-self: center; }.mcp-resource-preview { margin-top: 12px; padding: 12px; overflow: auto; border: 1px solid var(--app-border); border-radius: 11px; }.mcp-resource-preview img { display: block; max-width: 100%; max-height: 460px; margin: auto; object-fit: contain; }.mcp-resource-preview pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; }
.mcp-catalog-configurable { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 6px 12px; }.mcp-catalog-configurable > strong,.mcp-catalog-configurable > p,.mcp-catalog-configurable > code,.mcp-catalog-configurable > .mcp-argument-grid { grid-column: 1; }.mcp-catalog-configurable > .n-button { grid-column: 2; grid-row: 1 / span 4; align-self: center; }.mcp-argument-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin-top: 4px; }.mcp-prompt-preview > strong { display: block; margin-bottom: 10px; }.mcp-prompt-preview article + article { margin-top: 12px; }.mcp-prompt-preview small { display: block; margin-bottom: 5px; color: var(--app-text-secondary); font-weight: 700; text-transform: uppercase; }
@media (max-width: 920px) { .library-header { align-items: flex-start; flex-direction: column; }.header-tools,.search-input { width: 100%; }.pool-switcher { grid-template-columns: repeat(2, 1fr); }.resource-editor { grid-template-columns: 210px minmax(0, 1fr); }.creator-layout { grid-template-columns: 1fr; }.source-pane { position: static; }.parameter-fields { grid-template-columns: minmax(0, 1fr) 140px 82px; } }
@media (max-width: 620px) { .library-page { padding: 20px 14px; }.pool-switcher { grid-template-columns: 1fr 1fr; }.pool-switch { padding: 13px; }.pool-switch small { display: none; }.pool-surface { padding: 15px; }.pool-heading { align-items: flex-start; flex-direction: column; }.card-grid { grid-template-columns: 1fr; }.resource-editor { grid-template-columns: 1fr; }.resource-editor aside { max-height: 160px; border-right: 0; border-bottom: 1px solid var(--app-border); }.form-section.two-column,.parameter-fields { grid-template-columns: 1fr; }.parameter-description { grid-column: auto; }.skillhub-panel,.skillhub-preview { padding: 22px 18px; }.skillhub-header { gap: 12px; }.skillhub-search { min-height: 52px; padding-left: 14px; }.skillhub-search button { min-width: 64px; height: 38px; padding: 0 13px; }.skillhub-results article { grid-template-columns: 38px minmax(0, 1fr); }.skillhub-result-mark { width: 38px; height: 38px; }.skillhub-result-actions { grid-column: 2; justify-self: start; }.skillhub-preview footer { align-items: flex-start; flex-direction: column; }.skillhub-preview dl > div { grid-template-columns: 86px minmax(0, 1fr); } }
</style>
