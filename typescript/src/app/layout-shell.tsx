'use client'

import { SidebarLayout } from '@/components/sidebar-layout'
import {
  Sidebar,
  SidebarBody,
  SidebarHeader,
  SidebarItem,
  SidebarLabel,
  SidebarSection,
  SidebarSpacer,
} from '@/components/sidebar'
import { Navbar, NavbarSection, NavbarSpacer } from '@/components/navbar'
import { Heading } from '@/components/heading'
import { Listbox, ListboxLabel, ListboxOption } from '@/components/listbox'
import {
  ArrowUpTrayIcon,
  Cog6ToothIcon,
  CpuChipIcon,
  DocumentMagnifyingGlassIcon,
  LanguageIcon,
  BookOpenIcon,
} from '@heroicons/react/20/solid'
import { useI18n, type Lang } from '@/lib/i18n'

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const { t, lang, setLang } = useI18n()
  return (
    <SidebarLayout
      sidebar={
        <Sidebar>
          <SidebarHeader>
            <Heading level={2}>Paper Agent</Heading>
          </SidebarHeader>
          <SidebarBody>
            <SidebarSection>
              <SidebarItem href="/">
                <ArrowUpTrayIcon />
                <SidebarLabel>{t('nav.upload')}</SidebarLabel>
              </SidebarItem>
              <SidebarItem href="/sessions">
                <DocumentMagnifyingGlassIcon />
                <SidebarLabel>{t('nav.sessions')}</SidebarLabel>
              </SidebarItem>
              <SidebarItem href="/logs">
                <CpuChipIcon />
                <SidebarLabel>{t('nav.logs')}</SidebarLabel>
              </SidebarItem>
              <SidebarItem href="/skills">
                <BookOpenIcon />
                <SidebarLabel>Skills</SidebarLabel>
              </SidebarItem>
              <SidebarItem href="/settings">
                <Cog6ToothIcon />
                <SidebarLabel>{t('nav.settings')}</SidebarLabel>
              </SidebarItem>
            </SidebarSection>
            <SidebarSpacer />
            <SidebarSection>
              <div className="flex items-center gap-2 px-3 text-sm text-zinc-500">
                <LanguageIcon className="size-4" />
                <Listbox value={lang} onChange={(v) => setLang((v ?? 'en') as Lang)}>
                  <ListboxOption value="en"><ListboxLabel>English</ListboxLabel></ListboxOption>
                  <ListboxOption value="zh"><ListboxLabel>中文</ListboxLabel></ListboxOption>
                </Listbox>
              </div>
            </SidebarSection>
          </SidebarBody>
        </Sidebar>
      }
      navbar={
        <Navbar>
          <NavbarSection>
            <SidebarLabel>Paper Agent</SidebarLabel>
          </NavbarSection>
          <NavbarSpacer />
        </Navbar>
      }
    >
      {children}
    </SidebarLayout>
  )
}
