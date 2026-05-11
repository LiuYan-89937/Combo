import React, {useState} from 'react';
import {Box, Text, useInput} from 'ink';

export function CommandInput({prompt, onSubmit}: {prompt: string; onSubmit: (value: string) => void}) {
	const [value, setValue] = useState('');
	useInput((input, key) => {
		if (key.return) {
			const submitted = value.trim();
			setValue('');
			onSubmit(submitted);
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
		<Box>
			<Text color="cyan">{prompt}: </Text>
			<Text>{value}</Text>
		</Box>
	);
}

