/* Testable Google Identity Services helpers for the standalone web app. */
(function exposeGoogleAuth(root, factory) {
  const helpers = factory();
  if (root) root.SchaudioGoogleAuth = helpers;
  if (typeof module === "object" && module.exports) module.exports = helpers;
})(typeof window === "object" ? window : null, function buildGoogleAuthHelpers() {
  "use strict";

  function isStandalone(_matchMediaFn, navigatorLike) {
    // navigator.standalone is Apple-specific. Keep the workaround scoped to
    // iOS/iPadOS home-screen apps; Android and desktop PWAs retain the normal
    // browser flow instead of inheriting an unrelated Safari workaround.
    return navigatorLike?.standalone === true;
  }

  async function createNonce(cryptoApi, base64Encode) {
    if (!cryptoApi?.getRandomValues || !cryptoApi?.subtle?.digest) {
      throw new Error("Secure nonce generation is unavailable");
    }
    const bytes = new Uint8Array(32);
    cryptoApi.getRandomValues(bytes);
    const raw = base64Encode(String.fromCharCode(...bytes));
    const encoded = new TextEncoder().encode(raw);
    const hashBuffer = await cryptoApi.subtle.digest("SHA-256", encoded);
    const hashed = Array.from(new Uint8Array(hashBuffer), (byte) =>
      byte.toString(16).padStart(2, "0")
    ).join("");
    return { raw, hashed };
  }

  function identityConfig(clientId, hashedNonce, callback) {
    return {
      client_id: clientId,
      callback,
      nonce: hashedNonce,
      itp_support: true,
      auto_select: false,
      cancel_on_tap_outside: true,
    };
  }

  function signInWithCredential(authClient, response, rawNonce) {
    if (!response?.credential) {
      return Promise.resolve({
        data: null,
        error: { code: "missing_google_credential", message: "Google did not return a credential" },
      });
    }
    return authClient.signInWithIdToken({
      provider: "google",
      token: response.credential,
      nonce: rawNonce,
    });
  }

  function runSignInFlow(isStandaloneContext, standaloneFlow, browserFlow) {
    return isStandaloneContext ? standaloneFlow() : browserFlow();
  }

  return { isStandalone, createNonce, identityConfig, signInWithCredential, runSignInFlow };
});
