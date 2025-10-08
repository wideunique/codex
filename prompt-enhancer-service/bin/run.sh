 #!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

log_info() {
    printf '[INFO] %s\n' "$*"
}

log_warn() {
    printf '[WARN] %s\n' "$*" >&2
}

log_error() {
    printf '[ERROR] %s\n' "$*" >&2
}

SCRIPT_PATH="${BASH_SOURCE[0]}"
BIN_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
PROJECT_ROOT="$(cd "$BIN_DIR/.." && pwd)"
REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"
DEFAULT_CONFIG_FILE="$PROJECT_ROOT/configs/config.yaml"
CONFIG_TEMPLATE="$PROJECT_ROOT/configs/config.example.yaml"
VENV_DIR="$PROJECT_ROOT/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG_FILE="$DEFAULT_CONFIG_FILE"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config|-c)
            if [[ $# -lt 2 ]]; then
                log_error "Option --config requires a file path."
                exit 1
            fi
            shift
            CONFIG_ARG="$1"
            if [[ "$CONFIG_ARG" = /* ]]; then
                CONFIG_FILE="$CONFIG_ARG"
            else
                CONFIG_FILE="$PROJECT_ROOT/$CONFIG_ARG"
            fi
            ;;
        --help|-h)
            cat <<USAGE
Usage: $(basename "$SCRIPT_PATH") [--config <path>]
    --config, -c   Specify config file path; defaults to configs/config.yaml
    --help,  -h    Show this help message
USAGE
            exit 0
            ;;
        *)
            log_error "Unknown argument: $1"
            exit 1
            ;;
    esac
    shift
done

log_info "Using project root: $PROJECT_ROOT"
log_info "Using config file: $CONFIG_FILE"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    log_error "Python runtime '$PYTHON_BIN' not found. Install Python 3.10 or newer."
    exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    log_error "Detected Python version is too old. Please use Python 3.10+."
    exit 1
fi

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
    log_error "Missing dependency list $REQUIREMENTS_FILE."
    exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
    log_info "Virtual environment not found; creating $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    log_info "Detected existing virtual environment $VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    log_error "Virtual environment appears corrupted: $VENV_PYTHON is not executable. Remove $VENV_DIR and retry."
    exit 1
fi

log_info "Upgrading pip"
"$VENV_PYTHON" -m pip install --upgrade pip >/dev/null

log_info "Installing project dependencies"
"$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE"

if [[ ! -f "$CONFIG_FILE" ]]; then
    log_error "Configuration file $CONFIG_FILE is missing."
    log_error "Create configs/config.yaml based on $CONFIG_TEMPLATE and retry."
    exit 1
fi

log_info "Starting prompt-enhancer-service"
cd "$PROJECT_ROOT"
exec "$VENV_PYTHON" -m src.main --config "$CONFIG_FILE"