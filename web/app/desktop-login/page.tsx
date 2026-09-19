import { Suspense } from "react"
import { LoginForm } from "./login-form"

export default function DesktopLoginPage() {
  return (
    <main className="flex min-h-svh w-full flex-col items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-accent text-accent-foreground">
            <span className="text-lg font-semibold">P</span>
          </div>
          <div>
            <h1 className="text-lg font-semibold leading-tight">PhotoForge</h1>
            <p className="text-sm text-muted">Account sign in</p>
          </div>
        </div>

        <Suspense
          fallback={
            <div className="rounded-lg border border-border bg-panel p-6 text-sm text-muted">Loading…</div>
          }
        >
          <LoginForm />
        </Suspense>
      </div>
    </main>
  )
}
