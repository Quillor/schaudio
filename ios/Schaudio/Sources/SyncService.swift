import Foundation
import Observation

/// Google sign-in plus cross-device sync against the same Supabase row the web
/// app writes.
///
/// Supabase's REST and auth endpoints are plain HTTPS, and this app touches one
/// table and one token exchange, so it talks to them directly rather than
/// pulling in the SDK — no dependency to keep current, and the whole contract
/// is visible in this file.
@Observable
@MainActor
final class SyncService {
    struct Account: Sendable, Equatable {
        var id: String
        var email: String
        var name: String
        var avatar: URL?
    }

    enum Status: Equatable {
        case signedOut
        case signingIn
        case signedIn
        case syncing
        case error(String)
    }

    private(set) var account: Account?
    private(set) var status: Status = .signedOut

    private let projectURL = URL(string: "https://dntyenrksitgfichghca.supabase.co")!
    private let anonKey = "sb_publishable_OlbdMOaYHDs5mrbDFFAmwA_PsVAq4UL"

    private var accessToken: String?
    private var refreshToken: String?
    private var pushTask: Task<Void, Never>?

    private unowned let store: Store

    init(store: Store) {
        self.store = store
        restoreSession()
        store.onLocalChange = { [weak self] in self?.schedulePush() }
    }

    // MARK: - Sign in

    /// Exchanges a Google ID token for a Supabase session.
    func signIn(idToken: String, nonce: String?) async {
        status = .signingIn
        var body: [String: Any] = ["provider": "google", "id_token": idToken]
        if let nonce { body["nonce"] = nonce }

        var request = URLRequest(url: projectURL.appending(path: "auth/v1/token").appending(queryItems: [
            URLQueryItem(name: "grant_type", value: "id_token")
        ]))
        request.httpMethod = "POST"
        request.setValue(anonKey, forHTTPHeaderField: "apikey")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                let message = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error_description"] as? String
                status = .error(message ?? "Google sign-in was rejected.")
                return
            }
            try applySession(data)
            status = .signedIn
            await pull()
        } catch {
            status = .error(error.localizedDescription)
        }
    }

    func signOut() {
        accessToken = nil
        refreshToken = nil
        account = nil
        status = .signedOut
        Keychain.delete("schaudio.refreshToken")
    }

    // MARK: - Sync

    /// Pull the remote row and take it if it is newer than what's on device.
    func pull() async {
        guard let accessToken, let account else { return }
        status = .syncing
        var request = URLRequest(url: projectURL.appending(path: "rest/v1/user_state")
            .appending(queryItems: [
                URLQueryItem(name: "select", value: "data"),
                URLQueryItem(name: "user_id", value: "eq.\(account.id)"),
            ]))
        request.setValue(anonKey, forHTTPHeaderField: "apikey")
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        do {
            let (data, _) = try await URLSession.shared.data(for: request)
            struct Row: Decodable { let data: SyncPayload }
            let rows = try JSONDecoder().decode([Row].self, from: data)
            if let remote = rows.first?.data, remote.updatedAt > store.updatedAt {
                store.apply(remote)
            } else {
                await push()      // device is ahead (or remote is empty)
            }
            status = .signedIn
        } catch {
            // A decode failure usually means an empty row; publishing ours fixes it.
            await push()
            status = .signedIn
        }
    }

    /// Debounced so a burst of edits (scrubbing, typing a note) is one request.
    func schedulePush() {
        guard accessToken != nil else { return }
        pushTask?.cancel()
        pushTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            await self?.push()
        }
    }

    func push() async {
        guard let accessToken, let account else { return }
        let payload = store.makePayload()
        struct Row: Encodable {
            let user_id: String
            let data: SyncPayload
            let updated_at: String
        }
        let row = Row(user_id: account.id, data: payload,
                      updated_at: ISO8601DateFormatter().string(from: .now))

        var request = URLRequest(url: projectURL.appending(path: "rest/v1/user_state"))
        request.httpMethod = "POST"
        request.setValue(anonKey, forHTTPHeaderField: "apikey")
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // Upsert: one row per user, replace it wholesale.
        request.setValue("resolution=merge-duplicates", forHTTPHeaderField: "Prefer")
        request.httpBody = try? JSONEncoder().encode(row)

        _ = try? await URLSession.shared.data(for: request)
    }

    // MARK: - Session plumbing

    private func applySession(_ data: Data) throws {
        struct Session: Decodable {
            let access_token: String
            let refresh_token: String
            let user: User
            struct User: Decodable {
                let id: String
                let email: String?
                let user_metadata: Meta?
                struct Meta: Decodable {
                    let full_name: String?
                    let avatar_url: String?
                }
            }
        }
        let session = try JSONDecoder().decode(Session.self, from: data)
        accessToken = session.access_token
        refreshToken = session.refresh_token
        Keychain.set(session.refresh_token, for: "schaudio.refreshToken")
        account = Account(
            id: session.user.id,
            email: session.user.email ?? "",
            name: session.user.user_metadata?.full_name ?? session.user.email ?? "Account",
            avatar: session.user.user_metadata?.avatar_url.flatMap(URL.init(string:))
        )
    }

    private func restoreSession() {
        guard let token = Keychain.get("schaudio.refreshToken") else { return }
        refreshToken = token
        Task { await refresh(using: token) }
    }

    private func refresh(using token: String) async {
        var request = URLRequest(url: projectURL.appending(path: "auth/v1/token").appending(queryItems: [
            URLQueryItem(name: "grant_type", value: "refresh_token")
        ]))
        request.httpMethod = "POST"
        request.setValue(anonKey, forHTTPHeaderField: "apikey")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["refresh_token": token])

        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
              (try? applySession(data)) != nil else {
            Keychain.delete("schaudio.refreshToken")
            return
        }
        status = .signedIn
        await pull()
    }
}

/// Refresh tokens are long-lived credentials, so they live in the keychain
/// rather than UserDefaults.
enum Keychain {
    static func set(_ value: String, for key: String) {
        delete(key)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    static func get(_ key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(_ key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
