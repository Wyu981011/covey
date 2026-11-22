import React from 'react';
import { createRoot } from 'react-dom/client';
import { createPortal } from 'react-dom';
import { BrowserRouter } from 'react-router-dom';
import { ErrorBoundary } from 'react-error-boundary';

import { AppContainer } from './AppContainer';
import { ErrorRender } from './ErrorRender';
import RoutesComponent from '../app.tsx';
import './index.css';
import { Toaster } from '@client/src/components/ui/sonner';

const MainApp = () => (
  <BrowserRouter basename="/">
    <AppContainer defaultTheme="light">
      <ErrorBoundary fallbackRender={({ error, resetErrorBoundary }) => <ErrorRender error={error as Error} resetErrorBoundary={resetErrorBoundary} />}>
        <RoutesComponent />
        {createPortal(<Toaster />, document.body)}
      </ErrorBoundary>
    </AppContainer>
  </BrowserRouter>
);

createRoot(document.getElementById('root')!).render(<MainApp />);
