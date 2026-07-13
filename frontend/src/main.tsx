import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { WorkflowProvider } from './context/WorkflowContext';
import { AuthProvider } from './store/authStore';
import './styles/global.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <WorkflowProvider>
          <App />
        </WorkflowProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
