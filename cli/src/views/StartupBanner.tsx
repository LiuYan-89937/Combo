import React from 'react';
import {Box, Text} from 'ink';

const BANNER = String.raw`
  _____     _      ____     _____
 |" ___|U  /"\  u / __"| u |_ " _|
U| |_  u \/ _ \/ <\___ \/    | |
\|  _|/  / ___ \  u___) |   /| |\
 |_|    /_/   \_\ |____/>> u |_|U
 )(\\,-  \\    >>  )(  (__)_// \\_
(__)(_/ (__)  (__)(__)    (__) (__)
            _       ____  U _____ u _   _     _____
        U  /"\  uU /"___|u\| ___"|/| \ |"|   |_ " _|
         \/ _ \/ \| |  _ / |  _|" <|  \| |>    | |
         / ___ \  | |_| |  | |___ U| |\  |u   /| |\
        /_/   \_\  \____|  |_____| |_| \_|   u |_|U
         \\    >>  _)(|_   <<   >> ||   \\,-._// \\_
        (__)  (__)(__)__) (__) (__)(_")  (_/(__) (__)
                  _____     _        ____   _____   U  ___ u   ____     __   __
                 |" ___|U  /"\  u U /"___| |_ " _|   \/"_ \/U |  _"\ u  \ \ / /
                U| |_  u \/ _ \/  \| | u     | |     | | | | \| |_) |/   \ V /
                \|  _|/  / ___ \   | |/__   /| |\.-,_| |_| |  |  _ <    U_|"|_u
                 |_|    /_/   \_\   \____| u |_|U \_)-\___/   |_| \_\     |_|
                 )(\\,-  \\    >>  _// \\  _// \\_     \\     //   \\_.-,//|(_
                (__)(_/ (__)  (__)(__)(__)(__) (__)   (__)   (__)  (__)\_) (__)
`.trimEnd();

const COLORS = ['cyan', 'blue', 'magenta', 'red', 'yellow', 'green'] as const;

export function StartupBanner() {
	const lines = BANNER.split('\n');
	return (
		<Box flexDirection="column" marginBottom={1}>
			{lines.map((line, index) => (
				<Text key={`${index}:${line}`} color={COLORS[index % COLORS.length]} bold>
					{line}
				</Text>
			))}
		</Box>
	);
}
