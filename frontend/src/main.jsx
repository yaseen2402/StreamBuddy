import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import Terms from './pages/Terms.jsx'
import Privacy from './pages/Privacy.jsx'
import './index.css'

// Simple router based on pathname
function Router() {
  const path = window.location.pathname
  
  if (path === '/terms') {
    return <Terms />
  }
  
  if (path === '/privacy') {
    return <Privacy />
  }
  
  return <App />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Router />
  </React.StrictMode>,
)
