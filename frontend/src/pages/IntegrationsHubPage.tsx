import { Settings2 } from 'lucide-react';
import { ZohoOneClickIntegration } from '@/components/ZohoOneClickIntegration';
import { CRMIntegrationsPage } from '@/pages/CRMIntegrationsPage';

export function IntegrationsHubPage() {
  return <div className="integrations-hub">
    <ZohoOneClickIntegration />
    <details className="integrations-hub__advanced">
      <summary><Settings2 /> Advanced and other CRM/channel integrations</summary>
      <div className="integrations-hub__advanced-content"><CRMIntegrationsPage /></div>
    </details>
  </div>;
}
