#!/bin/bash
# Copies extension/master/ files into extension/chrome/ and extension/firefox/.
# Run after editing anything in master/, before reloading either browser's extension.
set -euo pipefail
cd "$(dirname "$0")"

shared=(background.js content.js content-lego.js content-lego-spy.js content_main.js
        index.html index.js icon16.png icon48.png icon128.png)

for f in "${shared[@]}"; do
  cp "master/$f" "chrome/$f"
  cp "master/$f" "firefox/$f"
done
cp master/manifest.chrome.json  chrome/manifest.json
cp master/manifest.firefox.json firefox/manifest.json

echo "synced $(( ${#shared[@]} * 2 + 2 )) files into chrome/ and firefox/"
