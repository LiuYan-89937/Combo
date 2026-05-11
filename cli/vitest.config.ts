import {defineConfig} from 'vitest/config';

export default defineConfig({
	test: {
		environment: 'node',
		reporters: ['default'],
		watch: false,
		api: false
	}
});

