"use client"

import { createClient } from "@/lib/supabase/client"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { useState } from "react"

// Only the credential/existence signal is genericized — naming it would confirm
// whether an email is registered. Errors the user can act on are passed through.
function loginErrorMessage(error: unknown): string {
  const { code } = (error ?? {}) as { code?: string }
  if (code === "invalid_credentials") {
    return "Invalid email or password."
  }
  return "Something went wrong. Please try again."
}

// Only hand tokens back to a local loopback address the desktop app is listening on.
function isLoopback(uri: string): boolean {
  try {
    const u = new URL(uri)
    return (
      (u.protocol === "http:" || u.protocol === "https:") &&
      (u.hostname === "127.0.0.1" || u.hostname === "localhost" || u.hostname === "[::1]")
    )
  } catch {
    return false
  }
}

export function LoginForm() {
  const params = useSearchParams()
  const redirectUri = params.get("redirect_uri")
  const state = params.get("state") ?? ""
  const hasDesktopTarget = redirectUri !== null && isLoopback(redirectUri)

  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<"idle" | "loading" | "done">("idle")

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setStatus("loading")
    setError(null)

    try {
      const supabase = createClient()
      const { data, error } = await supabase.auth.signInWithPassword({ email, password })
      if (error) throw error

      const session = data.session
      if (hasDesktopTarget && session) {
        const url = new URL(redirectUri as string)
        url.searchParams.set("access_token", session.access_token)
        url.searchParams.set("refresh_token", session.refresh_token)
        url.searchParams.set("expires_at", String(session.expires_at ?? ""))
        url.searchParams.set("email", session.user.email ?? "")
        url.searchParams.set("state", state)
        setStatus("done")
        window.location.href = url.toString()
        return
      }
      setStatus("done")
    } catch (err: unknown) {
      console.error("[v0] login error:", err)
      setError(loginErrorMessage(err))
      setStatus("idle")
    }
  }

  if (status === "done") {
    return (
      <div className="rounded-lg border border-border bg-panel p-6 text-center">
        <h2 className="text-base font-medium">You are signed in</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          {hasDesktopTarget
            ? "Returning you to PhotoForge. You can close this tab if it does not close on its own."
            : "Open PhotoForge on your computer and press Log in to connect this account."}
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-panel p-6">
      <h2 className="text-base font-medium">Sign in to PhotoForge</h2>
      <p className="mt-1 text-sm text-muted">
        {hasDesktopTarget
          ? "Signing in will connect this account to the desktop app."
          : "Enter your account credentials below."}
      </p>

      <form onSubmit={handleLogin} className="mt-6 flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="email" className="text-sm text-foreground">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="h-10 rounded-md border border-border-strong bg-canvas px-3 text-sm text-foreground outline-none focus:border-accent"
            placeholder="you@example.com"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="password" className="text-sm text-foreground">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="h-10 rounded-md border border-border-strong bg-canvas px-3 text-sm text-foreground outline-none focus:border-accent"
            placeholder="••••••••"
          />
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button
          type="submit"
          disabled={status === "loading"}
          className="inline-flex h-10 items-center justify-center rounded-md bg-accent px-4 text-sm font-medium text-accent-foreground transition-colors hover:bg-accent-hover disabled:opacity-60"
        >
          {status === "loading" ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-muted">
        No account yet?{" "}
        <Link href="/sign-up" className="text-accent underline-offset-4 hover:underline">
          Create one
        </Link>
      </p>
    </div>
  )
}
