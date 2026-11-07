#!/usr/bin/env bash
# Install the Deterministic Model Test and an `llmtest` command, then start a test.
#
#   curl -fsSL https://raw.githubusercontent.com/Prism77Proton/LocalLLMTest/main/install.sh | bash
#   ./install.sh            # from inside a copy of the repository
#
# Options: --no-run (install only), --skip-tests (skip the grader self-test).
# Environment: LLMTEST_HOME (default ~/LocalLLMTest), LLMTEST_BIN (default ~/.local/bin),
#              LLMTEST_REPO (default https://github.com/Prism77Proton/LocalLLMTest).
# Needs bash, Python 3.12+ and git or curl/wget. No Python packages, no sudo.
set -euo pipefail

REPO_URL="${LLMTEST_REPO:-https://github.com/Prism77Proton/LocalLLMTest}"
DEST="${LLMTEST_HOME:-$HOME/LocalLLMTest}"
BIN_DIR="${LLMTEST_BIN:-$HOME/.local/bin}"
RUN=1
SELF_TEST=1
for arg in "$@"; do
  case "$arg" in
    --no-run) RUN=0 ;;
    --skip-tests) SELF_TEST=0 ;;
    -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null || true; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Python 3.12 or newer (the test uses only the standard library).
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[ -n "$PYTHON" ] || fail "Python 3.12 or newer is required.
  Ubuntu/Debian/WSL: sudo apt install python3.12    macOS: brew install python@3.12"
say "Using $("$PYTHON" --version) at $PYTHON"

# 2. The test files: this copy if run from one, otherwise a download into $DEST.
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/run_models.py" ] && [ -f "$SCRIPT_DIR/grade.py" ]; then
  DEST="$SCRIPT_DIR"
  say "Using this copy: $DEST"
elif [ -d "$DEST/.git" ]; then
  say "Updating $DEST"
  git -C "$DEST" pull --ff-only --quiet || fail "Could not update $DEST; resolve it with git, or move it aside."
elif [ -e "$DEST" ]; then
  fail "$DEST already exists and is not a git copy of the test. Move it aside or set LLMTEST_HOME."
elif command -v git >/dev/null 2>&1; then
  say "Downloading into $DEST"
  git clone --quiet --depth 1 "$REPO_URL" "$DEST"
else
  say "Downloading into $DEST (no git found, using a tarball)"
  archive="$REPO_URL/archive/refs/heads/main.tar.gz"
  mkdir -p "$DEST"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$archive" | tar -xz -C "$DEST" --strip-components=1
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$archive" | tar -xz -C "$DEST" --strip-components=1
  else
    fail "Install git, curl or wget to download the test."
  fi
fi

# 3. Check the grading engine works on this machine (about five seconds).
if [ "$SELF_TEST" = 1 ]; then
  say "Checking the grader"
  (cd "$DEST" && PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -m unittest discover -s tests -q 2>&1 | tail -1) ||
    fail "The grader self-test failed in $DEST."
fi

# 4. The `llmtest` command: model picker, one-question-at-a-time runner, report and leaderboard.
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/llmtest" <<EOF
#!/usr/bin/env bash
# Deterministic Model Test launcher (written by install.sh).
#   llmtest                       pick a server and model, run all 50 questions
#   llmtest --url URL --list      list a server's models without running anything
#   llmtest --resume              continue the last run of the model you pick
#   llmtest submit                post the latest finished run to the public leaderboard
#   llmtest board                 open the local leaderboard
#   llmtest --help                every option
cd "$DEST"
if [ "\${1:-}" = submit ]; then
  shift
  exec "$PYTHON" "$DEST/run_models.py" --submit-only "\$@"
fi
if [ "\${1:-}" = board ]; then
  board="$DEST/results/leaderboard.html"
  [ -f "\$board" ] || { echo "No runs yet. Run llmtest first."; exit 1; }
  echo "\$board"
  for opener in wslview xdg-open open; do
    command -v "\$opener" >/dev/null 2>&1 && { "\$opener" "\$board" >/dev/null 2>&1 & exit 0; }
  done
  exit 0
fi
exec "$PYTHON" "$DEST/run_models.py" "\$@"
EOF
chmod +x "$BIN_DIR/llmtest"
say "Installed the llmtest command in $BIN_DIR"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "   Add it to your PATH:  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc && source ~/.bashrc" ;;
esac

cat <<EOF

  Start a test:        llmtest
  List a server:       llmtest --url http://localhost:1234 --list
  Servers with a key:  MODEL_API_KEY=... llmtest   (or enter it when asked)
  Results:             $DEST/results/<model>_<date-time>/report.html
  Submit a finished run: llmtest submit
  Local leaderboard:   llmtest board

EOF

# 5. Start the picker now. Read answers from the terminal even when piped from curl.
if [ "$RUN" = 1 ] && [ -r /dev/tty ]; then
  read -r -p "Start a test now? [Y/n] " reply < /dev/tty || reply=n
  case "${reply:-y}" in
    [Yy]*) exec "$BIN_DIR/llmtest" < /dev/tty ;;
  esac
fi
