import type { Metadata } from "next";
import { IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";
import "./globals.css";
import { Shell } from "@/components/Shell";

const plex = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-plex", display: "swap" });
const serif = Source_Serif_4({ subsets: ["latin"], weight: ["400", "600"], style: ["normal", "italic"], variable: "--font-serif4", display: "swap" });

export const metadata: Metadata = {
  title: "10-K Research",
  description: "Verifiable answers from SEC 10-K filings: XBRL facts, deterministic calculations and cited filing passages.",
};

// Applied before paint so a stored theme choice never flashes.
const themeScript = `try{var t=localStorage.getItem('theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t;}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${plex.variable} ${serif.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
