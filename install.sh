#!/usr/bin/env bash
#
# Instalador do Lapo's Task — gravador de macros para Linux/Wayland.
#
# Uso:
#   ./install.sh                 # instala (rodando dentro do repo ou via curl|bash)
#   ./install.sh --permissions   # instala e também configura grupo input + udev (sudo)
#   ./install.sh --uninstall     # remove o app (preserva macros e config)
#
# Instalação por usuário (sem root): app + venv em ~/.local/share/lapos-task,
# launcher em ~/.local/bin/lapos-task e atalho no menu de aplicativos.
#
set -euo pipefail

REPO_URL="${LAPOS_REPO:-https://github.com/LapoLapoNaldo/Lapo-s-Task.git}"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
BASE="$DATA_HOME/lapos-task"
APP_DIR="$BASE/app"
VENV_DIR="$BASE/venv"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/lapos-task"
DESKTOP="$DATA_HOME/applications/lapos-task.desktop"

# ----------------------------------------------------------------- helpers
if [ -t 1 ]; then
    BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi
info()  { printf '%s==>%s %s\n' "$GREEN$BOLD" "$RESET" "$*"; }
warn()  { printf '%s!  %s%s\n' "$YELLOW" "$*" "$RESET"; }
die()   { printf '%sErro:%s %s\n' "$RED$BOLD" "$RESET" "$*" >&2; exit 1; }

# ----------------------------------------------------------------- uninstall
uninstall() {
    info "Removendo o Lapo's Task..."
    rm -rf "$APP_DIR" "$VENV_DIR"
    rm -f "$LAUNCHER" "$DESKTOP"
    # remove a base só se ficou vazia (preserva macros/config do usuário)
    rmdir "$BASE" 2>/dev/null || true
    info "Removido. Suas macros e configurações foram preservadas em:"
    printf '   %s\n' "$BASE/macros"
    printf '   %s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/lapos-task"
    exit 0
}

# ----------------------------------------------------------------- permissions
setup_permissions() {
    info "Configurando permissões de input (requer sudo)..."
    if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
        info "Você já está no grupo 'input'."
    else
        sudo usermod -aG input "$USER"
        warn "Adicionado ao grupo 'input' — faça logout/login para valer."
    fi
    echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' \
        | sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null
    sudo udevadm control --reload-rules && sudo udevadm trigger
    info "Regra udev do /dev/uinput instalada."
}

# ----------------------------------------------------------------- args
DO_PERMISSIONS=0
for arg in "$@"; do
    case "$arg" in
        --uninstall) uninstall ;;
        --permissions) DO_PERMISSIONS=1 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Argumento desconhecido: $arg (use --help)" ;;
    esac
done

# ----------------------------------------------------------------- python
PYTHON="$(command -v python3 || true)"
[ -n "$PYTHON" ] || die "python3 não encontrado. Instale o Python 3.8+ e tente de novo."

# ----------------------------------------------------------------- fonte
# Detecta se estamos rodando dentro do repositório; senão, clona.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
CLEANUP_SRC=""
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/src/cli.py" ]; then
    SRC_DIR="$SCRIPT_DIR"
    info "Usando o código local em $SRC_DIR"
else
    command -v git >/dev/null || die "git não encontrado (necessário para baixar o app)."
    SRC_DIR="$(mktemp -d)"
    CLEANUP_SRC="$SRC_DIR"
    info "Baixando o Lapo's Task de $REPO_URL ..."
    git clone --depth 1 "$REPO_URL" "$SRC_DIR" >/dev/null 2>&1 \
        || die "Falha ao clonar o repositório."
fi
[ -f "$SRC_DIR/requirements.txt" ] || die "requirements.txt não encontrado na fonte."

cleanup() { [ -n "$CLEANUP_SRC" ] && rm -rf "$CLEANUP_SRC"; }
trap cleanup EXIT

# ----------------------------------------------------------------- instala app
info "Instalando arquivos em $APP_DIR ..."
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -r "$SRC_DIR/src" "$APP_DIR/"
cp "$SRC_DIR/requirements.txt" "$APP_DIR/"

# ----------------------------------------------------------------- venv + deps
info "Criando ambiente virtual e instalando dependências..."
"$PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

# ----------------------------------------------------------------- launcher
info "Criando launcher em $LAUNCHER ..."
mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Launcher gerado pelo install.sh do Lapo's Task
exec "$VENV_DIR/bin/python" "$APP_DIR/src/cli.py" "\$@"
EOF
chmod +x "$LAUNCHER"

# ----------------------------------------------------------------- desktop
info "Criando atalho no menu de aplicativos..."
mkdir -p "$(dirname "$DESKTOP")"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Lapo's Task
GenericName=Gravador de macros
Comment=Grava e reproduz macros de teclado e mouse (Wayland/X11)
Exec=$LAUNCHER gui
Icon=input-keyboard
Terminal=false
Categories=Utility;
Keywords=macro;automation;recorder;tinytask;
EOF
update-desktop-database "$(dirname "$DESKTOP")" >/dev/null 2>&1 || true

# ----------------------------------------------------------------- permissões
if [ "$DO_PERMISSIONS" -eq 1 ]; then
    setup_permissions
elif [ -t 0 ]; then
    if ! id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
        printf '\n'
        read -r -p "Configurar permissões de input agora? (precisa de sudo) [s/N] " ans
        case "$ans" in [sSyY]*) setup_permissions ;; esac
    fi
fi

# ----------------------------------------------------------------- final
printf '\n'
info "${BOLD}Instalação concluída!${RESET}"
printf '   Rode com:  %slapos-task%s   (ou procure \"Lapo'\''s Task\" no menu)\n' "$BOLD" "$RESET"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR não está no seu PATH. Adicione ao seu shell:"
       printf '       export PATH="%s:$PATH"\n' "$BIN_DIR" ;;
esac

if ! id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
    warn "Permissões de input não configuradas. Rode: ./install.sh --permissions"
    warn "(sem elas, gravar/reproduzir falha com erro de dispositivo)."
fi