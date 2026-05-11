import React from 'react';
import {Box, Text} from 'ink';

export function Section({
	title,
	color,
	children
}: {
	title: string;
	color: string;
	children: React.ReactNode;
}) {
	return (
		<Box borderStyle="round" borderColor={color} paddingX={1} flexDirection="column" marginTop={1}>
			<Box>
				<Text color={color} bold>{title}</Text>
			</Box>
			{children}
		</Box>
	);
}

export function Pill({label, value, color = 'cyan'}: {label: string; value: string; color?: string}) {
	return (
		<Box marginRight={2}>
			<Text color="gray">{label} </Text>
			<Text color={color} bold>{value}</Text>
		</Box>
	);
}

export function Muted({children}: {children: React.ReactNode}) {
	return <Text color="gray">{children}</Text>;
}

export function Value({children, color = 'white'}: {children: React.ReactNode; color?: string}) {
	return <Text color={color}>{children}</Text>;
}

