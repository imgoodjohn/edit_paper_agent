import '@/styles/tailwind.css'
import 'katex/dist/katex.min.css'
import type { Metadata } from 'next'
import { LayoutShell } from './layout-shell'
import { I18nProvider } from '@/lib/i18n'

export const metadata: Metadata = {
  title: {
    template: '%s — Paper Agent',
    default: 'Paper Agent',
  },
  description: 'Multi-agent manuscript reviewer and editor',
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className="text-zinc-950 antialiased lg:bg-zinc-100 dark:bg-zinc-900 dark:text-white dark:lg:bg-zinc-950"
    >
      <head>
        <link rel="preconnect" href="https://rsms.me/" />
        <link rel="stylesheet" href="https://rsms.me/inter/inter.css" />
      </head>
      <body>
        <I18nProvider>
          <LayoutShell>{children}</LayoutShell>
        </I18nProvider>
      </body>
    </html>
  )
}
