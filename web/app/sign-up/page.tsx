"use client"

import { createClient } from "@/lib/supabase/client"
import Link from "next/link"
import { useState } from "react"

function signUpErrorMessage(error: unknown): string {
  const { code, status } = (error ?? {}) as { code?: string; status?: number }
  if (code === "weak_password") {
    return "Please choose a stronger password (at least 6 characters)."
  }
  if (code === "user_already_exists" || code === "email_exists") {
    return "An account with this email may already exist. Try signing in instead."
  }
  if (code === "over_email_send_rate_limit" || status === 429) {
    return "Too many attempts. Please wait a moment and try again."
  }
  return "Something went wrong. Please try again."
}

export default function SignUpPage() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<"idle" | "loading" | "done">("idle")

  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault()
    setStatus("loading")
    setError(null)

    try {
      const supabase = createClient()
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          emailRedirectTo:
            process.env.NEXT_PUBLIC_DEV_SUPABASE_REDIRECT_URL ?? `${window.location.origin}/desktop-login`,
        },
      })
      if (error) throw error
      setStatus("done")
    } catch (err: unknown) {
      console.error("[v0] sign-up error:", err)
      setError(signUpErrorMessage(err))
      setStatus("idle")
    }
  }

  return (
    <main className="flex min-h-svh w-full flex-col items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-accent text-accent-foreground">
            <span className="text-lg font-semibold">P</span>
          </div>
          <div>
            <h1 className="text-lg font-semibold leading-tight">PhotoForge</h1>
            <p className="text-sm text-muted">Create your account</p>
          </div>
        </div>

        {status === "done" ? (
          <div className="rounded-lg border border-border bg-panel p-6 text-center">
            <h2 className="text-base font-medium">Check your email</h2>
            <p className="mt-2 text-sm leading-relaxed text-muted">
              We sent a confirmation link to <span className="text-foreground">{email}</span>. Confirm your address,
              then sign in from the PhotoForge desktop app.
            </p>
            <Link
              href="/desktop-login"
              className="mt-6 inline-flex h-10 w-full items-center justify-center rounded-md border border-border-strong px-4 text-sm font-medium text-foreground transition-colors hover:bg-panel-raised"
            >
              Go to sign in
            </Link>
          </div>
        ) : (
          <div className="rounded-lg border border-border bg-panel p-6">
            <h2 className="text-base font-medium">Sign up</h2>
            <p className="mt-1 text-sm text-muted">Use your email and a password.</p>

            <form onSubmit={handleSignUp} className="mt-6 flex flex-col gap-4">
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
                  autoComplete="new-password"
                  minLength={6}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-10 rounded-md border border-border-strong bg-canvas px-3 text-sm text-foreground outline-none focus:border-accent"
                  placeholder="At least 6 characters"
                />
              </div>

              {error && <p className="text-sm text-red-400">{error}</p>}

              <button
                type="submit"
                disabled={status === "loading"}
                className="inline-flex h-10 items-center justify-center rounded-md bg-accent px-4 text-sm font-medium text-accent-foreground transition-colors hover:bg-accent-hover disabled:opacity-60"
              >
                {status === "loading" ? "Creating account…" : "Create account"}
              </button>
            </form>

            <p className="mt-4 text-center text-sm text-muted">
              Already have an account?{" "}
              <Link href="/desktop-login" className="text-accent underline-offset-4 hover:underline">
                Sign in
              </Link>
            </p>
          </div>
        )}
      </div>
    </main>
  )
}
