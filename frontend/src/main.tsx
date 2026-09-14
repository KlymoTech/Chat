import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from '@/App';
import { AuthProvider, ToastProvider, WorkspaceProvider } from '@/components/providers';
import '@/styles.css';
import '@/help.css';
import '@/help-detail.css';
import '@fontsource-variable/inter';
import '@/theme/materialm.tokens.css';
import '@/theme/materialm.css';
import '@/theme/materialm.components.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider><WorkspaceProvider><App /></WorkspaceProvider></AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
