import React, {useState} from 'react';
import {Box, Text, useInput} from 'ink';
import {type ShellCommandSpec} from '../commands.js';
import {Muted} from './ui.js';

export function CommandInput({
	prompt,
	onSubmit,
	getSuggestions,
	disabled = false,
	disabledText = 'runtime is busy'
}: {
	prompt: string;
	onSubmit: (value: string) => void;
	getSuggestions: (value: string) => ShellCommandSpec[];
	disabled?: boolean;
	disabledText?: string;
}) {
	const [value, setValue] = useState('');
	const [history, setHistory] = useState<string[]>([]);
	const [historyIndex, setHistoryIndex] = useState<number | null>(null);
	const suggestions = getSuggestions(value);
	useInput((input, key) => {
		if (disabled) {
			if (key.ctrl && input === 'c') {
				onSubmit('/quit');
			}
			return;
		}
		if (key.return) {
			const submitted = value.trim();
			setValue('');
			setHistoryIndex(null);
			if (submitted) {
				setHistory(current => [...current.slice(-40), submitted]);
			}
			onSubmit(submitted);
			return;
		}
		if (key.tab && suggestions[0]) {
			setValue(suggestions[0].usage.split(/\s+/)[0] ?? suggestions[0].usage);
			return;
		}
		if (key.upArrow) {
			setHistoryIndex(current => {
				const next = current === null ? history.length - 1 : Math.max(0, current - 1);
				setValue(history[next] ?? value);
				return next;
			});
			return;
		}
		if (key.downArrow) {
			setHistoryIndex(current => {
				if (current === null) {
					return null;
				}
				const next = current + 1;
				if (next >= history.length) {
					setValue('');
					return null;
				}
				setValue(history[next] ?? '');
				return next;
			});
			return;
		}
		if (key.backspace || key.delete) {
			setValue(current => current.slice(0, -1));
			return;
		}
		if (key.ctrl && input === 'c') {
			onSubmit('/quit');
			return;
		}
		if (input && !key.ctrl && !key.meta) {
			setValue(current => current + input);
		}
	});
	return (
		<Box flexDirection="column" marginTop={1}>
			<Box borderStyle="round" borderColor="cyan" paddingX={1}>
				<Text color="cyan" bold>{prompt}</Text>
				<Text color="gray"> $ </Text>
				{disabled ? (
					<Text color="gray">{disabledText}</Text>
				) : (
					<>
						<Text>{value || ''}</Text>
						<Text inverse>{' '}</Text>
						{!value && <Text color="gray"> type a command or message</Text>}
					</>
				)}
			</Box>
			{!disabled && suggestions.length > 0 && (
				<Box flexDirection="column" paddingX={1}>
					<Muted>Tab complete / Up Down history</Muted>
					<Box flexDirection="column">
						{suggestions.slice(0, 5).map((item, index) => (
							<Box key={item.usage}>
								<Text color={index === 0 ? 'cyan' : 'gray'}>{index === 0 ? '> ' : '  '}</Text>
								<Text color={index === 0 ? 'cyan' : 'white'}>{item.usage.padEnd(24)}</Text>
								<Text color="gray">{item.description}</Text>
							</Box>
						))}
					</Box>
				</Box>
			)}
		</Box>
	);
}
