import {type FactoryMode} from './protocol.js';

export type ShellCommandSpec = {
	name: string;
	usage: string;
	description: string;
	availableIn: Array<FactoryMode | 'root' | 'interrupt'>;
};

export const shellCommands: ShellCommandSpec[] = [
	{name: '/chat', usage: '/chat', description: '进入聊天模式', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/create-agent', usage: '/create-agent', description: '进入 Agent 制造模式', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/exit', usage: '/exit', description: '退出当前模式', availableIn: ['chat', 'create_agent']},
	{name: '/quit', usage: '/quit', description: '退出 CLI', availableIn: ['root', 'chat', 'create_agent', 'interrupt']},
	{name: '/help', usage: '/help', description: '显示命令帮助', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/session', usage: '/session', description: '显示当前会话', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/sessions', usage: '/sessions', description: '列出历史会话', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/new-session', usage: '/new-session', description: '创建新会话', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/resume', usage: '/resume <session_id>', description: '切换到指定会话', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/tools', usage: '/tools', description: '显示工厂基础工具', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/stages', usage: '/stages', description: '显示 FactoryGraph 阶段', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/state', usage: '/state on|off', description: '切换最终 state 展示', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/messages', usage: '/messages on|off', description: '切换最终 messages 展示', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/tool-grep', usage: '/tool-grep <query|off>', description: '过滤工具执行与 Observation 展示', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/stop', usage: '/stop <stage_id|off>', description: '设置制造阶段断点', availableIn: ['root', 'chat', 'create_agent']}
];

export const factoryStages = [
	'requirement_capture',
	'runtime_pattern_selection',
	'graph_behavior_planning',
	'node_strategy_planning',
	'tool_capability_planning',
	'resource_and_condition_planning',
	'assembly_spec_generation',
	'package_generation',
	'harness_generation_and_test',
	'repair_or_finalize'
];

export const factoryToolGroups = [
	'filesystem: file_read, file_write, file_patch, file_list, file_exists, file_mkdir, file_copy',
	'search: search_files, search_text, search_inspect_text, search_inspect_file',
	'shell: shell_run, shell_run_text, shell_which, shell_cwd, shell_start, shell_status, shell_grep_process, shell_stop'
];

export function visibleCommands(mode: FactoryMode | null, hasInterrupt: boolean): ShellCommandSpec[] {
	const scope: FactoryMode | 'root' | 'interrupt' = hasInterrupt ? 'interrupt' : mode ?? 'root';
	return shellCommands.filter(item => item.availableIn.includes(scope));
}

export function commandSuggestions(input: string, mode: FactoryMode | null, hasInterrupt: boolean): ShellCommandSpec[] {
	if (hasInterrupt) {
		return [
			{name: '-y', usage: '-y', description: '批准当前 interrupt 或工具调用', availableIn: ['interrupt']},
			{name: '-n', usage: '-n', description: '拒绝当前 interrupt 或工具调用', availableIn: ['interrupt']}
		];
	}
	if (!input.startsWith('/')) {
		return visibleCommands(mode, false).slice(0, 6);
	}
	return visibleCommands(mode, false)
		.filter(item => item.name.startsWith(input.split(/\s+/)[0] ?? ''))
		.slice(0, 6);
}
