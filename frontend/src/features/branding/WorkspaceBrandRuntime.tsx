import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useWorkspace } from '@/components/providers';
import { workspaceSettingsApi, type ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';
import { applyBrandTokens } from '@/theme/brand-tokens';

const RuntimeBrandContext = createContext<ExtendedBranding | null>(null);

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
    if (!branding?.identity.brandedDashboard) return;
    const previousTitle = document.title;
    const cleanupTokens = applyBrandTokens({
      primaryColor: branding.identity.primaryColor,
      secondaryColor: branding.identity.secondaryColor,
      colors: branding.colors,
      typography: branding.typography,
      borderRadius: branding.appearance.borderRadius,
    });
    if (branding.identity.browserTitle) document.title = branding.identity.browserTitle;
    return () => {
      cleanupTokens();
      if (branding.identity.browserTitle && document.title === branding.identity.browserTitle) document.title = previousTitle;
    };
  }, [branding]);

  const value = useMemo(() => branding, [branding]);
  return <RuntimeBrandContext.Provider value={value}>{children}</RuntimeBrandContext.Provider>;
}

export function useWorkspaceBrandRuntime(): ExtendedBranding | null {
  return useContext(RuntimeBrandContext);
}
