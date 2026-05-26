import React, {useEffect, useMemo, useState} from 'react';
import {Box, Text, useInput} from 'ink';
import {
	buildPlanReviewContinuePayload,
	buildPlanReviewRevisionPayload,
	buildRequirementClarificationResumePayload,
	buildResourceFormPayload,
	buildResourceFormSkipPayload,
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
	if (!event || !['requirement_clarification', 'plan_review', 'tool_approval', 'resource_form'].includes(interruptType)) {
		return null;
	}
	if (interruptType === 'requirement_clarification') {
		return <RequirementClarificationTabs event={event} onSubmit={onSubmit} />;
	}
	if (interruptType === 'plan_review') {
		return <PlanReviewTabs event={event} onSubmit={onSubmit} />;
	}
	if (interruptType === 'resource_form') {
		return <ResourceFormPanel event={event} onSubmit={onSubmit} />;
	}
	return <ToolApprovalTabs event={event} onSubmit={onSubmit} />;
}

export function isChoiceInterrupt(event: FactoryEvent | null): boolean {
	const interruptType = String(event?.payload?.type ?? event?.event_type ?? '');
	return ['requirement_clarification', 'plan_review', 'tool_approval', 'resource_form'].includes(interruptType);
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

type ResourceFormField = {
	key: string;
	label: string;
	type: string;
	required: boolean;
	description?: string;
	default?: unknown;
	secret?: boolean;
};

function ResourceFormPanel({
	event,
	onSubmit
}: {
	event: FactoryEvent;
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const fields = useMemo(() => resourceFormFields(event), [event]);
	const [selected, setSelected] = useState(0);
	const [values, setValues] = useState<Record<string, string | boolean>>({});
	const [notice, setNotice] = useState('');
	const selectedField = fields[selected] ?? fields[0];

	useEffect(() => {
		setSelected(0);
		setNotice('');
		setValues(defaultResourceFormValues(fields));
	}, [event.event_id, fields]);

	useInput((input, key) => {
		if (!fields.length) {
			return;
		}
		if (key.upArrow) {
			setSelected(current => Math.max(0, current - 1));
			setNotice('');
			return;
		}
		if (key.downArrow) {
			setSelected(current => Math.min(fields.length - 1, current + 1));
			setNotice('');
			return;
		}
		if (key.escape) {
			onSubmit(buildResourceFormSkipPayload());
			return;
		}
		if (key.return) {
			const missing = fields.filter(field => field.required && !hasFormValue(values[field.key]));
			if (missing.length) {
				setNotice(`缺少必填项：${missing.map(field => field.key).join(', ')}`);
				return;
			}
			onSubmit(buildResourceFormPayload(coerceResourceFormValues(fields, values)));
			return;
		}
		if (!selectedField) {
			return;
		}
			if (selectedField.type === 'boolean' && (input === ' ' || key.leftArrow || key.rightArrow)) {
				setValues(current => ({...current, [selectedField.key]: !current[selectedField.key]}));
			setNotice('');
			return;
		}
		if (key.backspace || key.delete) {
			setValues(current => ({...current, [selectedField.key]: String(current[selectedField.key] ?? '').slice(0, -1)}));
			setNotice('');
			return;
		}
		if (input && !key.ctrl && !key.meta && selectedField.type !== 'boolean') {
			setValues(current => ({...current, [selectedField.key]: `${String(current[selectedField.key] ?? '')}${input}`}));
			setNotice('');
		}
	});

	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold color="yellow">{String(event.payload?.title ?? 'Resource Form')}</Text>
			<Text color="gray">{String(event.payload?.message ?? '提交外部资源后继续。')}</Text>
			{fields.map((field, index) => (
				<Box key={field.key} flexDirection="column" marginTop={index ? 1 : 0}>
					<Text color={index === selected ? 'yellow' : field.required && !hasFormValue(values[field.key]) ? 'red' : 'white'}>
						{index === selected ? '> ' : '  '}
						{field.key}
						{field.required ? ' *' : ''}
						<Text color="gray">  {field.type}</Text>
					</Text>
					<Text>
						<Text color="gray">value: </Text>
						{formatResourceFieldValue(field, values[field.key])}
						{index === selected && field.type !== 'boolean' ? <Text inverse>{' '}</Text> : null}
					</Text>
					{field.description ? <Text color="gray">{trimOneLine(field.description, 180)}</Text> : null}
				</Box>
			))}
			{notice ? <Text color="red">{notice}</Text> : null}
			<Text color="gray">Up/Down 选择字段，直接输入值，Backspace 删除；boolean 用 Space 切换；Enter 提交；Esc 暂不提供。</Text>
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

function resourceFormFields(event: FactoryEvent): ResourceFormField[] {
	const form = event.payload?.form;
	const fields = form && typeof form === 'object' ? (form as Record<string, unknown>).fields : [];
	if (!Array.isArray(fields)) {
		return [];
	}
	return fields.map((item, index) => {
		const field = item && typeof item === 'object' ? item as Record<string, unknown> : {};
		const key = String(field.key ?? `field_${index + 1}`);
		return {
			key,
			label: String(field.label ?? key),
			type: String(field.type ?? 'string'),
			required: Boolean(field.required),
			description: field.description ? String(field.description) : undefined,
			default: field.default,
			secret: Boolean(field.secret)
		};
	});
}

function defaultResourceFormValues(fields: ResourceFormField[]): Record<string, string | boolean> {
	const values: Record<string, string | boolean> = {};
	for (const field of fields) {
		if (field.default === undefined || field.default === null) {
			if (field.type === 'boolean') {
				values[field.key] = false;
			}
			continue;
		}
		if (field.type === 'boolean') {
			values[field.key] = Boolean(field.default);
			continue;
		}
		if (typeof field.default === 'string' || typeof field.default === 'number' || typeof field.default === 'boolean') {
			values[field.key] = String(field.default);
			continue;
		}
		values[field.key] = JSON.stringify(field.default);
	}
	return values;
}

function hasFormValue(value: unknown): boolean {
	if (value === undefined || value === null) {
		return false;
	}
	if (typeof value === 'string') {
		return value.trim().length > 0;
	}
	return true;
}

function coerceResourceFormValues(fields: ResourceFormField[], values: Record<string, string | boolean>): Record<string, unknown> {
	const result: Record<string, unknown> = {};
	for (const field of fields) {
		const value = values[field.key];
		if (!hasFormValue(value)) {
			continue;
		}
		result[field.key] = coerceResourceFieldValue(field, value);
	}
	return result;
}

function coerceResourceFieldValue(field: ResourceFormField, value: string | boolean): unknown {
	if (field.type === 'boolean') {
		return Boolean(value);
	}
	const text = String(value).trim();
	if (field.type === 'string_array' || field.type === 'url_array') {
		if (text.startsWith('[') && text.endsWith(']')) {
			try {
				const parsed = JSON.parse(text);
				if (Array.isArray(parsed)) {
					return parsed;
				}
			} catch {
				return text.split(',').map(item => item.trim()).filter(Boolean);
			}
		}
		return text.split(',').map(item => item.trim()).filter(Boolean);
	}
	if (field.type === 'number') {
		const numberValue = Number(text);
		return Number.isFinite(numberValue) ? numberValue : text;
	}
	if (field.type === 'json') {
		try {
			return JSON.parse(text);
		} catch {
			return text;
		}
	}
	return text;
}

function formatResourceFieldValue(field: ResourceFormField, value: string | boolean | undefined): string {
	if (field.type === 'boolean') {
		return value ? 'true' : 'false';
	}
	if (field.secret && hasFormValue(value)) {
		return '••••••';
	}
	return trimOneLine(String(value ?? ''), 180);
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
