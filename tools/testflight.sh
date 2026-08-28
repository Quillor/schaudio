#!/bin/bash
# Archive Schaudio and ship it to TestFlight.
#
# Needs an App Store Connect API key (App Store Connect -> Users and Access ->
# Integrations -> App Store Connect API -> "+", role: App Manager). Download the
# .p8 once — Apple will not show it again — and put it where altool looks:
#
#   mkdir -p ~/.appstoreconnect/private_keys
#   mv ~/Downloads/AuthKey_XXXXXXXXXX.p8 ~/.appstoreconnect/private_keys/
#
# Then:
#   ASC_KEY_ID=XXXXXXXXXX ASC_ISSUER_ID=<uuid> DEVELOPMENT_TEAM=<10-char team> \
#     tools/testflight.sh
#
# The build number is the commit count, so every upload is unique and traceable
# back to a commit — App Store Connect rejects a build number it has seen before.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${ASC_KEY_ID:?set ASC_KEY_ID (App Store Connect API key id)}"
: "${ASC_ISSUER_ID:?set ASC_ISSUER_ID (App Store Connect issuer id)}"
: "${DEVELOPMENT_TEAM:?set DEVELOPMENT_TEAM (10-character Apple team id)}"

KEY_FILE="$HOME/.appstoreconnect/private_keys/AuthKey_${ASC_KEY_ID}.p8"
[ -f "$KEY_FILE" ] || { echo "No private key at $KEY_FILE"; exit 1; }

BUILD_NUMBER="$(git rev-list --count HEAD)"
ARCHIVE="ios/build/Schaudio.xcarchive"
EXPORT_DIR="ios/build/export"

echo "==> Generating project"
(cd ios && xcodegen generate >/dev/null)

echo "==> Archiving (build $BUILD_NUMBER)"
xcodebuild -project ios/Schaudio.xcodeproj -scheme Schaudio \
  -sdk iphoneos -configuration Release \
  -archivePath "$ARCHIVE" \
  DEVELOPMENT_TEAM="$DEVELOPMENT_TEAM" \
  CURRENT_PROJECT_VERSION="$BUILD_NUMBER" \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$KEY_FILE" \
  -authenticationKeyID "$ASC_KEY_ID" \
  -authenticationKeyIssuerID "$ASC_ISSUER_ID" \
  archive

echo "==> Exporting"
rm -rf "$EXPORT_DIR"
xcodebuild -exportArchive -archivePath "$ARCHIVE" \
  -exportOptionsPlist ios/ExportOptions.plist \
  -exportPath "$EXPORT_DIR" \
  DEVELOPMENT_TEAM="$DEVELOPMENT_TEAM" \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$KEY_FILE" \
  -authenticationKeyID "$ASC_KEY_ID" \
  -authenticationKeyIssuerID "$ASC_ISSUER_ID"

IPA="$(find "$EXPORT_DIR" -name '*.ipa' | head -1)"
[ -n "$IPA" ] || { echo "No .ipa produced"; exit 1; }

echo "==> Validating $IPA"
xcrun altool --validate-app -f "$IPA" -t ios \
  --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"

echo "==> Uploading to App Store Connect"
xcrun altool --upload-app -f "$IPA" -t ios \
  --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"

echo
echo "Uploaded build $BUILD_NUMBER. Apple processes it for 5-15 minutes, then it"
echo "appears under TestFlight in App Store Connect. Internal testers can install"
echo "immediately; external groups need a beta review first."
