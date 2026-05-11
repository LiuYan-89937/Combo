import React from 'react';
import {Box, Text} from 'ink';
import {type FactoryMode} from '../protocol.js';
import {visibleCommands} from '../commands.js';
import {Section} from './ui.js';

export function HelpPanel({mode, hasInterrupt}: {mode: FactoryMode | null; hasInterrupt: boolean}) {
	const commands = visibleCommands(mode, hasInterrupt).slice(0, 10);
	return (
		<Section title="Command Hints" color="gray">
			{commands.map(item => (
				<Text key={item.usage}>
					<Text color="cyan">{item.usage.padEnd(24)}</Text>
					{item.description}
				</Text>
			))}
		</Section>
	);
}
