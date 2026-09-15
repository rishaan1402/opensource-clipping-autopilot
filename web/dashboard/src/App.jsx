import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import NewJob from './pages/NewJob'
import JobDetail from './pages/JobDetail'
import Settings from './pages/Settings'

function App() {
  const location = useLocation()

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>🎬 OSC Studio</h1>
          <p>AI Auto-Clipper v1.0.7</p>
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <span className="icon">📊</span>
            Dashboard
          </NavLink>
          <NavLink to="/new" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <span className="icon">➕</span>
            New Job
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <span className="icon">⚙️</span>
            Settings
          </NavLink>
        </nav>
        <div style={{ padding: '12px 14px', borderTop: '1px solid var(--border-color)' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            OpenSource Clipping
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewJob />} />
          <Route path="/job/:jobId" element={<JobDetail />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
