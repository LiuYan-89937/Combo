import React, {useEffect, useMemo, useState} from 'react';
import {Box, Text, useInput} from 'ink';
import {
	buildPlanReviewContinuePayload,
	buildPlanReviewRevisionPayload,
	buildRequirementClarificationResumePayload,
	buildToolApprovalPayload,
	buildToolApprovalRevisionPayload,
	type RequirementClarificationAnswer
} from '../interrupts.js';
import {type FactoryEvent} from '../protocol.js';

type ChoiceOption = {
	id: string;
	label: string;
	description?: string;
	custom?: boolean;
};

export function InterruptChoicePanel({
	event,
	onSubmit
}: {
	event: FactoryEvent | null;
	onSubmit: (payload: Record<string, unknown>) => void;
}) {
	const interruptType = String(event?.payload?.type ?? event?.event_type ?? '');
	if (!event || !['requirement_clarification', 'plan_review', 'tool_approval'].includes(interruptType)) {
		return null;
	}
	if (interruptType === 'requirement_clarification') {
		return <RequirementClarificationTabs event={event} onSubmit={onSubmit} />;
	}
	if (interruptType === 'plan_review') {
		return <PlanReviewTabs event={event} onSubmit={onSubmit} />;
	}
	return <ToolApprovalTabs event={event} onSubmit={onSubmit} />;
}

export function isChoiceInterrupt(event: FactoryEvent | null): boolean {
	const interruptType = String(event?.payload?.type ?? event?.event_type ?? '');
	return ['requirement_clarification', 'plan_review', 'tool_approval'].includes(interruptType);
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
		if (key.leftArrow || key.upArrow) {
			setSelected(current => Math.max(0, current - 1));
			return;
		}
		if (key.rightArrow || key.downArrow) {
			setSelected(current => Math.min(2, current + 1));
			return;
		}
		if (key.return) {
			if (selected === 2) {
				setRevisionMode(true);
				return;
			}
			onSubmit(buildToolApprovalPayload(selected === 0));
		}
	});
	return (
		<Box borderStyle="round" borderColor="yellow" paddingX={1} flexDirection="column">
			<Text bold color="yellow">Tool Approval Required</Text>
			{requests.map((item, index) => (
				<Text key={String(item.tool_call_id ?? index)}>
					{index + 1}. {String(item.tool_name ?? '-')} {String(item.summary ?? '')}
				</Text>
			))}
			<Box marginTop={1}>
				<Tab label="批准" active={selected === 0} />
				<Tab label="拒绝" active={selected === 1} />
				<Tab label="重试导向" active={selected === 2} />
			</Box>
			{revisionMode && (
				<Text color="cyan">
					审查意见：{revisionText}
					<Text inverse>{' '}</Text>
				</Text>
			)}
			<Text color="gray">Left/Right 选择，Enter 确认；重试导向会进入输入模式，提交后不执行工具而是让模型重写 tool call。</Text>
		</Box>
	);
}

function Tab({label, active}: {label: string; active: boolean}) {
	return (
		<Text color={active ? 'black' : 'yellow'} backgroundColor={active ? 'yellow' : undefined}>
			{` ${label} `}
		</Text>
	);
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
