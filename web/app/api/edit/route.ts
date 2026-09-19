/**
 * Cloud AI proxy for the PhotoForge desktop app (roadmap A6).
 *
 * The NVIDIA key must never ship inside the desktop app -- a key bundled with
 * PyInstaller is readable with `strings`, and once extracted it can be spent by
 * anyone and cannot be revoked without shipping an update to every user. So the
 * app never sees it. It sends the Supabase access token it already has from
 * signing in (app/auth.py), and the key stays in this function's environment.
 *
 * Guests are rejected: "Continue as guest" users have no token, so anonymous
 * callers never reach NVIDIA.
 *
 * NVIDIA_API_KEY must NOT be prefixed NEXT_PUBLIC_ -- that would inline it into
 * the browser bundle and publish it on the website.
 */

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL
const NVIDIA_API_KEY = process.env.NVIDIA_API_KEY
// Full NIM invoke URL for the image-edit model. Config rather than a constant
// because NIM model paths change; confirm yours on build.nvidia.com.
const NIM_ENDPOINT = process.env.NIM_ENDPOINT

// Vercel caps function request bodies at 4.5 MB. The desktop client downscales
// to 1024px before sending (~1.4 MB as base64 PNG), so this ceiling is a guard
// against a malformed client, not a normal path.
const MAX_BODY_BYTES = 4_000_000

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

/** Resolve a Supabase access token to a user id, or null if it isn't valid. */
async function verifyUser(authHeader: string | null): Promise<string | null> {
  if (!authHeader?.toLowerCase().startsWith("bearer ")) return null
  const token = authHeader.slice(7).trim()
  if (!token) return null

  // Ask Supabase rather than verifying a JWT signature here: this route then
  // needs no JWT secret of its own, and it honours tokens revoked server-side,
  // which a local signature check would still accept.
  const res = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
    headers: { Authorization: `Bearer ${token}`, apikey: token },
    cache: "no-store",
  })
  if (!res.ok) return null
  const user = await res.json()
  return user?.id ?? null
}

/** NIM image responses vary by model; pull the base64 payload out of the shapes we know. */
function extractImage(payload: any): string | null {
  return (
    payload?.artifacts?.[0]?.base64 ??
    payload?.image ??
    payload?.data?.[0]?.b64_json ??
    null
  )
}

export async function POST(req: Request) {
  if (!SUPABASE_URL || !NVIDIA_API_KEY || !NIM_ENDPOINT) {
    // Misconfiguration is ours, not the caller's -- don't say which var is missing.
    console.error("Cloud AI is misconfigured: missing SUPABASE_URL, NVIDIA_API_KEY or NIM_ENDPOINT")
    return json(503, { error: "Cloud AI is not available right now." })
  }

  const userId = await verifyUser(req.headers.get("authorization"))
  if (!userId) {
    return json(401, { error: "Sign in to PhotoForge to use cloud AI features." })
  }

  let body: any
  try {
    const raw = await req.text()
    if (raw.length > MAX_BODY_BYTES) {
      return json(413, { error: "That photo is too large for cloud editing." })
    }
    body = JSON.parse(raw)
  } catch {
    return json(400, { error: "That request could not be read." })
  }

  const image: string | undefined = body?.image
  const prompt: string = (body?.prompt ?? "").trim()
  if (!image) return json(400, { error: "No image was sent." })
  if (!prompt) return json(400, { error: "Describe the edit you want." })

  try {
    const res = await fetch(NIM_ENDPOINT, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${NVIDIA_API_KEY}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        prompt,
        image,
        // Optional selection mask: only this area is regenerated (A6).
        ...(body?.mask ? { mask: body.mask } : {}),
      }),
    })

    if (!res.ok) {
      // NVIDIA quotes the offending key back in auth errors, so never forward
      // the body and scrub anything key-shaped before it reaches the logs.
      const detail = (await res.text()).slice(0, 400).replace(/nvapi-[A-Za-z0-9_-]+/g, "nvapi-<redacted>")
      if (res.status === 401 || res.status === 403) {
        console.error(`NVIDIA rejected our credentials: ${res.status} ${detail}`)
        return json(502, { error: "Cloud AI is unavailable right now. Please try again later." })
      }
      if (res.status === 429) {
        return json(429, { error: "Cloud AI is busy right now. Please try again in a moment." })
      }
      console.error(`NVIDIA error ${res.status}: ${detail}`)
      return json(502, { error: "The cloud AI service could not complete that edit." })
    }

    const result = extractImage(await res.json())
    if (!result) {
      console.error("NVIDIA returned a response with no image payload")
      return json(502, { error: "The cloud AI service returned an unexpected result." })
    }
    return json(200, { image: result })
  } catch (err) {
    console.error("Cloud AI request failed:", err)
    return json(504, { error: "The cloud AI service timed out. Please try again." })
  }
}
