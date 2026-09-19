# PhotoForge Brev GPU accelerator

This server optionally accelerates the same commercially approved local PhotoForge AI
models on the project's NVIDIA Brev machine:

- Remove Background / Select Subject — BiRefNet-lite
- Click-to-select / object selection — SAM 2.1 Tiny

It is **not** the generative-editing backend. Describe Your Edit / Generative Fill stays on
the signed-in `phrame.tech/api/edit` → NVIDIA NIM path in `app/ai/base.py`. Keeping these
paths separate avoids having two competing implementations of roadmap A6.

```
PhotoForge desktop
    │
    │ localhost:8765 through an authenticated SSH tunnel
    ▼
Brev instance: bigbird-gpu-dev
    │
    ├── BiRefNet-lite
    └── SAM 2.1 Tiny
```

## Normal setup

1. Start the `bigbird-gpu-dev` instance in the Brev dashboard.
2. Install the Brev CLI on the computer running PhotoForge (on Windows, inside Ubuntu/WSL)
   and run `brev login` once.
3. In PhotoForge open **AI → AI Settings…**, choose **My NVIDIA cloud GPU (Brev)**, and save.

PhotoForge then manages the rest:

- creates a random PhotoForge server access token locally;
- opens the SSH tunnel;
- copies the exact server files to the Brev machine when needed;
- runs `server/setup.sh` on first setup;
- installs the server as a boot service;
- compares a server-file fingerprint on later connections and updates the server when the
  bundled files change.

If the Brev GPU is stopped or unreachable, PhotoForge falls back to the local implementation
for these tools. Generative cloud editing is unaffected because it uses the separate
`phrame.tech/api/edit` path.

The server listens on `127.0.0.1` only and also requires
`Authorization: Bearer <PHOTOFORGE_TOKEN>`. It is not intended to be exposed directly to
the public internet.

## Manual troubleshooting

From the Brev machine, from the copied `~/photoforge-server` directory:

```bash
bash server/setup.sh
export PHOTOFORGE_TOKEN='<token shown in PhotoForge AI Settings>'
bash server/install_service.sh
```

For a temporary foreground run:

```bash
export PHOTOFORGE_TOKEN='<token>'
.venv-server/bin/python -m server.photoforge_server --port 8765
```

From the desktop side, the equivalent tunnel is:

```bash
ssh -N -L 8765:127.0.0.1:8765 bigbird-gpu-dev
```

PhotoForge normally creates and owns this tunnel automatically.

## API

All endpoints require the bearer token. Bodies are NumPy `.npz` payloads.

| Endpoint | Request | Response |
|---|---|---|
| `GET /health` | — | JSON: device, providers, model state, server version |
| `POST /remove_background` | `image` (HxWx3 uint8) | `mask` (HxW uint8) |
| `POST /sam/encode` | `image` | `session` |
| `POST /sam/decode` | `session`, `points`, `labels` | `scores`, `logits` |

## Costs

Brev bills while the GPU machine is running. Stop the instance in the Brev dashboard when
you are finished using the accelerator.
