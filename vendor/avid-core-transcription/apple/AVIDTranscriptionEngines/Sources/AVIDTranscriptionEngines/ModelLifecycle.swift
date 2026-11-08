/// Release model resources before returning a result or propagating an error.
/// Inherit the provider's actor so non-Sendable SDK models stay on their owner.
func withModelCleanup<Result: Sendable>(
    isolation: isolated (any Actor)? = #isolation,
    operation: () async throws -> Result,
    cleanup: () async -> Void
) async rethrows -> Result {
    do {
        let result = try await operation()
        await cleanup()
        return result
    } catch {
        await cleanup()
        throw error
    }
}
