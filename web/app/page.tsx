import Link from "next/link"

export default function Home() {
  return (
    <main className="flex min-h-svh w-full flex-col items-center justify-center px-6 py-16">
      <div className="w-full max-w-md">
        <div className="mb-10 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-accent text-accent-foreground">
            <span className="text-lg font-semibold">P</span>
          </div>
          <div>
            <h1 className="text-lg font-semibold leading-tight">PhotoForge Account</h1>
            <p className="text-sm text-muted">Sign in to sync your PhotoForge photo editor</p>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-panel p-6">
          <h2 className="text-base font-medium">Signing in from the desktop app</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            Click <span className="text-foreground">Log in</span> inside PhotoForge on your computer. It opens this page
            in your browser, you sign in, and you are returned to the app automatically.
          </p>

          <div className="mt-6 flex flex-col gap-3">
            <Link
              href="/desktop-login"
              className="inline-flex h-10 items-center justify-center rounded-md bg-accent px-4 text-sm font-medium text-accent-foreground transition-colors hover:bg-accent-hover"
            >
              Go to sign in
            </Link>
            <Link
              href="/sign-up"
              className="inline-flex h-10 items-center justify-center rounded-md border border-border-strong px-4 text-sm font-medium text-foreground transition-colors hover:bg-panel-raised"
            >
              Create an account
            </Link>
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-muted">
          PhotoForge desktop stays on your machine. This page only handles your account sign in.
        </p>
      </div>
    </main>
  )
}
