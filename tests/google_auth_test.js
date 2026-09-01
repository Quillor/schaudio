"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { webcrypto } = require("node:crypto");
const googleAuth = require("../app/google-auth.js");

test("scopes the workaround to installed Apple web apps", () => {
  assert.equal(googleAuth.isStandalone(() => ({ matches: true }), {}), false);
  assert.equal(googleAuth.isStandalone(() => ({ matches: false }), { standalone: true }), true);
  assert.equal(googleAuth.isStandalone(() => ({ matches: false }), {}), false);
});

test("generates a random nonce and the Google-facing SHA-256 hash", async () => {
  const first = await googleAuth.createNonce(webcrypto, btoa);
  const second = await googleAuth.createNonce(webcrypto, btoa);

  assert.match(first.raw, /^[A-Za-z0-9+/]+={0,2}$/);
  assert.match(first.hashed, /^[0-9a-f]{64}$/);
  assert.notEqual(first.raw, second.raw);
  const expectedHash = Array.from(new Uint8Array(
    await webcrypto.subtle.digest("SHA-256", new TextEncoder().encode(first.raw))
  ), (byte) => byte.toString(16).padStart(2, "0")).join("");
  assert.equal(first.hashed, expectedHash);
  await assert.rejects(
    googleAuth.createNonce({}, btoa),
    /Secure nonce generation/
  );
});

test("configures upgraded ITP One Tap with a JavaScript credential callback", () => {
  const callback = () => {};
  assert.deepEqual(googleAuth.identityConfig("client-id", "hashed-nonce", callback), {
    client_id: "client-id",
    callback,
    nonce: "hashed-nonce",
    itp_support: true,
    auto_select: false,
    cancel_on_tap_outside: true,
  });
});

test("uses the canonical HTTPS app URL for OAuth redirects", () => {
  assert.equal(
    googleAuth.resolveRedirectUrl(
      "https://schaudio.timrosenberg.app/",
      "https://schaudio-tim-rosenberg.vercel.app",
      "/app/"
    ),
    "https://schaudio.timrosenberg.app/"
  );
  assert.equal(
    googleAuth.resolveRedirectUrl(
      "not-a-url",
      "https://schaudio-tim-rosenberg.vercel.app",
      "/app/"
    ),
    "https://schaudio-tim-rosenberg.vercel.app/app/"
  );
});

test("marks the installed-app callback and rejects forged session messages", () => {
  assert.equal(
    googleAuth.resolvePopupRedirectUrl(
      "https://schaudio.timrosenberg.app/",
      "https://fallback.example",
      "/app/"
    ),
    "https://schaudio.timrosenberg.app/?authPopup=1"
  );

  const popup = {};
  const message = {
    origin: "https://schaudio.timrosenberg.app",
    source: popup,
    data: { type: "schaudio:auth-session", accessToken: "access", refreshToken: "refresh" },
  };
  assert.equal(googleAuth.isTrustedSessionMessage(message, message.origin, popup), true);
  assert.equal(googleAuth.isTrustedSessionMessage({ ...message, origin: "https://evil.example" }, message.origin, popup), false);
  assert.equal(googleAuth.isTrustedSessionMessage({ ...message, source: {} }, message.origin, popup), false);
  assert.equal(googleAuth.isTrustedSessionMessage({ ...message, data: { ...message.data, refreshToken: "" } }, message.origin, popup), false);
});

test("exchanges the Google ID token and raw nonce with Supabase", async () => {
  let payload = null;
  const client = {
    signInWithIdToken: async (value) => {
      payload = value;
      return { data: { session: { user: { id: "user-1" } } }, error: null };
    },
  };

  const result = await googleAuth.signInWithCredential(
    client,
    { credential: "signed-google-jwt" },
    "raw-nonce"
  );

  assert.deepEqual(payload, {
    provider: "google",
    token: "signed-google-jwt",
    nonce: "raw-nonce",
  });
  assert.equal(result.data.session.user.id, "user-1");
});

test("fails closed when GIS returns no credential", async () => {
  let called = false;
  const client = { signInWithIdToken: async () => { called = true; } };

  const result = await googleAuth.signInWithCredential(client, {}, "raw-nonce");

  assert.equal(called, false);
  assert.equal(result.error.code, "missing_google_credential");
});

test("standalone routing never invokes the browser redirect flow", () => {
  let standaloneCalls = 0;
  let redirectCalls = 0;

  googleAuth.runSignInFlow(
    true,
    () => { standaloneCalls += 1; },
    () => { redirectCalls += 1; }
  );

  assert.equal(standaloneCalls, 1);
  assert.equal(redirectCalls, 0);
});

test("regular browsers retain the existing redirect flow", () => {
  let standaloneCalls = 0;
  let redirectCalls = 0;

  googleAuth.runSignInFlow(
    false,
    () => { standaloneCalls += 1; },
    () => { redirectCalls += 1; }
  );

  assert.equal(standaloneCalls, 0);
  assert.equal(redirectCalls, 1);
});
