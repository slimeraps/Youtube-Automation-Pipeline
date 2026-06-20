# ComfyUI setup (local SDXL b-roll)

The Media Agent's `local_diffusion` source talks to a ComfyUI server you run
locally. This doc covers the one-time install and how to start the server.

## Prerequisites

- NVIDIA GPU with >=10 GB VRAM (tested on RTX 5070 12 GB)
- Recent NVIDIA driver supporting CUDA 12.x
- Python 3.10-3.12 available for ComfyUI's own venv (separate from this project)

## Install

From the project root:

```bash
mkdir -p third_party
git clone https://github.com/comfyanonymous/ComfyUI third_party/ComfyUI
cd third_party/ComfyUI
python -m venv .venv
. .venv/Scripts/activate   # Windows; use .venv/bin/activate on Linux/macOS
pip install --upgrade pip
pip install -r requirements.txt
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

(Adjust the torch CUDA wheel index if your driver needs a different version.)

## Download SDXL base 1.0

Roughly 7 GB.

```bash
mkdir -p models/checkpoints
curl -L https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors \
  -o models/checkpoints/sd_xl_base_1.0.safetensors
```

(If you have HuggingFace auth set up you may need `huggingface-cli download` instead.)

## Run

From `third_party/ComfyUI` with the venv active:

```bash
python main.py --listen 127.0.0.1 --port 8188
```

Leave that terminal running. The pipeline talks to it at `http://127.0.0.1:8188`.

Smoke test from a separate terminal:

```bash
curl http://127.0.0.1:8188/system_stats
```

You should see a JSON system info blob.

## Pipeline config

Defaults in `src/yt_auto/config.py` already point at `http://127.0.0.1:8188` and
set `media_source=local_diffusion`. Override either via environment:

```bash
export COMFYUI_URL=http://127.0.0.1:8189   # if you moved the port
export MEDIA_SOURCE=pexels                 # to force the Pexels fallback
```

## Failure modes

- **ComfyUI not running:** the run logs one warning at startup, then falls back
  to Pexels for the whole run. The video still renders.
- **Per-scene generation timeout / crash:** that one scene falls back to Pexels;
  the rest stay on SDXL.
- **Pexels also fails on the same scene:** the run aborts with `MediaError`.
