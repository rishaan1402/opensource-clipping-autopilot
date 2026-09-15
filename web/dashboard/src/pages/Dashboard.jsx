import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { fetchJobs, fetchHealth } from '../api'

const STATUS_LABELS = {
  queued: 'Queued',
  downloading: 'Downloading',
  transcribing: 'Transcribing',
  analyzing: 'Analyzing',
  rendering: 'Rendering',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

function formatDate(dateStr) {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return d.toLocaleString('id-ID', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function Dashboard() {
  const [jobs, setJobs] = useState([])
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadData = async () => {
    try {
      const [jobsData, healthData] = await Promise.all([
        fetchJobs(),
        fetchHealth(),
      ])
      setJobs(jobsData.jobs || [])
      setHealth(healthData)
    } catch (err) {
      console.error('Failed to load dashboard:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 5000) // Poll every 5s
    return () => clearInterval(interval)
  }, [])

  const totalCompleted = jobs.filter(j => j.status === 'completed').length
  const totalClips = jobs.reduce((acc, j) => acc + (j.clips?.length || 0), 0)
  const running = jobs.filter(j => !['completed', 'failed', 'cancelled'].includes(j.status)).length

  return (
    <div className="fade-in">
      <div className="page-header">
        <div>
          <h2>Dashboard</h2>
          <p>Overview semua clipping jobs</p>
        </div>
        <Link to="/new" className="btn btn-primary">
          ➕ New Job
        </Link>
      </div>

      {/* Stats Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '24px' }}>
        <div className="card">
          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' }}>Total Jobs</div>
          <div style={{ fontSize: '28px', fontWeight: 800, marginTop: '4px', background: 'linear-gradient(135deg, var(--accent), #c4b5fd)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>{jobs.length}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' }}>Completed</div>
          <div style={{ fontSize: '28px', fontWeight: 800, marginTop: '4px', color: 'var(--success)' }}>{totalCompleted}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' }}>Total Clips</div>
          <div style={{ fontSize: '28px', fontWeight: 800, marginTop: '4px', color: 'var(--accent-hover)' }}>{totalClips}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' }}>System</div>
          <div style={{ fontSize: '12px', marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <span style={{ color: health?.gpu_available ? 'var(--success)' : 'var(--text-tertiary)' }}>
              {health?.gpu_available ? '✅ GPU' : '⚪ CPU only'}
            </span>
            <span style={{ color: health?.ffmpeg_available ? 'var(--success)' : 'var(--error)' }}>
              {health?.ffmpeg_available ? '✅ FFmpeg' : '❌ FFmpeg'}
            </span>
          </div>
        </div>
      </div>

      {/* Job List */}
      {loading ? (
        <div className="empty-state">
          <div className="spinner"></div>
          <p style={{ marginTop: '12px' }}>Loading...</p>
        </div>
      ) : jobs.length === 0 ? (
        <div className="empty-state">
          <div className="icon">🎬</div>
          <h3>Belum ada job</h3>
          <p>Buat job pertama untuk memulai clipping video otomatis dengan AI.</p>
          <Link to="/new" className="btn btn-primary">➕ Create First Job</Link>
        </div>
      ) : (
        <div className="job-grid">
          {jobs.map(job => (
            <Link to={`/job/${job.id}`} key={job.id} className="job-card">
              <div className="job-info">
                <h3>
                  {job.url ? new URL(job.url).hostname.replace('www.', '') : job.upload_filename || 'Upload'}
                  {job.url && <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: '8px', fontSize: '12px' }}>#{job.id}</span>}
                </h3>
                <div className="job-meta">
                  <span>{formatDate(job.created_at)}</span>
                  {job.clips?.length > 0 && <span>🎞️ {job.clips.length} clips</span>}
                  {job.progress?.message && !['completed', 'failed'].includes(job.status) && (
                    <span style={{ color: 'var(--accent-hover)' }}>{job.progress.message}</span>
                  )}
                  {job.error && <span style={{ color: 'var(--error)' }}>⚠ Error</span>}
                </div>
              </div>
              <div>
                <span className={`badge badge-${job.status}`}>
                  {STATUS_LABELS[job.status] || job.status}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

export default Dashboard
