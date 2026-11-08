import Foundation

/// Turn a locale hint into the base language code used by speech model tokens.
/// An explicit empty/unknown code remains explicit and is rejected by the provider.
enum LanguageInput {
    static func baseCode(_ value: String) -> String {
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased().replacingOccurrences(of: "_", with: "-")
        return normalized.split(separator: "-", omittingEmptySubsequences: false)
            .first.map(String.init) ?? ""
    }
}
