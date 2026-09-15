import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { fetchJob, deleteJob, createSSEConnection } from '../api'
import ManualClipPicker from './ManualClipPicker'

const STEPS = [
  { key: 'download', label: 'Download' },
  { key: 'transcribe', label: 'Transcribe' },
  { key: 'analyze', label: 'AI Analysis' },
  { key: 'metadata', label: 'Metadata' },
  { key: 'render', label: 'Render' },
  { key: 'done', label: 'Done' },
]

function JobDetail() {
  const { jobId } = useParams()
  const [job, setJob] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let sse = null

    const load = async () => {
      try {
        const data = await fetchJob(jobId)
        setJob(data)

        const terminal = ['completed', 'failed', 'cancelled']
        if (!terminal.includes(data.status)) {
          sse = createSSEConnection(jobId, (event) => {
            if (event.type === 'completed') {
              fetchJob(jobId).then(setJob)
            } else if (event.type === 'progress') {
              setJob(prev => prev ? { ...prev, status: event.status, progress: event.progress, error: event.error } : prev)
            }
          })
        }
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    load()
    return () => { if (sse) sse.close() }
  }, [jobId])

  // Also poll for updates
  useEffect(() => {
    if (!job) return
    const terminal = ['completed', 'failed', 'cancelled']
    if (terminal.includes(job.status)) return

    const interval = setInterval(async () => {
      try {
        const data = await fetchJob(jobId)
        setJob(data)
      } catch {}
    }, 3000)
    return () => clearInterval(interval)
  }, [jobId, job?.status])

  if (loading) return <div className="empty-state"><div className="spinner"></div></div>
  if (!job) return <div className="empty-state"><h3>Job not found</h3></div>

  const currentStep = job.progress?.step || ''
  const percent = job.progress?.percent || 0

  return (
    <div className="fade-in">
      <div className="page-header">
        <div>
          <h2>Job #{job.id}</h2>
          <p>{job.url || job.upload_filename || 'Unknown source'}</p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <span className={`badge badge-${job.status}`}>{job.status}</span>
          <Link to="/new" state={{ reuseJob: job }} className="btn btn-secondary btn-sm">🔁 Clone & Rerun</Link>
          <Link to="/" className="btn btn-ghost btn-sm">← Back</Link>
        </div>
      </div>

      {/* Progress */}
      {!['completed', 'failed', 'cancelled'].includes(job.status) && (
        <div className="card" style={{ marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '13px', fontWeight: 600 }}>Progress</span>
            <span style={{ fontSize: '13px', color: 'var(--accent-hover)' }}>{Math.round(percent)}%</span>
          </div>
          <div className="progress-bar-bg">
            <div className="progress-bar-fill" style={{ width: `${percent}%` }}></div>
          </div>
          {job.progress?.message && (
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '10px' }}>
              {job.progress.message}
            </p>
          )}
          <div className="progress-steps" style={{ marginTop: '14px' }}>
            {STEPS.map(s => {
              const stepIdx = STEPS.findIndex(x => x.key === s.key)
              const currentIdx = STEPS.findIndex(x => x.key === currentStep)
              let cls = ''
              if (stepIdx < currentIdx) cls = 'done'
              else if (stepIdx === currentIdx) cls = 'active'
              return (
                <div key={s.key} className={`progress-step ${cls}`}>
                  <span className="step-dot"></span>
                  {s.label}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Error */}
      {job.error && (
        <div className="card" style={{ marginBottom: '16px', borderColor: 'rgba(239,68,68,0.2)' }}>
          <h3 style={{ color: 'var(--error)', fontSize: '14px', marginBottom: '8px' }}>❌ Error</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{job.error}</p>
        </div>
      )}

      {/* Manual clip picker — shown once a download_only job has finished fetching the video */}
      {job.config?.mode === 'download_only' && job.status === 'completed' && job.source_video_url && (
        <ManualClipPicker job={job} />
      )}

      {/* Clips */}
      {job.clips && job.clips.length > 0 && (
        <>
          <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '16px' }}>
            🎞️ Generated Clips ({job.clips.length})
          </h3>
          <div className="clip-grid">
            {job.clips.map((clip, i) => (
              <div key={i} className="clip-card">
                <video className="clip-video" controls preload="metadata" src={clip.download_url} />
                <div className="clip-body">
                  <div className="clip-title">{clip.title || clip.title_en || `Clip ${clip.rank}`}</div>
                  <div className="clip-stats">
                    {clip.viral_score && <span className="viral-score">🔥 {clip.viral_score}</span>}
                    {clip.duration && <span>{Math.round(clip.duration)}s</span>}
                    <span>Rank #{clip.rank}</span>
                  </div>
                  <div className="clip-actions">
                    <a href={clip.download_url} download className="btn btn-secondary btn-sm">⬇️ Download</a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Log */}
      {job.log && job.log.length > 0 && (
        <div style={{ marginTop: '24px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 700, marginBottom: '10px' }}>📋 Activity Log</h3>
          <div className="log-viewer">
            {job.log.map((line, i) => <div key={i}>{line}</div>)}
          </div>
        </div>
      )}
    </div>
  )
}

export default JobDetail
