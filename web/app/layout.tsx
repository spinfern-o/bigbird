import type { Metadata, Viewport } from "next"
import { Inter } from "next/font/google"
import "./globals.css"

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" })

export const metadata: Metadata = {
  title: "Bigbird — Photo Editor",
  description:
    "Bigbird for the browser: a beginner-friendly photo editor with Lightroom-style adjustments and Photoshop-style tools.",
}

export const viewport: Viewport = {
  themeColor: "#1b1b1e",
  colorScheme: "dark",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={`${inter.variable} bg-background`}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  )
}
