import type { Metadata } from "next";
import { EB_Garamond, Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const garamond = EB_Garamond({ subsets: ["latin"], variable: "--font-garamond" });

export const metadata: Metadata = {
  title: "Picard-OSS",
  description: "Local-first legal document assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${inter.variable} ${garamond.variable} antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
