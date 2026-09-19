# PhotoForge GPU server (NVIDIA Brev)

Runs PhotoForge's heavy AI on a cloud NVIDIA GPU so it works fast on any laptop:
background removal / Select Subject (BiRefNet), click-to-select objects (SAM 2.1), and
**Fill Removed Area** (LaMa, cloud only). Light work such as retouching and selections
stays on your PC.

```
PhotoForge (your PC) ──localhost:8765──▶ brev port-forward ──▶ Brev GPU: server/photoforge_server.py
```

## Automatic setup (recommended)

You only need to:
1. Create a GPU instance at [brev.nvidia.com](https://brev.nvidia.com) (any NVIDIA GPU).
2. On your PC, install the Brev CLI (on Windows, inside Ubuntu/WSL) and run `brev login` once.
3. In PhotoForge choose **AI → AI Settings… → My NVIDIA cloud GPU (Brev)** and click **Save**
   (or **Start GPU**).

PhotoForge then does everything else by itself:
- finds your instance and creates the access token
- copies this server to the GPU over SSH, installs it (about 5 minutes the first time) and
  makes it start at boot
- keeps it updated whenever PhotoForge's AI code changes
- connects automatically whenever you open the app and the GPU is on

Optional checkboxes in AI Settings start the GPU when PhotoForge opens and stop it when
PhotoForge closes.

The manual steps below are only for reference or troubleshooting.

The server listens only on `127.0.0.1` of the GPU machine and requires an access token.
It's reachable only through `brev port-forward` (an authenticated tunnel), never directly
from the internet.

## 1. Create the GPU machine (once)

1. Go to [brev.nvidia.com](https://brev.nvidia.com), then **GPUs → Create Environment**.
2. Choose any NVIDIA GPU. An **L4** or **T4** is plenty; these models are small.
3. Give it a name, e.g. `photoforge-gpu`, and create it.

## 2. Install the server on it (once)

Open the instance's terminal (Brev console → **Open Notebook/Terminal**, or `brev shell photoforge-gpu`):

```bash
git clone https://github.com/spinfern-o/bigbird.git
cd bigbird
bash server/setup.sh
```

## 3. Make the server start automatically (once)

In PhotoForge open **AI → AI Settings…**, click **New** next to *Access token*, then **Copy**.
On the GPU machine:

```bash
cd bigbird
export PHOTOFORGE_TOKEN='paste-the-token-here'
bash server/install_service.sh
```

This installs the server as a system service. It starts by itself whenever the instance
boots, remembers the token, and restarts if it ever crashes.

## 4. Connect PhotoForge (once)

1. Install the [Brev CLI](https://docs.nvidia.com/brev/) (on Windows: inside Ubuntu/WSL) and
   run `brev login` once.
2. In **AI → AI Settings…**: choose **My NVIDIA cloud GPU (Brev)**, enter the **Brev
   instance** name (see `brev ls`), and click **Save**.

From then on it's automatic: when PhotoForge opens, it checks whether your instance is
running and, if it is, opens a secure SSH tunnel in the background and connects. The bottom
status bar shows **☁ GPU connected**. If the GPU is off, PhotoForge uses this computer. After
starting the GPU later, click **Try Connecting Again** in AI Settings (or click the status).

Everyday use: `brev start <name>`, then open PhotoForge and edit. When you're done,
`brev stop <name>`.

## Costs

Brev bills per hour while the instance runs. **Stop the instance in the Brev console
when you're done editing**. A stopped instance only incurs a small storage charge; delete
it to remove that too. The server starts by itself when the instance boots.

## API (for reference)

All endpoints need `Authorization: Bearer <PHOTOFORGE_TOKEN>`. Bodies are numpy `.npz`.

| Endpoint | Request | Response |
|---|---|---|
| `GET /health` | – | JSON: device, providers, models |
| `POST /remove_background` | `image` (HxWx3 uint8) | `mask` (HxW uint8) |
| `POST /sam/encode` | `image` | `session` |
| `POST /sam/decode` | `session`, `points` (Nx2), `labels` (N) | `scores` (3), `logits` (3x256x256) |
| `POST /fill` | `image` (crop), `mask` (crop) | `image` (filled crop) |
