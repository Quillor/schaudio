import SwiftUI

@main
struct SchaudioApp: App {
    @State private var library = Library()
    @State private var store: Store
    @State private var sync: SyncService
    @State private var player = Player()
    @State private var downloads = Downloads()

    init() {
        let store = Store()
        _store = State(initialValue: store)
        _sync = State(initialValue: SyncService(store: store))
    }

    var body: some Scene {
        WindowGroup {
            LibraryView()
                .environment(library)
                .environment(store)
                .environment(player)
                .environment(sync)
                .environment(downloads)
                .task {
                    await library.load()
                    player.rate = store.rate
                }
        }
    }
}
