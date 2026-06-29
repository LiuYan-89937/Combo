import {type FactoryMode} from './protocol.js';

export type ShellCommandSpec = {
	name: string;
	usage: string;
	description: string;
	availableIn: Array<FactoryMode | 'root' | 'interrupt'>;
};

export const shellCommands: ShellCommandSpec[] = [
	{name: '/chat', usage: '/chat', description: '进入 SystemPackage 聊天模式', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/create-agent', usage: '/create-agent', description: '进入 Agent 制造模式', availableIn: ['root', 'chat', 'create_agent']},
	{name: '/evolve-agent', usage: '/evolve-agent', description: '选择已发布 Agent 并进入进化模式', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/exit', usage: '/exit', description: '退出当前模式', availableIn: ['chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/quit', usage: '/quit', description: '退出 CLI', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package', 'interrupt']},
	{name: '/help', usage: '/help', description: '显示命令帮助', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/session', usage: '/session', description: '显示当前会话', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/sessions', usage: '/sessions', description: '打开历史会话选择器', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/new-session', usage: '/new-session', description: '创建新会话', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/resume', usage: '/resume <session_id>', description: '按完整 id 切换会话', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/run-agent-package', usage: '/run-agent-package', description: '扫描正式产物目录并进入已生产 Agent', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/cancel', usage: '/cancel', description: '取消当前正在运行的请求', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/scheduler', usage: '/scheduler <list|describe|runs|pause|resume|delete|run-now>', description: '管理定时任务与执行记录', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/agent-sessions', usage: '/agent-sessions', description: '选择当前 AgentPackage 的会话', availableIn: ['agent_package']},
	{name: '/tools', usage: '/tools', description: '显示工厂基础工具', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/state', usage: '/state on|off', description: '切换最终 state 展示', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/messages', usage: '/messages on|off', description: '切换最终 messages 展示', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']},
	{name: '/tool-grep', usage: '/tool-grep <query|off>', description: '过滤工具执行与 Observation 展示', availableIn: ['root', 'chat', 'create_agent', 'evolve_agent', 'agent_package']}
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
