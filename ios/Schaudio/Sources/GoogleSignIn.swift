import AuthenticationServices
import CryptoKit
import Foundation
import UIKit

/// Google sign-in without a third-party SDK.
///
/// `ASWebAuthenticationSession` is the system's OAuth surface: it runs in
/// Safari's process, so Google accepts it (embedded web views are blocked),
/// existing Google sessions are reused, and the app never sees the password.
/// We ask Google directly — not via a Supabase redirect — so the consent screen
/// names *Schaudio*, and we exchange the resulting ID token with Supabase.
@MainActor
enum GoogleSignIn {
    /// iOS OAuth client for bundle id com.quillor.schaudio. Public by design.
    static let clientID = "929848887321-dnn5rn5i6log3e1cakbfc6301ff1n26k.apps.googleusercontent.com"

    /// Google requires iOS clients to redirect to the reversed client id.
    static var redirectScheme: String {
        clientID.split(separator: ".").reversed().joined(separator: ".")
    }

    struct Result: Sendable {
        let idToken: String
        let nonce: String
    }

    enum Failure: LocalizedError {
        case cancelled
        case noIDToken
        case http(String)

        var errorDescription: String? {
            switch self {
            case .cancelled: "Sign-in was cancelled."
            case .noIDToken: "Google didn't return an identity token."
            case .http(let m): m
            }
        }
    }

    static func run(from anchor: ASPresentationAnchor) async throws -> Result {
        // PKCE: the code verifier never leaves the device, so the authorization
        // code is useless to anyone who intercepts the redirect.
        let verifier = randomString(64)
        let challenge = base64URL(SHA256.hash(data: Data(verifier.utf8)))
        let rawNonce = randomString(32)
        let hashedNonce = base64URL(SHA256.hash(data: Data(rawNonce.utf8)))
        let redirectURI = "\(redirectScheme):/oauth2redirect"

        var components = URLComponents(string: "https://accounts.google.com/o/oauth2/v2/auth")!
        components.queryItems = [
            .init(name: "client_id", value: clientID),
            .init(name: "redirect_uri", value: redirectURI),
            .init(name: "response_type", value: "code"),
            .init(name: "scope", value: "openid email profile"),
            .init(name: "code_challenge", value: challenge),
            .init(name: "code_challenge_method", value: "S256"),
            .init(name: "nonce", value: hashedNonce),
        ]

        let callback = try await authenticate(url: components.url!, scheme: redirectScheme, anchor: anchor)
        guard let code = URLComponents(url: callback, resolvingAgainstBaseURL: false)?
            .queryItems?.first(where: { $0.name == "code" })?.value else {
            throw Failure.cancelled
        }

        let idToken = try await exchange(code: code, verifier: verifier, redirectURI: redirectURI)
        return Result(idToken: idToken, nonce: rawNonce)
    }

    // MARK: - Steps

    private static func authenticate(url: URL, scheme: String, anchor: ASPresentationAnchor) async throws -> URL {
        let provider = AnchorProvider(anchor: anchor)
        return try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: scheme) { callback, error in
                if let callback {
                    continuation.resume(returning: callback)
                } else {
                    continuation.resume(throwing: error ?? Failure.cancelled)
                }
            }
            session.presentationContextProvider = provider
            session.prefersEphemeralWebBrowserSession = false
            // Retained by the continuation's closure until the session finishes.
            objc_setAssociatedObject(session, &AnchorProvider.key, provider, .OBJC_ASSOCIATION_RETAIN)
            session.start()
        }
    }

    private static func exchange(code: String, verifier: String, redirectURI: String) async throws -> String {
        var request = URLRequest(url: URL(string: "https://oauth2.googleapis.com/token")!)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        // No client secret: iOS clients are public, which is exactly why PKCE
        // is required above.
        var body = URLComponents()
        body.queryItems = [
            .init(name: "client_id", value: clientID),
            .init(name: "code", value: code),
            .init(name: "code_verifier", value: verifier),
            .init(name: "grant_type", value: "authorization_code"),
            .init(name: "redirect_uri", value: redirectURI),
        ]
        request.httpBody = body.percentEncodedQuery.map { Data($0.utf8) }

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let text = String(data: data, encoding: .utf8) ?? "Token exchange failed."
            throw Failure.http(text)
        }
        struct Token: Decodable { let id_token: String? }
        guard let idToken = try JSONDecoder().decode(Token.self, from: data).id_token else {
            throw Failure.noIDToken
        }
        return idToken
    }

    // MARK: - Helpers

    private static func randomString(_ length: Int) -> String {
        let chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        return String((0..<length).map { _ in chars.randomElement()! })
    }

    private static func base64URL(_ digest: SHA256.Digest) -> String {
        Data(digest).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

private final class AnchorProvider: NSObject, ASWebAuthenticationPresentationContextProviding {
    nonisolated(unsafe) static var key: UInt8 = 0
    let anchor: ASPresentationAnchor
    init(anchor: ASPresentationAnchor) { self.anchor = anchor }
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor { anchor }
}

/// The key window, for presenting the auth sheet.
@MainActor
enum PresentationAnchor {
    static var current: ASPresentationAnchor {
        let scene = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }
        return scene?.keyWindow ?? ASPresentationAnchor()
    }
}
