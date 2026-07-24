import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic QA Copilot",
  description: "Graph RAG + Vector RAG agentic QA intelligence system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}