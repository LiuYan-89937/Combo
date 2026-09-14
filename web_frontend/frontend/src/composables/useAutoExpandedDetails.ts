import { computed, inject, provide, shallowReactive, type InjectionKey, type Ref } from 'vue'

const detailsStateKey: InjectionKey<Map<string, boolean>> = Symbol('detailsState')

/** Preserve explicit choices when a folded turn unmounts its expensive bodies. */
export function provideDetailsState(): void {
  provide(detailsStateKey, inject(detailsStateKey, null) ?? shallowReactive(new Map<string, boolean>()))
}

/** Vue owns `open`; only summary activation changes the user preference.
 * Native `toggle` also fires asynchronously after programmatic updates.
 */
export function useAutoExpandedDetails(autoExpand: Ref<boolean>, key: () => string) {
  const choices = inject(detailsStateKey, null) ?? shallowReactive(new Map<string, boolean>())
  const expanded = computed(() => choices.get(key()) ?? autoExpand.value)

  function toggle(): void {
    choices.set(key(), !expanded.value)
  }

  return { expanded, toggle }
}
