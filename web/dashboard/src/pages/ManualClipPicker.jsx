import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { createJob } from '../api'

function fmt(t) {
  if (t == null || Number.isNaN(t)) return '0:00.0'
  const m = Math.floor(t / 60)
  const s = (t % 60).toFixed(1)
  return `${m}:${s.padStart(4, '0')}`
}

function ManualClipPicker({ job }) {
  const navigate = useNavigate()
  const videoRef = useRef(null)

  const [segments, setSegments] = useState([])
  const [pendingStart, setPendingStart] = useState(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const duration = job.source_duration || videoRef.current?.duration || 0

  const handleTimeUpdate = () => {
    if (videoRef.current) setCurrentTime(videoRef.current.currentTime)
  }

  const seekTo = (t) => {
    if (videoRef.current) {
      videoRef.current.currentTime = t
      setCurrentTime(t)
    }
  }

  const markIn = () => setPendingStart(currentTime)

  const markOut = () => {
    if (pendingStart == null) {
      setError('Mark an in-point first.')
      return
    }
    if (currentTime <= pendingStart) {
      setError('Out-point must be after the in-point.')
      return
    }
    setSegments(prev => [
      ...prev,
      { id: Date.now(), start: pendingStart, end: currentTime, title: `Clip ${prev.length + 1}` },
    ])
    setPendingStart(null)
    setError('')
  }

  const removeSegment = (id) => setSegments(prev => prev.filter(s => s.id !== id))

  const updateSegment = (id, field, value) => {
    setSegments(prev => prev.map(s => s.id === id ? { ...s, [field]: value } : s))
  }

  const handleSubmit = async () => {
    if (segments.length === 0) {
      setError('Add at least one clip first.')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const config = job.config || {}
      const payload = {
        reuse_job_id: job.id,
        mode: 'manual',
        manual_segments: segments.map(s => ({
          start_time: Number(s.start.toFixed(2)),
          end_time: Number(s.end.toFixed(2)),
          title: s.title,
        })),
        ratio: config.ratio || '9:16',
        font_style: config.font_style || 'HORMOZI',
        whisper_model: config.whisper_model || 'large-v3',
        whisper_device: config.whisper_device || 'cuda',
        use_broll: config.use_broll ?? true,
        use_hook_glitch: config.use_hook_glitch ?? true,
        use_auto_bgm: config.use_auto_bgm ?? true,
        use_karaoke_effect: config.use_karaoke_effect ?? true,
        no_subs: config.no_subs ?? false,
        use_dlp_subs: config.use_dlp_subs ?? false,
      }
      const newJob = await createJob(payload)
      navigate(`/job/${newJob.id}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card" style={{ marginBottom: '16px' }}>
      <h3 className="card-title" style={{ marginBottom: '12px' }}>✋ Pick Your Clip Timestamps</h3>
      <p className="form-hint" style={{ marginBottom: '16px' }}>
        Scrub the video, hit "Mark In" and "Mark Out" to capture a clip window, repeat for as many clips as you want, then render.
      </p>

      <video
        ref={videoRef}
        src={job.source_video_url}
        controls
        preload="metadata"
        onTimeUpdate={handleTimeUpdate}
        style={{ width: '100%', maxHeight: '420px', borderRadius: 'var(--radius-md)', background: '#000' }}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '12px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '13px', fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
          {fmt(currentTime)} {duration ? `/ ${fmt(duration)}` : ''}
        </span>
        <button type="button" className="btn btn-secondary btn-sm" onClick={markIn}>
          ⏱️ Mark In {pendingStart != null && `(${fmt(pendingStart)})`}
        </button>
        <button type="button" className="btn btn-primary btn-sm" onClick={markOut} disabled={pendingStart == null}>
          ✂️ Mark Out → Add Clip
        </button>
        {pendingStart != null && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPendingStart(null)}>
            Cancel in-point
          </button>
        )}
      </div>

      {error && (
        <div style={{ background: 'var(--error-dim)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--radius-md)', padding: '10px 14px', marginTop: '12px', color: 'var(--error)', fontSize: '13px' }}>
          ⚠️ {error}
        </div>
      )}

      {segments.length > 0 && (
        <div style={{ marginTop: '20px' }}>
          <h4 style={{ fontSize: '13px', fontWeight: 700, marginBottom: '10px' }}>
            Segments ({segments.length})
          </h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {segments.map(s => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', padding: '8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
                <input
                  className="form-input"
                  style={{ maxWidth: '160px' }}
                  value={s.title}
                  onChange={(e) => updateSegment(s.id, 'title', e.target.value)}
                />
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => seekTo(s.start)}>
                  ▶ {fmt(s.start)}
                </button>
                <span style={{ color: 'var(--text-secondary)' }}>→</span>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => seekTo(s.end)}>
                  {fmt(s.end)}
                </button>
                <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  ({(s.end - s.start).toFixed(1)}s)
                </span>
                <button type="button" className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto', color: 'var(--error)' }} onClick={() => removeSegment(s.id)}>
                  🗑️
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <button
        type="button"
        className="btn btn-primary"
        disabled={submitting || segments.length === 0}
        onClick={handleSubmit}
        style={{ marginTop: '20px', fontSize: '14px', padding: '12px 28px' }}
      >
        {submitting ? <><span className="spinner"></span> Rendering...</> : `🚀 Render ${segments.length || ''} Clip${segments.length === 1 ? '' : 's'}`}
      </button>
    </div>
  )
}

export default ManualClipPicker
