# PhotoForge GPU server (NVIDIA Brev)

Runs PhotoForge's heavy AI on a cloud NVIDIA GPU so it works fast on any laptop:
background removal / Select Subject (BiRefNet), click-to-select objects (SAM 2.1), and
**Fill Removed Area** (LaMa, cloud only). Light work such as retouching and selections
stays on your PC.

```
PhotoForge (your PC) ──localhost:8765──▶ brev port-forward ──▶ Brev GPU: server/photoforge_server.py
```

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

## 3. Start the server

In PhotoForge open **AI → AI Settings…**, click **New** next to *Access token*, then **Copy**.
On the GPU machine:

```bash
cd bigbird
export PHOTOFORGE_TOKEN='paste-the-token-here'
bash server/start.sh
```

## 4. Connect PhotoForge

1. Install the [Brev CLI](https://docs.nvidia.com/brev/) on your PC and run `brev login` once.
2. In **AI → AI Settings…**: choose **My NVIDIA cloud GPU (Brev)**, enter the instance
   name, click **Connect**, then **Test Connection**. It should report `NVIDIA GPU (CUDA)`.
3. Click **Save**. Remove Background, Select Subject, Select Object(s) to Remove and
   **Fill Removed Area** now run on the cloud GPU.

(Alternatively run `brev port-forward photoforge-gpu --port 8765:8765` yourself and leave
it open.)

## Costs

Brev bills per hour while the instance runs. **Stop the instance in the Brev console
when you're done editing**. A stopped instance only incurs a small storage charge; delete
it to remove that too. After restarting it, run `bash server/start.sh` again.

## API (for reference)

All endpoints need `Authorization: Bearer <PHOTOFORGE_TOKEN>`. Bodies are numpy `.npz`.

| Endpoint | Request | Response |
|---|---|---|
| `GET /health` | – | JSON: device, providers, models |
| `POST /remove_background` | `image` (HxWx3 uint8) | `mask` (HxW uint8) |
| `POST /sam/encode` | `image` | `session` |
| `POST /sam/decode` | `session`, `points` (Nx2), `labels` (N) | `scores` (3), `logits` (3x256x256) |
| `POST /fill` | `image` (crop), `mask` (crop) | `image` (filled crop) |
