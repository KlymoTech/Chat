import { Suspense } from 'react';
import { PageErrorBoundary } from '@/components/PageErrorBoundary';
import { PageLoader } from '@/components/ui';
import { AppRoutes } from './routes';

/** Application shell: error boundary, suspense boundary, and route composition. */
export function App() {
  return <PageErrorBoundary><Suspense fallback={<PageLoader />}><AppRoutes /></Suspense></PageErrorBoundary>;
}
