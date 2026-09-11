import { computed, ref, watch, type Ref } from 'vue'

/**
 * Drives a `<details>` element that opens itself while it is active.
 *
 * A long transcript should not keep every finished reasoning/tool block open,
 * but the user must still be able to open one manually. The explicit toggle
 * therefore wins until the activity state changes again, and the content is
 * only mounted while open so a freshly expanded panel never renders blank.
 */
export function useAutoExpandedDetails(autoExpand: Ref<boolean>) {
  const userOverride = ref<boolean | null>(null)
  const expanded = computed(() => userOverride.value ?? autoExpand.value)

  watch(autoExpand, () => {
    userOverride.value = null
  })

  function handleToggle(event: Event): void {
    // `toggle` bubbles. Without this guard a nested `<details>` (an argument or
    // result section) also drives its ancestors' state, so the two drift apart:
    // the DOM ends up open while the JS state still says collapsed, and the
    // panel renders blank until the user toggles it once more.
    if (event.target !== event.currentTarget) return
    const element = event.currentTarget as HTMLDetailsElement | null
    if (!element || element.open === expanded.value) return
    userOverride.value = element.open
  }

  return { expanded, handleToggle }
}
