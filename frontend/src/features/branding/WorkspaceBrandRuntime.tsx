import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useWorkspace } from '@/components/providers';
import { workspaceSettingsApi, type ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';

const RuntimeBrandContext = createContext<ExtendedBranding | null>(null);
const BRAND_VARIABLES = [
  '--brand-primary','--brand-primary-hover','--brand-secondary','--brand-accent','--brand-background',
  '--brand-surface','--brand-sidebar','--brand-sidebar-text','--brand-header','--brand-text','--brand-muted',
  '--brand-success','--brand-warning','--brand-error','--brand-border','--brand-link','--brand-font',
  '--brand-heading-font','--brand-font-size','--brand-radius',
] as const;

function setVariable(name: string, value: string | number | undefined) {
  const root = document.documentElement;
  if (value === undefined || value === '') root.style.removeProperty(name);
  else root.style.setProperty(name, String(value));
}

function clearBrandVariables() {
  BRAND_VARIABLES.forEach((name) => document.documentElement.style.removeProperty(name));
}

export function WorkspaceBrandRuntime({ children }: { children: ReactNode }) {
  const { activeWorkspace } = useWorkspace();
  const [branding, setBranding] = useState<ExtendedBranding | null>(null);

  useEffect(() => {
    let current = true;
    if (!activeWorkspace) {
      setBranding(null);
      return () => { current = false; };
    }
    workspaceSettingsApi.runtimeBranding().then((value) => { if (current) setBranding(value); }).catch(() => { if (current) setBranding(null); });
    return () => { current = false; };
  }, [activeWorkspace?.id]);

  useEffect(() => {
    if (!branding?.identity.brandedDashboard) {
      clearBrandVariables();
      return;
    }
    const previousTitle = document.title;
    const { identity, colors, typography, appearance } = branding;
    setVariable('--brand-primary', identity.primaryColor);
    setVariable('--brand-primary-hover', colors.primaryHover);
    setVariable('--brand-secondary', identity.secondaryColor);
    setVariable('--brand-accent', colors.accent);
    setVariable('--brand-background', colors.background);
    setVariable('--brand-surface', colors.surface);
    setVariable('--brand-sidebar', colors.sidebarBackground);
    setVariable('--brand-sidebar-text', colors.sidebarText);
    setVariable('--brand-header', colors.header);
    setVariable('--brand-text', colors.textPrimary);
    setVariable('--brand-muted', colors.textSecondary);
    setVariable('--brand-success', colors.success);
    setVariable('--brand-warning', colors.warning);
    setVariable('--brand-error', colors.error);
    setVariable('--brand-border', colors.border);
    setVariable('--brand-link', colors.link);
    setVariable('--brand-font', typography.bodyFont);
    setVariable('--brand-heading-font', typography.headingFont);
    setVariable('--brand-font-size', `${typography.baseFontSize}px`);
    setVariable('--brand-radius', `${appearance.borderRadius}px`);
    if (identity.browserTitle) document.title = identity.browserTitle;
    return () => {
      clearBrandVariables();
      if (identity.browserTitle && document.title === identity.browserTitle) document.title = previousTitle;
    };
  }, [branding]);

  const value = useMemo(() => branding, [branding]);
  return <RuntimeBrandContext.Provider value={value}>{children}</RuntimeBrandContext.Provider>;
}

export function useWorkspaceBrandRuntime(): ExtendedBranding | null {
  return useContext(RuntimeBrandContext);
}
