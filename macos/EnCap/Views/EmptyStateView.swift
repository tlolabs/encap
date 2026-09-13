import SwiftUI

struct EmptyStateView<Actions: View>: View {
    let title: String
    let systemImage: String
    let description: String
    @ViewBuilder let actions: () -> Actions

    init(
        _ title: String,
        systemImage: String,
        description: String,
        @ViewBuilder actions: @escaping () -> Actions
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.actions = actions
    }

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 42, weight: .light))
                .foregroundStyle(.secondary)
            Text(title).font(.title2).fontWeight(.semibold)
            Text(description)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
            actions()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }
}

extension EmptyStateView where Actions == EmptyView {
    init(_ title: String, systemImage: String, description: String) {
        self.init(title, systemImage: systemImage, description: description) { EmptyView() }
    }
}
