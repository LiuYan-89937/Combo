import React, {useEffect, useMemo, useState} from 'react';
import {Box, Text, useInput} from 'ink';
import {
	buildPlanReviewContinuePayload,
	buildPlanReviewRevisionPayload,
	buildRequirementClarificationResumePayload,
	buildResourceCollectionPayload,
	buildResourceCollectionSkipPayload,
	buildResourceConfirmationApprovePayload,
	buildResourceConfirmationRevisePayload,
	buildResourceConfirmationSkipPayload,
	buildSchedulerSeedReviewApprovePayload,
	buildSchedulerSeedReviewRevisePayload,
	buildSchedulerSeedReviewSkipPayload,
	buildToolApprovalPayload,
	buildToolApprovalRevisionPayload,
	buildToolTrustPayload,
	type RequirementClarificationAnswer
} from '../interrupts.js';
import {type FactoryEvent} from '../protocol.js';
import {useStoreSelector} from '../state/useStoreSelector.js';

type ChoiceOption = {
	id: string;
	label: string;
	description?: string;
	custom?: boolean;
};

type ToolApprovalActionId = 'approve' | 'deny' | 'revise' | 'trust';

type ToolApprovalAction = {
	id: ToolApprovalActionId;
	label: string;
	key: string;
	color: string;
	description: string;
};

const TOOL_APPROVAL_ACTIONS: ToolApprovalAction[] = [
	{
		id: 'approve',
		label: '批准执行',
		key: 'y',
		color: 'green',
		description: '本次参数没有问题，继续执行工具。'
	},
	{
		id: 'deny',
		label: '拒绝执行',
		key: 'n',
		color: 'red',
		description: '不执行工具，把拒绝作为 observation 返回给模型。'
	},
	{
		id: 'revise',
		label: '要求重写',
		key: 'r',
		color: 'cyan',
		description: '输入审查意见，让模型基于你的意见重新生成 tool call。'
	},
	{
		id: 'trust',
		label: '信任该工具',
		key: 't',
		color: 'yellow',
		description: '允许该工具后续按当前信任语义减少重复确认。'
	}
];

export function InterruptChoicePanel({
	onSubmit
}: {
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const event = useStoreSelector(state => state.pendingInterrupt);
	const interruptType = String(event?.payload?.type ?? event?.event_type ?? '');
	if (!event || !['requirement_clarification', 'plan_review', 'tool_approval', 'resource_collection', 'resource_confirmation', 'scheduler_seed_review'].includes(interruptType)) {
		return null;
	}
	if (interruptType === 'requirement_clarification') {
		return <RequirementClarificationTabs event={event} onSubmit={onSubmit} />;
	}
	if (interruptType === 'plan_review') {
		return <PlanReviewTabs event={event} onSubmit={onSubmit} />;
	}
	if (interruptType === 'resource_collection') {
		return <ResourceCollectionPanel event={event} onSubmit={onSubmit} />;
	}
	if (interruptType === 'resource_confirmation') {
		return <ResourceConfirmationPanel event={event} onSubmit={onSubmit} />;
	}
	if (interruptType === 'scheduler_seed_review') {
		return <SchedulerSeedReviewPanel event={event} onSubmit={onSubmit} />;
	}
	return <ToolApprovalTabs event={event} onSubmit={onSubmit} />;
}

export function isChoiceInterrupt(event: FactoryEvent | null): boolean {
	const interruptType = String(event?.payload?.type ?? event?.event_type ?? '');
	return ['requirement_clarification', 'plan_review', 'tool_approval', 'resource_collection', 'resource_confirmation', 'scheduler_seed_review'].includes(interruptType);
}

function RequirementClarificationTabs({
	event,
	onSubmit
}: {
	event: FactoryEvent;
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const questions = useMemo(() => ((event.payload?.questions as Array<Record<string, unknown>>) ?? []), [event.payload]);
	const [questionIndex, setQuestionIndex] = useState(0);
	const [optionIndex, setOptionIndex] = useState(0);
	const [answers, setAnswers] = useState<Record<string, RequirementClarificationAnswer>>({});
	const [customMode, setCustomMode] = useState(false);
	const [customText, setCustomText] = useState('');

	useEffect(() => {
		setQuestionIndex(0);
		setOptionIndex(0);
		setAnswers({});
		setCustomMode(false);
		setCustomText('');
	}, [event.event_id]);

	const question = questions[questionIndex] ?? {};
	const options = optionsForQuestion(question);
	const questionId = String(question.id ?? `question_${questionIndex + 1}`);
	const selected = options[optionIndex] ?? options[0];

	useInput((input, key) => {
		if (!questions.length) {
			return;
		}
		if (customMode) {
			if (key.return) {
				commitAnswer({
					questionId,
					option: selected,
					customText,
					answers,
					setAnswers,
					questions,
					questionIndex,
					setQuestionIndex,
					onSubmit
				});
				setCustomMode(false);
				setCustomText('');
				return;
			}
			if (key.escape) {
				setCustomMode(false);
				setCustomText('');
				return;
			}
			if (key.backspace || key.delete) {
				setCustomText(current => current.slice(0, -1));
				return;
			}
			if (input && !key.ctrl && !key.meta) {
				setCustomText(current => current + input);
			}
			return;
		}
		if (key.leftArrow) {
			setQuestionIndex(current => Math.max(0, current - 1));
			setOptionIndex(0);
			return;
		}
		if (key.rightArrow) {
			setQuestionIndex(current => Math.min(questions.length - 1, current + 1));
			setOptionIndex(0);
			return;
		}
		if (key.upArrow) {
			setOptionIndex(current => Math.max(0, current - 1));
			return;
		}
		if (key.downArrow) {
			setOptionIndex(current => Math.min(options.length - 1, current + 1));
			return;
		}
		if (key.return && selected) {
			if (selected.custom) {
				setCustomMode(true);
				return;
			}
			commitAnswer({
				questionId,
				option: selected,
				customText: '',
				answers,
				setAnswers,
				questions,
				questionIndex,
				setQuestionIndex,
				onSubmit
			});
		}
	});

	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold color="yellow">Requirement Clarification</Text>
			<Box>
				{questions.map((item, index) => (
					<Text key={String(item.id ?? index)} color={index === questionIndex ? 'black' : answered(answers, item, index) ? 'green' : 'gray'} backgroundColor={index === questionIndex ? 'yellow' : undefined}>
						{` Q${index + 1} `}
					</Text>
				))}
			</Box>
			<Text>{String(question.question ?? questionId)}</Text>
			{options.map((option, index) => (
				<Text key={option.id} color={index === optionIndex ? 'yellow' : 'gray'}>
					{index === optionIndex ? '> ' : '  '}
					{option.label}
					{option.description ? ` - ${option.description}` : ''}
				</Text>
			))}
			{customMode && (
				<Text color="cyan">
					自定义输入：{customText}
					<Text inverse>{' '}</Text>
				</Text>
			)}
			<Text color="gray">Left/Right 切换问题，Up/Down 选择，Enter 确认；自定义项会进入输入模式。</Text>
		</Box>
	);
}

function PlanReviewTabs({
	event,
	onSubmit
}: {
	event: FactoryEvent;
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const [selected, setSelected] = useState(0);
	const [revisionMode, setRevisionMode] = useState(false);
	const [revisionText, setRevisionText] = useState('');
	useEffect(() => {
		setSelected(0);
		setRevisionMode(false);
		setRevisionText('');
	}, [event.event_id]);
	useInput((input, key) => {
		if (revisionMode) {
			if (key.return) {
				onSubmit(buildPlanReviewRevisionPayload(revisionText));
				return;
			}
			if (key.escape) {
				setRevisionMode(false);
				setRevisionText('');
				return;
			}
			if (key.backspace || key.delete) {
				setRevisionText(current => current.slice(0, -1));
				return;
			}
			if (input && !key.ctrl && !key.meta) {
				setRevisionText(current => current + input);
			}
			return;
		}
		if (key.leftArrow || key.upArrow) {
			setSelected(0);
			return;
		}
		if (key.rightArrow || key.downArrow) {
			setSelected(1);
			return;
		}
		if (key.return) {
			if (selected === 0) {
				onSubmit(buildPlanReviewContinuePayload());
			} else {
				setRevisionMode(true);
			}
		}
	});
	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold color="yellow">Plan Review</Text>
			<Text>{String(event.payload?.plan_text ?? '').slice(0, 2200)}</Text>
			<Box marginTop={1}>
				<Tab label="继续" active={selected === 0} />
				<Tab label="修改" active={selected === 1} />
			</Box>
			{revisionMode && (
				<Text color="cyan">
					修改意见：{revisionText}
					<Text inverse>{' '}</Text>
				</Text>
			)}
			<Text color="gray">Left/Right 选择，Enter 确认；修改会进入输入模式。</Text>
		</Box>
	);
}

function ToolApprovalTabs({
	event,
	onSubmit
}: {
	event: FactoryEvent;
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const [selected, setSelected] = useState(0);
	const [revisionMode, setRevisionMode] = useState(false);
	const [revisionText, setRevisionText] = useState('');
	const requests = (event.payload?.requests as Array<Record<string, unknown>>) ?? [];
	const selectedAction = TOOL_APPROVAL_ACTIONS[selected] ?? TOOL_APPROVAL_ACTIONS[0];
	useEffect(() => {
		setSelected(0);
		setRevisionMode(false);
		setRevisionText('');
	}, [event.event_id]);
	useInput((input, key) => {
		if (revisionMode) {
			if (key.return) {
				onSubmit(buildToolApprovalRevisionPayload(revisionText));
				return;
			}
			if (key.escape) {
				setRevisionMode(false);
				setRevisionText('');
				return;
			}
			if (key.backspace || key.delete) {
				setRevisionText(current => current.slice(0, -1));
				return;
			}
			if (input && !key.ctrl && !key.meta) {
				setRevisionText(current => current + input);
			}
			return;
		}
		if (input === 'r') {
			setSelected(actionIndex('revise'));
			setRevisionMode(true);
			return;
		}
		if (key.leftArrow || key.upArrow) {
			setSelected(current => Math.max(0, current - 1));
			return;
		}
		if (input === 'y') {
			onSubmit(buildToolApprovalPayload(true));
			return;
		}
		if (input === 'n') {
			onSubmit(buildToolApprovalPayload(false));
			return;
		}
		if (input === 't') {
			onSubmit(buildToolTrustPayload());
			return;
		}
		if (key.rightArrow || key.downArrow) {
			setSelected(current => Math.min(TOOL_APPROVAL_ACTIONS.length - 1, current + 1));
			return;
		}
		if (key.return) {
			if (selectedAction.id === 'revise') {
				setRevisionMode(true);
				return;
			}
			if (selectedAction.id === 'trust') {
				onSubmit(buildToolTrustPayload());
				return;
			}
			onSubmit(buildToolApprovalPayload(selectedAction.id === 'approve'));
		}
	});
	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold color="yellow">Tool Approval Dock</Text>
			<Text color="gray">检查工具、参数和影响范围；选择后此面板会归档到 Tool Activity。</Text>
			{requests.map((item, index) => (
				<Box key={String(item.tool_call_id ?? index)} flexDirection="column" marginTop={1} borderStyle="single" borderColor="gray" paddingX={1}>
					<Text>
						<Text color="yellow">▾ {index + 1}. </Text>
						<Text bold>{String(item.tool_name ?? '-')}</Text>
						<Text color="gray">  call </Text>
						{shortId(String(item.tool_call_id ?? '-'))}
					</Text>
					<Text color="gray">summary: {String(item.summary ?? 'awaiting review')}</Text>
					<Text color="yellow">risk: {String(item.risk_level ?? 'unknown')}</Text>
					{riskReasonLines(item.risk_reasons).map((line, lineIndex) => (
						<Text key={`${item.tool_call_id ?? index}:risk:${lineIndex}`} color="gray">
							- {line}
						</Text>
					))}
					{approvalArgumentLines(item.args ?? item.arguments ?? {}).map(line => (
						<Text key={`${item.tool_call_id ?? index}:${line.label}`} color="white">
							<Text color="gray">{line.label}: </Text>
							{line.value}
						</Text>
					))}
				</Box>
			))}
			<Box marginTop={1} flexDirection="column">
				<Box>
					{TOOL_APPROVAL_ACTIONS.map((action, index) => (
						<ActionTab key={action.id} action={action} active={selected === index} />
					))}
				</Box>
				<Text color={selectedAction.color}>
					{selectedAction.description}
				</Text>
			</Box>
			{revisionMode && (
				<Text color="cyan">
					审查意见：{revisionText}
					<Text inverse>{' '}</Text>
				</Text>
			)}
			<Text color="gray">Left/Right 选择，Enter 确认；y 批准，n 拒绝，r 重写，t 信任；Esc 退出审查输入。</Text>
		</Box>
	);
}

function ResourceCollectionPanel({
	event,
	onSubmit
}: {
	event: FactoryEvent;
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const questions = useMemo(() => resourceCollectionQuestions(event), [event]);
	const fields = useMemo(() => resourceCollectionFields(event), [event]);
	const reasonNotes = useMemo(() => resourceCollectionReasonNotes(event), [event]);
	const scope = resourceCollectionScope(event);
	const [answer, setAnswer] = useState('');

	useEffect(() => {
		setAnswer('');
	}, [event.event_id]);

	useInput((input, key) => {
		if (key.return) {
			if (answer.trim()) {
				onSubmit(buildResourceCollectionPayload(answer.trim()));
			}
			return;
		}
		if (key.escape) {
			onSubmit(buildResourceCollectionSkipPayload());
			return;
		}
		if (key.backspace || key.delete) {
			setAnswer(current => current.slice(0, -1));
			return;
		}
		if (input && !key.ctrl && !key.meta) {
			setAnswer(current => current + input);
		}
	});

	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold color="yellow">{String(event.payload?.title ?? '补充外部资源')}</Text>
			<Text color="gray">{String(event.payload?.message ?? '请直接用一句话说明可以使用的外部资源。')}</Text>
			<Text color={scope === 'missing_fields' ? 'cyan' : 'gray'}>
				{scope === 'missing_fields' ? '只需补充下面缺口；已经确认的资源会继续沿用。' : '请提供这个 Agent 可使用的外部资源与运行配置。'}
			</Text>
			{reasonNotes.map(note => (
				<Text key={note} color="gray">原因: {note}</Text>
			))}
			{fields.length > 0 ? fields.map((field, index) => (
				<Box key={field.key} flexDirection="column" marginTop={index === 0 ? 0 : 1}>
					<Text>
						<Text color="yellow">{index === 0 ? '> ' : '  '}</Text>
						<Text bold>{field.title}</Text>
						<Text color={field.required ? 'red' : 'gray'}> {field.required ? '必填' : '可选'}</Text>
						{field.secret ? <Text color="gray"> 密文</Text> : null}
						{field.strategyLabels.length > 0 ? <Text color="gray"> / {field.strategyLabels.join('、')}</Text> : null}
					</Text>
					<Text color="gray">  {field.question}</Text>
					{field.description ? <Text color="gray">  {field.description}</Text> : null}
					{field.placeholder ? <Text color="gray">  示例: {field.placeholder}</Text> : null}
				</Box>
			)) : questions.map((question, index) => (
				<Text key={`${question}-${index}`}>
					<Text color="yellow">{index === 0 ? '> ' : '  '}</Text>
					{question}
				</Text>
			))}
			<Text>
				<Text color="gray">回答: </Text>
				{answer}
				<Text inverse>{' '}</Text>
			</Text>
			<Text color="gray">可以一句话回答；Enter 提交；Esc 暂不提供。</Text>
		</Box>
	);
}

function ResourceConfirmationPanel({
	event,
	onSubmit
}: {
	event: FactoryEvent;
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const items = useMemo(() => resourceConfirmationItems(event), [event]);
	const [mode, setMode] = useState<'review' | 'revise'>('review');
	const [revisionText, setRevisionText] = useState('');

	useEffect(() => {
		setMode('review');
		setRevisionText('');
	}, [event.event_id]);

	useInput((input, key) => {
		if (mode === 'revise') {
			if (key.return) {
				if (revisionText.trim()) {
					onSubmit(buildResourceConfirmationRevisePayload(revisionText.trim()));
				}
				return;
			}
			if (key.escape) {
				setMode('review');
				setRevisionText('');
				return;
			}
			if (key.backspace || key.delete) {
				setRevisionText(current => current.slice(0, -1));
				return;
			}
			if (input && !key.ctrl && !key.meta) {
				setRevisionText(current => current + input);
			}
			return;
		}
		if (input.toLowerCase() === 'y' || key.return) {
			onSubmit(buildResourceConfirmationApprovePayload());
			return;
		}
		if (input.toLowerCase() === 'r') {
			setMode('revise');
			return;
		}
		if (input.toLowerCase() === 'n' || key.escape) {
			onSubmit(buildResourceConfirmationSkipPayload());
		}
	});

	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold color="yellow">{String(event.payload?.title ?? '确认外部资源')}</Text>
			<Text color="gray">{String(event.payload?.message ?? '确认后继续制造工具。')}</Text>
			{items.map(item => (
				<Text key={item.key}>
					<Text color={item.required ? 'yellow' : 'gray'}>{item.required ? '> ' : '  '}</Text>
					{item.title}: {item.valueSummary}
					<Text color="gray">
						{'  '}
						{item.sourceLabel}
						{item.statusLabel ? ` / ${item.statusLabel}` : ''}
						{item.secret ? ' / 密文' : ''}
						{item.evidenceCount > 0 ? ` / 证据 ${item.evidenceCount} 条` : ''}
					</Text>
				</Text>
			))}
			{mode === 'revise' ? (
				<Text color="cyan">
					修改说明：{revisionText}
					<Text inverse>{' '}</Text>
				</Text>
			) : null}
			<Text color="gray">Enter/y 确认；r 修改；n/Esc 暂不提供。</Text>
		</Box>
	);
}

function SchedulerSeedReviewPanel({
	event,
	onSubmit
}: {
	event: FactoryEvent;
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const seeds = useMemo(() => schedulerSeedReviewItems(event), [event]);
	const missingQuestions = useMemo(() => schedulerSeedMissingQuestions(event), [event]);
	const [revisionText, setRevisionText] = useState('');

	useEffect(() => {
		setRevisionText('');
	}, [event.event_id]);

	useInput((input, key) => {
		if (key.return) {
			if (revisionText.trim()) {
				onSubmit(buildSchedulerSeedReviewRevisePayload(revisionText.trim()));
			} else {
				onSubmit(buildSchedulerSeedReviewApprovePayload());
			}
			return;
		}
		if (key.escape) {
			onSubmit(buildSchedulerSeedReviewSkipPayload());
			return;
		}
		if (key.backspace || key.delete) {
			setRevisionText(current => current.slice(0, -1));
			return;
		}
		if (input && !key.ctrl && !key.meta) {
			setRevisionText(current => current + input);
		}
	});

	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold color="yellow">{String(event.payload?.title ?? '确认定时任务')}</Text>
			<Text color="gray">{String(event.payload?.message ?? '请确认或修改定时任务。')}</Text>
			{seeds.map(seed => (
				<Box key={seed.seedId} flexDirection="column" marginTop={1}>
					<Text><Text color="yellow">{'> '}</Text><Text bold>{seed.title}</Text></Text>
					<Text color="gray">  时间：{seed.humanSchedule || '需要补充'}</Text>
					<Text color="gray">  动作：{seed.taskContent || '运行 Agent'}</Text>
					<Text color="gray">  失败治理：连续失败 {seed.maxConsecutiveFailures} 次后自动暂停</Text>
					<Text color="gray">  完成反馈：{seed.feedbackEnabled ? '开启' : '关闭'}</Text>
					<Text color="gray">  高级：{seed.scheduleType || '-'} {seed.scheduleExpr || '-'} / {seed.timezone || '-'}</Text>
				</Box>
			))}
			{missingQuestions.map(question => (
				<Text key={question} color="red">还需确认：{question}</Text>
			))}
			<Text>
				<Text color="gray">修改: </Text>
				{revisionText}
				<Text inverse>{' '}</Text>
			</Text>
			<Text color="gray">直接 Enter 确认；输入一句话修改后 Enter；Esc 暂不定时。</Text>
		</Box>
	);
}

function actionIndex(actionId: ToolApprovalActionId): number {
	return Math.max(0, TOOL_APPROVAL_ACTIONS.findIndex(action => action.id === actionId));
}

function ActionTab({action, active}: {action: ToolApprovalAction; active: boolean}) {
	return (
		<Text color={active ? 'black' : action.color} backgroundColor={active ? action.color : undefined}>
			{` ${action.label}(${action.key}) `}
		</Text>
	);
}

function Tab({label, active}: {label: string; active: boolean}) {
	return (
		<Text color={active ? 'black' : 'yellow'} backgroundColor={active ? 'yellow' : undefined}>
			{` ${label} `}
		</Text>
	);
}

function riskReasonLines(value: unknown): string[] {
	if (!Array.isArray(value)) {
		return [];
	}
	return value.map(item => trimOneLine(String(item), 180)).filter(Boolean).slice(0, 4);
}

function approvalArgumentLines(value: unknown): Array<{label: string; value: string}> {
	if (value === undefined || value === null || value === '') {
		return [{label: 'args', value: 'none'}];
	}
	if (typeof value !== 'object' || Array.isArray(value)) {
		return [{label: 'args', value: formatApprovalValue(value)}];
	}
	const record = value as Record<string, unknown>;
	const entries = Object.entries(record).slice(0, 8);
	const lines = entries.map(([key, item]) => ({label: key, value: formatApprovalValue(item)}));
	if (Object.keys(record).length > entries.length) {
		lines.push({label: 'more', value: `${Object.keys(record).length - entries.length} fields collapsed`});
	}
	return lines.length ? lines : [{label: 'args', value: 'none'}];
}

function formatApprovalValue(value: unknown): string {
	if (typeof value === 'string') {
		return trimOneLine(value, 240);
	}
	if (typeof value === 'number' || typeof value === 'boolean') {
		return String(value);
	}
	if (value === null) {
		return 'null';
	}
	if (Array.isArray(value)) {
		if (value.every(item => typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean')) {
			return trimOneLine(value.join(', '), 240);
		}
		return `${value.length} items`;
	}
	if (value && typeof value === 'object') {
		const keys = Object.keys(value as Record<string, unknown>);
		return keys.length ? `{ ${keys.slice(0, 4).join(', ')}${keys.length > 4 ? ', ...' : ''} }` : '{}';
	}
	return trimOneLine(String(value), 240);
}

function resourceCollectionQuestions(event: FactoryEvent): string[] {
	const questions = event.payload?.questions;
	if (!Array.isArray(questions)) {
		return [];
	}
	return questions.map(item => String(item).trim()).filter(Boolean).slice(0, 6);
}

function resourceCollectionScope(event: FactoryEvent): 'full_request' | 'missing_fields' {
	return event.payload?.scope === 'missing_fields' ? 'missing_fields' : 'full_request';
}

type ResourceCollectionField = {
	key: string;
	title: string;
	question: string;
	description: string;
	placeholder: string;
	required: boolean;
	secret: boolean;
	strategyLabels: string[];
};

function resourceCollectionFields(event: FactoryEvent): ResourceCollectionField[] {
	const fields = event.payload?.fields;
	if (!Array.isArray(fields)) {
		return [];
	}
	return fields.map((item, index) => {
		const record = item && typeof item === 'object' ? item as Record<string, unknown> : {};
		const key = String(record.key ?? `field_${index + 1}`);
		return {
			key,
			title: normalizeResourceTitle(String(record.title ?? key), key),
			question: normalizeResourceSentence(String(record.question ?? '请补充这个配置。'), 120),
			description: normalizeResourceSentence(String(record.description ?? ''), 160),
			placeholder: normalizeResourceSentence(String(record.placeholder ?? ''), 100),
			required: Boolean(record.required),
			secret: Boolean(record.secret),
			strategyLabels: resourceStrategyLabels(record.resolution_strategy)
		};
	}).filter(field => field.title.trim()).slice(0, 10);
}

function resourceCollectionReasonNotes(event: FactoryEvent): string[] {
	const notes = event.payload?.reason_notes;
	if (!Array.isArray(notes)) {
		return [];
	}
	return notes.map(item => String(item).trim()).filter(Boolean).slice(0, 3);
}

type ResourceConfirmationItem = {
	key: string;
	title: string;
	valueSummary: string;
	required: boolean;
	secret: boolean;
	sourceLabel: string;
	statusLabel: string;
	evidenceCount: number;
};

function resourceConfirmationItems(event: FactoryEvent): ResourceConfirmationItem[] {
	const items = event.payload?.items;
	if (!Array.isArray(items)) {
		return [];
	}
	return items.map((item, index) => {
		const record = item && typeof item === 'object' ? item as Record<string, unknown> : {};
		const key = String(record.key ?? `item_${index + 1}`);
		return {
			key,
			title: normalizeResourceTitle(String(record.title ?? key), key),
			valueSummary: normalizeResourceSentence(String(record.value_summary ?? record.valueSummary ?? '未提供'), 220),
			required: Boolean(record.required),
			secret: Boolean(record.secret),
			sourceLabel: resourceSourceLabel(String(record.source ?? '')),
			statusLabel: resourceStatusLabel(String(record.status ?? '')),
			evidenceCount: Array.isArray(record.evidence_refs) ? record.evidence_refs.length : 0
		};
	});
}

function normalizeResourceTitle(value: string, fallback: string): string {
	const text = trimOneLine(value, 48);
	if (text) {
		return text;
	}
	return trimOneLine(fallback.replace(/[._-]+/g, ' '), 48);
}

function normalizeResourceSentence(value: string, limit: number): string {
	return trimOneLine(value, limit);
}

function resourceStrategyLabels(value: unknown): string[] {
	if (!Array.isArray(value)) {
		return [];
	}
	const labels: Record<string, string> = {
		ask_user: '需你提供',
		discoverable: '可查找',
		secret: '密文',
		optional: '可选',
		runtime_config: '运行配置',
		defaultable: '可默认'
	};
	const result: string[] = [];
	for (const item of value) {
		const label = labels[String(item)];
		if (label && !result.includes(label)) {
			result.push(label);
		}
	}
	return result.slice(0, 3);
}

function resourceSourceLabel(source: string): string {
	if (source === 'tool' || source === 'mcp' || source === 'knowledge' || source === 'skill') {
		return '工具发现';
	}
	if (source === 'user') {
		return '用户提供';
	}
	if (source === 'default') {
		return '默认值';
	}
	if (source === 'system') {
		return '系统';
	}
	return '来源待确认';
}

function resourceStatusLabel(status: string): string {
	if (status === 'confirmed') {
		return '已确认';
	}
	if (status === 'discovered') {
		return '待确认发现结果';
	}
	if (status === 'declined') {
		return '暂不提供';
	}
	if (status === 'optional_empty') {
		return '可留空';
	}
	if (status === 'missing') {
		return '缺失';
	}
	return '';
}

type SchedulerSeedReviewItem = {
	seedId: string;
	title: string;
	humanSchedule: string;
	taskContent: string;
	maxConsecutiveFailures: number;
	feedbackEnabled: boolean;
	scheduleType: string;
	scheduleExpr: string;
	timezone: string;
};

function schedulerSeedReviewItems(event: FactoryEvent): SchedulerSeedReviewItem[] {
	const seeds = event.payload?.seeds;
	if (!Array.isArray(seeds)) {
		return [];
	}
	return seeds.map((item, index) => {
		const record = item && typeof item === 'object' ? item as Record<string, unknown> : {};
		const advanced = record.advanced && typeof record.advanced === 'object' ? record.advanced as Record<string, unknown> : {};
		const failure = record.failure_policy && typeof record.failure_policy === 'object'
			? record.failure_policy as Record<string, unknown>
			: {};
		return {
			seedId: String(record.seed_id ?? `seed_${index + 1}`),
			title: String(record.title ?? `定时任务 ${index + 1}`),
			humanSchedule: String(record.human_schedule ?? ''),
			taskContent: String(record.task_content ?? ''),
			maxConsecutiveFailures: Number(failure.max_consecutive_failures ?? 3),
			feedbackEnabled: Boolean(record.feedback_enabled ?? true),
			scheduleType: String(advanced.schedule_type ?? ''),
			scheduleExpr: String(advanced.schedule_expr ?? ''),
			timezone: String(advanced.timezone ?? '')
		};
	});
}

function schedulerSeedMissingQuestions(event: FactoryEvent): string[] {
	const questions = event.payload?.missing_questions;
	if (!Array.isArray(questions)) {
		return [];
	}
	return questions.map(item => String(item).trim()).filter(Boolean).slice(0, 4);
}

function trimOneLine(value: string, limit: number): string {
	const normalized = value.replace(/\s+/g, ' ').trim();
	return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}

function shortId(value: string): string {
	return value.length > 16 ? `${value.slice(0, 14)}...` : value;
}

function optionsForQuestion(question: Record<string, unknown>): ChoiceOption[] {
	const customOptionId = String(question.custom_option_id ?? 'custom');
	return (((question.options as Array<Record<string, unknown>>) ?? []) as Array<Record<string, unknown>>).map(item => {
		const id = String(item.id ?? item.label ?? '');
		return {
			id,
			label: String(item.label ?? id),
			description: item.description ? String(item.description) : undefined,
			custom: id === customOptionId
		};
	});
}

function answered(answers: Record<string, RequirementClarificationAnswer>, question: Record<string, unknown>, index: number): boolean {
	return Boolean(answers[String(question.id ?? `question_${index + 1}`)]);
}

function commitAnswer({
	questionId,
	option,
	customText,
	answers,
	setAnswers,
	questions,
	questionIndex,
	setQuestionIndex,
	onSubmit
}: {
	questionId: string;
	option: ChoiceOption;
	customText: string;
	answers: Record<string, RequirementClarificationAnswer>;
	setAnswers: React.Dispatch<React.SetStateAction<Record<string, RequirementClarificationAnswer>>>;
	questions: Array<Record<string, unknown>>;
	questionIndex: number;
	setQuestionIndex: React.Dispatch<React.SetStateAction<number>>;
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const nextAnswers = {
		...answers,
		[questionId]: {
			question_id: questionId,
			selected_option_id: option.id,
			selected_label: option.label,
			...(customText ? {custom_text: customText} : {})
		}
	};
	setAnswers(nextAnswers);
	const nextIndex = questionIndex + 1;
	if (nextIndex < questions.length) {
		setQuestionIndex(nextIndex);
		return;
	}
	const orderedAnswers = questions.map((question, index) => nextAnswers[String(question.id ?? `question_${index + 1}`)]).filter(Boolean);
	onSubmit(buildRequirementClarificationResumePayload(orderedAnswers));
}
