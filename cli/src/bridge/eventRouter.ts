import {type FactoryEvent} from '../protocol.js';
import {type FactoryUiState} from '../state/factoryStore.js';
import {reduceFactoryEvent} from '../state/factoryStore.js';

export function routeFactoryEvent(state: FactoryUiState, event: FactoryEvent): FactoryUiState {
	return reduceFactoryEvent(state, event);
}

