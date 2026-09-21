import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';

export type PublicBranding = {
  workspaceId: string;
  companyName: string;
  browserTitle: string;
  logoDataUrl: string;
  faviconDataUrl: string;
  primaryColor: string;
  secondaryColor: string;
  colors: Record<string, string>;
  typography: Record<string, string | number>;
  authentication: {
    loginLogo?: string;
    loginBackground?: string;
    loginTitle?: string;
    loginDescription?: string;
    termsUrl?: string;
    privacyUrl?: string;
    supportUrl?: string;
    footer?: string;
  };
  supportUrl: string;
};

const PublicBrandingContext = createContext<PublicBranding | null>(null);

function setFavicon(dataUrl: string) {
  if (!dataUrl) return;
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    document.head.appendChild(link);
  }
  link.href = dataUrl;
}

function applyTokens(brand: PublicBranding) {
  const root = document.documentElement;
  const tokens: Record<string, string> = {
    '--brand-primary': brand.primaryColor,
    '--brand-secondary': brand.secondaryColor,
    '--brand-accent': brand.colors.accent ?? brand.primaryColor,
    '--brand-background': brand.colors.background ?? '#ffffff',
    '--brand-surface': brand.colors.surface ?? '#ffffff',
    '--brand-border': brand.colors.border ?? '#e5e7eb',
    '--brand-text': brand.colors.textPrimary ?? '#111827',
    '--brand-muted': brand.colors.textSecondary ?? '#6b7280',
    '--brand-sidebar': brand.colors.sidebarBackground ?? '#ffffff',
    '--brand-sidebar-text': brand.colors.sidebarText ?? '#111827',
  };
  Object.entries(tokens).forEach(([name, value]) => root.style.setProperty(name, value));
  const font = String(brand.typography.bodyFont ?? '');
  if (font) root.style.setProperty('--brand-font', font);
}

export function PublicBrandingProvider({ children }: { children: ReactNode }) {
  const [brand, setBrand] = useState<PublicBranding | null>(null);
  const hostname = useMemo(() => window.location.hostname.toLowerCase(), []);

  useEffect(() => {
    let current = true;
    const controller = new AbortController();
    fetch(`${API_URL}/branding/public?hostname=${encodeURIComponent(hostname)}`, {
      headers: { Accept: 'application/json' },
      credentials: 'omit',
      cache: 'no-store',
      signal: controller.signal,
    })
      .then(async (response) => response.ok ? await response.json() as PublicBranding : null)
      .then((value) => {
        if (!current || !value) return;
        setBrand(value);
        if (value.browserTitle) document.title = value.browserTitle;
        setFavicon(value.faviconDataUrl);
        applyTokens(value);
      })
      .catch(() => undefined);
    return () => { current = false; controller.abort(); };
  }, [hostname]);

  return <PublicBrandingContext.Provider value={brand}>{children}</PublicBrandingContext.Provider>;
}

export function usePublicBranding() {
  return useContext(PublicBrandingContext);
}
