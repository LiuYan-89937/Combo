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
	if (!event || !['requirement_clarification', 'plan_review', 'tool_approval', 'resource_collection', 'resource_confirmation'].includes(interruptType)) {
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
	return <ToolApprovalTabs event={event} onSubmit={onSubmit} />;
}

export function isChoiceInterrupt(event: FactoryEvent | null): boolean {
	const interruptType = String(event?.payload?.type ?? event?.event_type ?? '');
	return ['requirement_clarification', 'plan_review', 'tool_approval', 'resource_collection', 'resource_confirmation'].includes(interruptType);
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
			{questions.map((question, index) => (
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

type ResourceConfirmationItem = {
	key: string;
	title: string;
	valueSummary: string;
	required: boolean;
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
			title: String(record.title ?? key),
			valueSummary: String(record.value_summary ?? record.valueSummary ?? '未提供'),
			required: Boolean(record.required)
		};
	});
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
