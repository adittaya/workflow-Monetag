#!/usr/bin/env bash
set -e

INSTALL_DIR="${MONETAG_HOME:-$HOME/.monetag247}"
REPO="adittaya/workflow-monetag"
BIN_DIR="${HOME}/.local/bin"
BIN="${BIN_DIR}/monetag"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║         M O N E T A G   I N S T A L L E R              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# --- Python ---
echo "[1/4] Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python $PYVER"

# --- Pip deps ---
echo "[2/4] Installing Python dependencies..."
pip3 install --break-system-packages -q selenium webdriver-manager requests urllib3 cryptography pynacl 2>/dev/null \
  || pip3 install -q selenium webdriver-manager requests urllib3 cryptography pynacl

# --- Chromium (informational) ---
echo "[3/4] Checking Chromium..."
if command -v chromium &>/dev/null; then
    echo "  Chromium: $(chromium --version 2>/dev/null || echo 'installed')"
elif command -v google-chrome &>/dev/null; then
    echo "  Chrome: $(google-chrome --version 2>/dev/null || echo 'installed')"
elif command -v chromium-browser &>/dev/null; then
    echo "  Chromium: $(chromium-browser --version 2>/dev/null || echo 'installed')"
else
    echo "  WARNING: No browser found. Automation needs Chromium or Chrome."
    echo "  Install Chrome (no snap): wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && sudo dpkg -i /tmp/chrome.deb"
fi

# --- TUI launcher ---
echo "[4/4] Installing monetag launcher..."

# Remove old Node.js install if present
if [ -L "$HOME/.local/bin/monetag" ]; then
    rm -f "$HOME/.local/bin/monetag"
fi

# Download tui.py
curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/tui.py" -o /tmp/monetag_tui.py

# Also download core automation files
for f in monetag_automation.py config.py profile_generator.py proxy_rotator.py monetag.yml requirements.txt; do
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/$f" -o "/tmp/monetag_$f" 2>/dev/null || true
done

# Create install dir
mkdir -p "$INSTALL_DIR"

# Move automation files into place
mv /tmp/monetag_monetag_automation.py "$INSTALL_DIR/monetag_automation.py" 2>/dev/null
mv /tmp/monetag_config.py "$INSTALL_DIR/config.py" 2>/dev/null
mv /tmp/monetag_profile_generator.py "$INSTALL_DIR/profile_generator.py" 2>/dev/null
mv /tmp/monetag_proxy_rotator.py "$INSTALL_DIR/proxy_rotator.py" 2>/dev/null
mv /tmp/monetag_requirements.txt "$INSTALL_DIR/requirements.txt" 2>/dev/null

# Create wrapper script
mkdir -p "$BIN_DIR"
cat > "$BIN" << 'WRAPPER'
#!/usr/bin/env bash
exec python3 "${MONETAG_HOME:-$HOME/.monetag247}/tui.py" "$@"
WRAPPER
chmod +x "$BIN"

# Install TUI
mv /tmp/monetag_tui.py "$INSTALL_DIR/tui.py"

# Init data files
for f in accounts.json deployments.json settings.json; do
    [ -f "$INSTALL_DIR/$f" ] || echo "{}" > "$INSTALL_DIR/$f"
done

# Clone template repo (needed for deploy)
if [ ! -d "$INSTALL_DIR/template" ]; then
    echo "  Cloning template repo..."
    git clone --depth 1 "https://github.com/${REPO}.git" "$INSTALL_DIR/template" 2>/dev/null || true
fi

echo ""
echo "✓ Installed to $INSTALL_DIR"
echo ""

# Ensure ~/.local/bin is in PATH
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    export PATH="$HOME/.local/bin:$PATH"
    echo "  Added ~/.local/bin to PATH (run 'source ~/.bashrc' or open new terminal)"
fi

echo "✓ Run with: monetag"
echo ""
echo "Next steps:"
echo "  1. Run 'monetag' to open the TUI"
echo "  2. Go to Accounts → Add your GitHub token"
echo "  3. Go to Settings → Set Supabase credentials + SmartLink URL"
echo "  4. Go to Deploy → Create a new instance"
