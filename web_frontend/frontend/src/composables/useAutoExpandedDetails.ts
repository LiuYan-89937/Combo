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
    const element = (event.currentTarget || event.target) as HTMLDetailsElement | null
    if (!element || element.open === expanded.value) return
    userOverride.value = element.open
  }

  return { expanded, handleToggle }
}
