#!/usr/bin/env sh
# Download a prebuilt `scele` from GitHub Releases. No Python needed.
#
#   curl -fsSL https://raw.githubusercontent.com/Andrew4Coding/scele-cli/main/install-bin.sh | sh
#
# Env overrides:
#   SCELE_VERSION=v0.2.0            install a specific tag (default: latest)
#   SCELE_BIN_DIR=/usr/local/bin    where the `scele` launcher goes (default: ~/.local/bin)
#   SCELE_APP_DIR=~/.local/lib/scele-app   where the bundle is unpacked
set -eu

REPO="Andrew4Coding/scele-cli"
VERSION="${SCELE_VERSION:-latest}"
BIN_DIR="${SCELE_BIN_DIR:-$HOME/.local/bin}"
APP_DIR="${SCELE_APP_DIR:-$HOME/.local/lib/scele-app}"

# --- UI & Styling Setup ---
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
    BOLD="\033[1m"
    DIM="\033[2m"
    RESET="\033[0m"
    RED="\033[31m"
    GREEN="\033[32m"
    YELLOW="\033[33m"
    BLUE="\033[34m"
    CYAN="\033[36m"
    GOLD="\033[1;33m"
    CLEAR_LINE="\033[2K\r"
    HIDE_CURSOR="\033[?25l"
    SHOW_CURSOR="\033[?25h"
    TICK="✔"
    CROSS="✖"
    INFO="ℹ"
else
    BOLD=""
    DIM=""
    RESET=""
    RED=""
    GREEN=""
    YELLOW=""
    BLUE=""
    CYAN=""
    GOLD=""
    CLEAR_LINE=""
    HIDE_CURSOR=""
    SHOW_CURSOR=""
    TICK="[OK]"
    CROSS="[FAIL]"
    INFO="[!]"
fi

# Cleanup and cursor restoration on exit/interrupt
TMP_DIR=""
CURRENT_PID=""
cleanup() {
    exit_code=$?
    [ -n "$CURRENT_PID" ] && kill -9 "$CURRENT_PID" 2>/dev/null || true
    [ -t 1 ] && printf "%b" "$SHOW_CURSOR"
    [ -n "$TMP_DIR" ] && rm -rf "$TMP_DIR"
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

die() {
    printf "\n  ${RED}%s${RESET} ${BOLD}Error:${RESET} %s\n\n" "$CROSS" "$*" >&2
    exit 1
}

print_banner() {
    printf "\n"
    printf "${GOLD}     _____ _____ _____ __    _____ ${RESET}\n"
    printf "${GOLD}    |   __|     |   __|  |  |   __|${RESET}\n"
    printf "${GOLD}    |__   |   --|   __|  |__|   __|${RESET}\n"
    printf "${GOLD}    |_____|_____|_____|_____|_____|${RESET}  ${CYAN}CLI${RESET}\n"
    printf "    ${DIM}Moodle client for CS Universitas Indonesia (scele.cs.ui.ac.id)${RESET}\n"
    printf "\n"
}

run_step() {
    step_num="$1"
    total_steps="$2"
    step_desc="$3"
    shift 3

    step_log="$TMP_DIR/step-$step_num.log"

    if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
        "$@" >"$step_log" 2>&1 &
        CURRENT_PID=$!
        i=0
        printf "%b" "$HIDE_CURSOR"
        while kill -0 "$CURRENT_PID" 2>/dev/null; do
            case $i in
                0) frame="⠋" ;; 1) frame="⠙" ;; 2) frame="⠹" ;; 3) frame="⠸" ;; 4) frame="⠼" ;;
                5) frame="⠴" ;; 6) frame="⠦" ;; 7) frame="⠧" ;; 8) frame="⠇" ;; 9) frame="⠏" ;;
            esac
            i=$(( (i + 1) % 10 ))
            printf "\r  ${CYAN}%s${RESET} ${BOLD}[%s/%s]${RESET} %s..." "$frame" "$step_num" "$total_steps" "$step_desc"
            sleep 0.08
        done
        wait "$CURRENT_PID"
        status=$?
        CURRENT_PID=""
        printf "%b" "$SHOW_CURSOR"

        if [ "$status" -eq 0 ]; then
            printf "\r${CLEAR_LINE}  ${GREEN}%s${RESET} ${BOLD}[%s/%s]${RESET} %s\n" "$TICK" "$step_num" "$total_steps" "$step_desc"
            return 0
        else
            printf "\r${CLEAR_LINE}  ${RED}%s${RESET} ${BOLD}[%s/%s]${RESET} %s ${RED}(failed)${RESET}\n" "$CROSS" "$step_num" "$total_steps" "$step_desc"
            if [ -s "$step_log" ]; then
                printf "\n${RED}%s${RESET}\n" "$(cat "$step_log")" >&2
            fi
            return "$status"
        fi
    else
        printf "  [%s/%s] %s...\n" "$step_num" "$total_steps" "$step_desc"
        "$@" >"$step_log" 2>&1
        status=$?
        if [ "$status" -eq 0 ]; then
            printf "  [%s/%s] %s (done)\n" "$step_num" "$total_steps" "$step_desc"
            return 0
        else
            printf "  [%s/%s] %s (failed)\n" "$step_num" "$total_steps" "$step_desc"
            if [ -s "$step_log" ]; then
                cat "$step_log" >&2
            fi
            return "$status"
        fi
    fi
}

show_help() {
    print_banner
    printf "Usage:\n"
    printf "  curl -fsSL https://raw.githubusercontent.com/%s/main/install-bin.sh | sh\n" "$REPO"
    printf "  ./install-bin.sh [options]\n\n"
    printf "Options:\n"
    printf "  -h, --help                      Show this help message and exit\n\n"
    printf "Environment Overrides:\n"
    printf "  SCELE_VERSION=v0.2.0            Install specific tag (default: latest)\n"
    printf "  SCELE_BIN_DIR=~/.local/bin      Launcher destination\n"
    printf "  SCELE_APP_DIR=~/.local/lib/...  Unpack directory for the binary bundle\n\n"
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) show_help ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

TOTAL_STEPS=4

print_banner

# Step 1: Detect system architecture
os=$(uname -s)
arch=$(uname -m)
case "$os" in
    Linux)  OS=linux; OS_NAME="Linux" ;;
    Darwin) OS=macos; OS_NAME="macOS" ;;
    *) die "unsupported OS '$os'. Use: pipx install git+https://github.com/$REPO.git" ;;
esac
case "$arch" in
    x86_64|amd64)
        [ "$OS" = macos ] && die "no prebuilt binary for Intel macs. Use: pipx install git+https://github.com/$REPO.git"
        ARCH=x86_64 ;;
    arm64|aarch64) [ "$OS" = macos ] && ARCH=arm64 || ARCH=aarch64 ;;
    *) die "unsupported architecture '$arch'" ;;
esac

ASSET="scele-${OS}-${ARCH}.tar.gz"
printf "  ${GREEN}%s${RESET} ${BOLD}[1/%s]${RESET} Detected environment: ${CYAN}%s (%s)${RESET}\n" "$TICK" "$TOTAL_STEPS" "$OS_NAME" "$ARCH"

if [ "$VERSION" = latest ]; then
    BASE="https://github.com/$REPO/releases/latest/download"
else
    BASE="https://github.com/$REPO/releases/download/$VERSION"
fi

fetch() {
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
    else echo "need curl or wget" >&2; return 1; fi
}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
    else echo ""; fi
}

TMP_DIR=$(mktemp -d)

# Step 2: Download release asset
download_asset() {
    fetch "$BASE/$ASSET" "$TMP_DIR/$ASSET"
}
run_step 2 "$TOTAL_STEPS" "Downloading prebuilt bundle (${CYAN}${ASSET}${RESET})" download_asset \
    || die "download failed — no prebuilt bundle for $OS-$ARCH at $BASE.\n         Try installing via pipx: pipx install git+https://github.com/$REPO.git"

# Step 3: Checksum verification
verify_checksum() {
    if fetch "$BASE/checksums.txt" "$TMP_DIR/checksums.txt" 2>/dev/null && [ -s "$TMP_DIR/checksums.txt" ]; then
        want=$(grep " ${ASSET}\$" "$TMP_DIR/checksums.txt" | awk '{print $1}' || true)
        got=$(sha256 "$TMP_DIR/$ASSET")
        if [ -n "$want" ] && [ -n "$got" ] && [ "$want" != "$got" ]; then
            echo "checksum mismatch for $ASSET (expected: $want, got: $got)" >&2
            return 1
        fi
    fi
    return 0
}
run_step 3 "$TOTAL_STEPS" "Verifying SHA-256 integrity checksum" verify_checksum \
    || die "checksum verification failed for $ASSET"

# Step 4: Extract and link
extract_and_link() {
    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR"
    tar -xzf "$TMP_DIR/$ASSET" -C "$APP_DIR" --strip-components=1 || return 1
    [ -x "$APP_DIR/scele" ] || { echo "bundle missing launcher at $APP_DIR/scele" >&2; return 1; }
    [ "$OS" = macos ] && xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null || true
    mkdir -p "$BIN_DIR"
    ln -sf "$APP_DIR/scele" "$BIN_DIR/scele"
}
run_step 4 "$TOTAL_STEPS" "Unpacking bundle & linking to $BIN_DIR/scele" extract_and_link \
    || die "failed to extract or link the application bundle"

INSTALLED_VER=$("$BIN_DIR/scele" --version 2>/dev/null || echo "$VERSION")

case ":$PATH:" in
    *":$BIN_DIR:"*) ON_PATH=1 ;;
    *) ON_PATH=0 ;;
esac

# Summary & Next Steps Card
printf "\n"
printf "  ${GREEN}%s${RESET} ${BOLD}SCELE CLI installed successfully!${RESET}\n\n" "$TICK"
printf "  ${CYAN}│${RESET}  ${BOLD}Launcher:${RESET}  %s\n" "$BIN_DIR/scele"
printf "  ${CYAN}│${RESET}  ${BOLD}Bundle:${RESET}    %s\n" "$APP_DIR/scele"
printf "  ${CYAN}│${RESET}  ${BOLD}Version:${RESET}   %s\n\n" "$INSTALLED_VER"
printf "  ${BOLD}Quick Start:${RESET}\n"
printf "    ${CYAN}scele login${RESET}     Authenticate with your SCELE account\n"
printf "    ${CYAN}scele courses${RESET}   List your enrolled courses\n"
printf "    ${CYAN}scele --help${RESET}    Explore available commands and options\n\n"

if [ "$ON_PATH" -eq 0 ]; then
    SHELL_NAME=$(basename "${SHELL:-bash}")
    RC_FILE="~/.${SHELL_NAME}rc"
    case "$SHELL_NAME" in
        zsh)  RC_FILE="~/.zshrc" ;;
        bash) [ "$OS" = macos ] && RC_FILE="~/.bash_profile" || RC_FILE="~/.bashrc" ;;
        fish) RC_FILE="~/.config/fish/config.fish" ;;
    esac

    printf "  ${YELLOW}%s Notice:${RESET} %s is not in your PATH.\n" "$INFO" "$BIN_DIR"
    printf "  To run ${CYAN}scele${RESET} directly from any terminal, add it to your configuration:\n\n"
    if [ "$SHELL_NAME" = "fish" ]; then
        printf "    ${CYAN}set -U fish_user_paths %s \$fish_user_paths${RESET}\n\n" "$BIN_DIR"
    else
        printf "    ${CYAN}echo 'export PATH=\"%s:\$PATH\"' >> %s${RESET}\n\n" "$BIN_DIR" "$RC_FILE"
    fi
    printf "  Then reload your shell or open a new terminal tab.\n\n"
fi
