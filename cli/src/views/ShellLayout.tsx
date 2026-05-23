import React from 'react';
import {Box} from 'ink';
import {StartupBanner} from './StartupBanner.js';

export function ShellLayout({children}: {children: React.ReactNode}) {
	return (
		<Box flexDirection="column">
			<StartupBanner />
			{children}
		</Box>
	);
}
