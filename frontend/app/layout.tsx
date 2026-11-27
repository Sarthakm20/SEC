import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Shell } from "@/components/Shell";

// Fonts ship with the repo (npm @fontsource packages), so builds never fetch from Google Fonts.
const plex = localFont({
  src: [
    { path: "../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-500-normal.woff2", weight: "500", style: "normal" },
    { path: "../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-600-normal.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-plex",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});
const serif = localFont({
  src: [
    { path: "../node_modules/@fontsource/source-serif-4/files/source-serif-4-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../node_modules/@fontsource/source-serif-4/files/source-serif-4-latin-400-italic.woff2", weight: "400", style: "italic" },
    { path: "../node_modules/@fontsource/source-serif-4/files/source-serif-4-latin-600-normal.woff2", weight: "600", style: "normal" },
    { path: "../node_modules/@fontsource/source-serif-4/files/source-serif-4-latin-600-italic.woff2", weight: "600", style: "italic" },
  ],
  variable: "--font-serif4",
  display: "swap",
  fallback: ["Georgia", "serif"],
});

export const metadata: Metadata = {
  title: "10-K Research",
  description: "Verifiable answers from SEC 10-K filings: XBRL facts, deterministic calculations and cited filing passages.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${plex.variable} ${serif.variable}`}>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
