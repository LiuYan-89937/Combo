import React, {createContext, useContext, useRef, useSyncExternalStore} from 'react';
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

export function useStoreSelector<T>(
	selector: (state: RuntimeState) => T,
	isEqual: (left: T, right: T) => boolean = Object.is
): T {
	const store = useRuntimeStore();
	const snapshotRef = useRef<{value: T} | null>(null);
	const getSelectedSnapshot = () => {
		const selected = selector(store.getSnapshot());
		if (snapshotRef.current && isEqual(snapshotRef.current.value, selected)) {
			return snapshotRef.current.value;
		}
		snapshotRef.current = {value: selected};
		return selected;
	};
	return useSyncExternalStore(
		store.subscribe,
		getSelectedSnapshot,
		getSelectedSnapshot
	);
}
