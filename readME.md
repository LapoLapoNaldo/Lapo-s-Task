# Lapo's Task

**TinyTask para Linux** — grava e reproduz macros de teclado e mouse. Funciona no
**Hyprland/Wayland** (e também em X11).

No Wayland não existe API de captura/injeção de input em espaço de usuário, então o
Lapo's Task lê os eventos crus de `/dev/input` e os reinjeta por `/dev/uinput` via
[`evdev`](https://python-evdev.readthedocs.io/). Detecta todos os dispositivos
automaticamente — sem configuração, igual ao TinyTask.

## Recursos

- Gravar / reproduzir teclado **e** mouse (movimento, cliques, roda)
- **Começa do ponto certo**: a posição absoluta do cursor é capturada na gravação
  (via `hyprctl`) e o playback teleporta o cursor pra lá antes de reproduzir
- **Warp verificado**: após teleportar o cursor, confere a posição e retenta se
  necessário — precisão de ~1px
- **Loop**: repetir N vezes ou **infinito** ("∞ sem parar")
- **Velocidade** de reprodução ajustável (inline na janela)
- **Hotkeys globais** (padrão: F9 gravar, F10 play, Esc parar) — funcionam com a janela
  em background, e aparecem em cada botão
- **Import / Export** de macros `.json`
- Configurações persistentes (XDG) e UI dark (PySide6/Qt6)
- Macros antigas gravadas com sinal errado são reparadas automaticamente ao carregar

## Instalação

### Rápida (recomendada)

O `install.sh` instala tudo num ambiente isolado (sem mexer no Python do
sistema), cria o comando `lapos-task` e um atalho no menu de aplicativos:

```bash
git clone https://github.com/LapoLapoNaldo/Lapo-s-Task.git
cd Lapo-s-Task
./install.sh
```

Ou em uma linha, sem clonar manualmente:

```bash
curl -fsSL https://raw.githubusercontent.com/LapoLapoNaldo/Lapo-s-Task/main/install.sh | bash
```

O instalador coloca o app em `~/.local/share/lapos-task`, o launcher em
`~/.local/bin/lapos-task` e o atalho em `~/.local/share/applications`. Nenhum
passo precisa de `sudo` — exceto a configuração de permissões de input (abaixo),
que o próprio script oferece configurar ao final.

Opções:

```bash
./install.sh --permissions   # instala e já configura grupo input + regra udev (sudo)
./install.sh --uninstall     # remove o app (preserva suas macros e configurações)
./install.sh --help
```

### Permissões (uma vez)

Para ler/injetar input sem `sudo`. O `install.sh` pode fazer isto por você
(`--permissions`), ou manualmente:

```bash
sudo usermod -aG input $USER
echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# faça logout/login para o grupo 'input' valer
```

### Manual / desenvolvimento

Se preferir rodar direto do repositório:

```bash
git clone https://github.com/LapoLapoNaldo/Lapo-s-Task.git
cd Lapo-s-Task
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Uso

Depois de instalar com o `install.sh`, use o comando `lapos-task`:

### GUI

```bash
lapos-task            # ou: lapos-task gui
```

### Terminal

```bash
lapos-task record -o minha_macro     # gravar (Ctrl+C p/ parar)
lapos-task play minha_macro          # reproduzir
lapos-task play minha_macro -s 2 -l 3 # 2× mais rápido, 3 repetições
lapos-task macros                    # listar macros
lapos-task export minha_macro ~/bkp/ # exportar
lapos-task import ~/bkp/outra.json   # importar
```

> Rodando direto do repositório (instalação manual), troque `lapos-task` por
> `.venv/bin/python src/cli.py` nos comandos acima.

As macros ficam em `~/.local/share/lapos-task/macros` e o config em
`~/.config/lapos-task/config.json`.

## ⚠️ Privacidade

Por natureza, um gravador de macros captura **tudo** que você digita e clica
enquanto está gravando — incluindo senhas e dados sensíveis — e salva os eventos
em arquivos `.json` em **texto puro**. Grave apenas o necessário, evite digitar
segredos durante a gravação e trate os arquivos de macro como dados sensíveis.
Durante a gravação, o título da janela mostra `● REC` como indicador.

## Licença

MIT
