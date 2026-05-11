#!/usr/bin/env node
import React from 'react';
import {render} from 'ink';
import {Command} from 'commander';
import {App} from './app.js';

const program = new Command();

program
	.name('factory')
	.description('FastAgentFactory TypeScript CLI frontend')
	.action(() => {
		render(<App />);
	});

program.parse(process.argv);

