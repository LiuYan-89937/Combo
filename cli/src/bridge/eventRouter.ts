import {type FactoryUiAction, type FactoryUiState, reduceFactoryUiAction} from '../state/factoryStore.js';

export function routeFactoryEvent(state: FactoryUiState, action: FactoryUiAction): FactoryUiState {
	return reduceFactoryUiAction(state, action);
}
