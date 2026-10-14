#!/bin/bash
# Installs Python 3.12 (via uv), AWS CLI v2, Terraform and GitHub CLI into your
# home folder. No sudo / admin rights needed. Safe to re-run (skips what exists).
# Sources: astral.sh (uv), awscli.amazonaws.com, releases.hashicorp.com, github.com/cli.
set -euo pipefail

BIN="$HOME/.local/bin"
mkdir -p "$BIN"
export PATH="$BIN:$PATH"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ARCH="$(uname -m)"   # arm64 or x86_64
[ "$ARCH" = "x86_64" ] && TF_ARCH=amd64 GH_ARCH=amd64 || TF_ARCH=arm64 GH_ARCH=arm64

# 1) PATH line in your shell config (once)
for rc in "$HOME/.zshrc" "$HOME/.zprofile"; do
  touch "$rc"
  grep -q 'llm-gateway tools' "$rc" || echo 'export PATH="$HOME/.local/bin:$PATH"  # llm-gateway tools' >> "$rc"
done

# 2) uv + Python 3.12
if ! command -v uv >/dev/null; then
  echo "==> Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh
fi
echo "==> Installing Python 3.12 (uv-managed)"
uv python install 3.12

# 3) AWS CLI v2 (official pkg, "current user only" install into ~/aws-cli)
if ! command -v aws >/dev/null; then
  echo "==> Installing AWS CLI v2 (~60 MB)"
  curl -fsSL https://awscli.amazonaws.com/AWSCLIV2.pkg -o "$TMP/AWSCLIV2.pkg"
  cat > "$TMP/choices.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <array>
    <dict>
      <key>choiceAttribute</key><string>customLocation</string>
      <key>attributeSetting</key><string>$HOME</string>
      <key>choiceIdentifier</key><string>default</string>
    </dict>
  </array>
</plist>
EOF
  installer -pkg "$TMP/AWSCLIV2.pkg" -target CurrentUserHomeDirectory -applyChoiceChangesXML "$TMP/choices.xml"
  ln -sf "$HOME/aws-cli/aws" "$BIN/aws"
  ln -sf "$HOME/aws-cli/aws_completer" "$BIN/aws_completer"
fi

# 4) Terraform (latest, SHA256 verified)
if ! command -v terraform >/dev/null; then
  TF_V="$(curl -fsSL https://checkpoint-api.hashicorp.com/v1/check/terraform | python3 -c 'import sys,json;print(json.load(sys.stdin)["current_version"])')"
  echo "==> Installing Terraform $TF_V"
  ZIP="terraform_${TF_V}_darwin_${TF_ARCH}.zip"
  curl -fsSL "https://releases.hashicorp.com/terraform/${TF_V}/${ZIP}" -o "$TMP/$ZIP"
  curl -fsSL "https://releases.hashicorp.com/terraform/${TF_V}/terraform_${TF_V}_SHA256SUMS" -o "$TMP/SUMS"
  (cd "$TMP" && grep " ${ZIP}\$" SUMS | shasum -a 256 -c -)
  unzip -oq "$TMP/$ZIP" terraform -d "$BIN"
fi

# 5) GitHub CLI (optional, latest)
if ! command -v gh >/dev/null; then
  GH_TAG="$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest | python3 -c 'import sys,json;print(json.load(sys.stdin)["tag_name"])')"
  GH_V="${GH_TAG#v}"
  echo "==> Installing GitHub CLI $GH_V"
  curl -fsSL "https://github.com/cli/cli/releases/download/${GH_TAG}/gh_${GH_V}_macOS_${GH_ARCH}.zip" -o "$TMP/gh.zip"
  unzip -oq "$TMP/gh.zip" -d "$TMP"
  cp "$TMP/gh_${GH_V}_macOS_${GH_ARCH}/bin/gh" "$BIN/gh"
fi

echo
echo "==> Versions"
uv --version
uv run --no-project --python 3.12 python --version
aws --version
terraform version | head -1
gh --version | head -1
echo
echo "Done. Open a NEW terminal tab (or run: source ~/.zshrc) so PATH picks up ~/.local/bin."
