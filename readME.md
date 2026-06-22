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
- **Loop**: repetir N vezes ou **infinito** ("∞ sem parar")
- **Velocidade** de reprodução ajustável (inline na janela)
- **Hotkeys globais** (padrão: F9 gravar, F10 play, Esc parar) — funcionam com a janela
  em background, e aparecem em cada botão
- **Import / Export** de macros `.json`
- Configurações persistentes (XDG) e UI dark (PySide6/Qt6)
- Macros antigas gravadas com sinal errado são reparadas automaticamente ao carregar

## Instalação

```bash
git clone https://github.com/SEU_USER/lapos-task.git
cd lapos-task
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Permissões (uma vez)

Para ler/injetar input sem `sudo`:

```bash
sudo usermod -aG input $USER
echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# faça logout/login para o grupo 'input' valer
```

## Uso

### GUI

```bash
.venv/bin/python src/cli.py            # ou: .venv/bin/python src/cli.py gui
```

### Terminal

```bash
.venv/bin/python src/cli.py record -o minha_macro     # gravar (Ctrl+C p/ parar)
.venv/bin/python src/cli.py play minha_macro          # reproduzir
.venv/bin/python src/cli.py play minha_macro -s 2 -l 3 # 2× mais rápido, 3 repetições
.venv/bin/python src/cli.py macros                    # listar macros
.venv/bin/python src/cli.py export minha_macro ~/bkp/ # exportar
.venv/bin/python src/cli.py import ~/bkp/outra.json   # importar
```

As macros ficam em `~/.local/share/lapos-task/macros` e o config em
`~/.config/lapos-task/config.json`.

## Licença

MIT
