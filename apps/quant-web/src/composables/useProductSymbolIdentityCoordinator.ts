import { readonly, ref, type Ref } from 'vue'


interface ProductSymbolIdentityCoordinatorDependencies {
  invalidateFacts: () => void
  refreshMarket: () => Promise<boolean>
  refreshFacts: () => readonly Promise<void>[]
  rejectFacts: () => void
}

export function useProductSymbolIdentityCoordinator(
  dependencies: ProductSymbolIdentityCoordinatorDependencies,
) {
  const synchronizing = ref(false)
  let generation = 0

  async function synchronize(): Promise<void> {
    const requestGeneration = ++generation
    synchronizing.value = true
    dependencies.invalidateFacts()

    let marketAccepted = false
    try {
      marketAccepted = await dependencies.refreshMarket()
    } catch {
      marketAccepted = false
    }
    if (requestGeneration !== generation) return

    if (!marketAccepted) {
      dependencies.rejectFacts()
      synchronizing.value = false
      return
    }

    const factRefreshes = dependencies.refreshFacts()
    synchronizing.value = false
    await Promise.allSettled(factRefreshes)
  }

  function dispose(): void {
    generation += 1
    synchronizing.value = false
  }

  return {
    synchronizing: readonly(synchronizing) as Readonly<Ref<boolean>>,
    synchronize,
    dispose,
  }
}
