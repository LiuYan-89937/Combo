import React, {createContext, useContext, useSyncExternalStore} from 'react';
import {type RuntimeState, type RuntimeStore} from './runtimeStore.js';

const RuntimeStoreContext = createContext<RuntimeStore | null>(null);

export function RuntimeStoreProvider({store, children}: {store: RuntimeStore; children: React.ReactNode}) {
	return <RuntimeStoreContext.Provider value={store}>{children}</RuntimeStoreContext.Provider>;
}

export function useRuntimeStore(): RuntimeStore {
	const store = useContext(RuntimeStoreContext);
	if (!store) {
		throw new Error('RuntimeStoreProvider is missing');
	}
	return store;
}

export function useStoreSelector<T>(selector: (state: RuntimeState) => T): T {
	const store = useRuntimeStore();
	return useSyncExternalStore(
		store.subscribe,
		() => selector(store.getSnapshot()),
		() => selector(store.getSnapshot())
	);
}
