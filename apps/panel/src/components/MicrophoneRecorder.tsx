import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { encodeWav } from '../audioWav'
import { currentLocale, translate, useI18n } from '../i18n'

const SAMPLE_RATE = 16_000
const MAX_DURATION_MS = 119_000

async function asWav(blob: Blob): Promise<File> {
  const context = new AudioContext()
  let decoded: AudioBuffer
  try {
    decoded = await context.decodeAudioData(await blob.arrayBuffer())
  } finally {
    await context.close()
  }
  if (decoded.duration < 0.2 || decoded.duration > 120) {
    throw new Error(translate('录音时长需在 0.2–120 秒之间。', currentLocale()))
  }
  const frames = Math.ceil(decoded.duration * SAMPLE_RATE)
  const offline = new OfflineAudioContext(1, frames, SAMPLE_RATE)
  const source = offline.createBufferSource()
  source.buffer = decoded
  source.connect(offline.destination)
  source.start()
  const samples = (await offline.startRendering()).getChannelData(0)
  const wav = encodeWav(samples)
  return new File([wav], 'smartmed-recording.wav', { type: 'audio/wav' })
}

type Props = {
  disabled?: boolean
  onText: (text: string) => Promise<void> | void
  onActiveChange?: (active: boolean) => void
}

export function MicrophoneRecorder({ disabled = false, onText, onActiveChange }: Props) {
  const {t} = useI18n()
  const [phase, setPhase] = useState<'idle' | 'requesting' | 'recording' | 'processing'>('idle')
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState('')
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const timer = useRef<number | null>(null)
  const deadline = useRef<number | null>(null)
  const discarded = useRef(false)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      discarded.current = true
      if (timer.current !== null) window.clearInterval(timer.current)
      if (deadline.current !== null) window.clearTimeout(deadline.current)
      if (recorder.current?.state === 'recording') recorder.current.stop()
      stream.current?.getTracks().forEach(track => track.stop())
    }
  }, [])

  function release() {
    if (timer.current !== null) window.clearInterval(timer.current)
    if (deadline.current !== null) window.clearTimeout(deadline.current)
    timer.current = null
    deadline.current = null
    stream.current?.getTracks().forEach(track => track.stop())
    stream.current = null
    recorder.current = null
  }

  function stop(discard = false) {
    discarded.current = discard
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }

  async function start() {
    setError('')
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError(t('此浏览器不支持麦克风录音，请使用 WAV 上传。'))
      return
    }
    setPhase('requesting')
    onActiveChange?.(true)
    let acquired: MediaStream | null = null
    try {
      acquired = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!mounted.current) {
        acquired.getTracks().forEach(track => track.stop())
        return
      }
      const mediaRecorder = new MediaRecorder(acquired)
      const chunks: BlobPart[] = []
      stream.current = acquired
      recorder.current = mediaRecorder
      discarded.current = false
      mediaRecorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
      mediaRecorder.onerror = () => {
        discarded.current = true
        if (mounted.current) setError(t('录音失败，请检查麦克风权限后重试。'))
        stop(true)
      }
      mediaRecorder.onstop = async () => {
        release()
        if (!mounted.current) return
        if (discarded.current) {
          setPhase('idle')
          onActiveChange?.(false)
          return
        }
        setPhase('processing')
        try {
          const wav = await asWav(new Blob(chunks, { type: mediaRecorder.mimeType }))
          const result = await api.transcribe(wav)
          if (mounted.current) await onText(result.text)
        } catch (cause) {
          if (mounted.current) setError(cause instanceof Error ? cause.message : t('语音识别失败。'))
        } finally {
          if (mounted.current) {
            setPhase('idle')
            onActiveChange?.(false)
          }
        }
      }
      mediaRecorder.start()
      setSeconds(0)
      setPhase('recording')
      const started = Date.now()
      timer.current = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 500)
      deadline.current = window.setTimeout(() => stop(), MAX_DURATION_MS)
    } catch (cause) {
      acquired?.getTracks().forEach(track => track.stop())
      setPhase('idle')
      onActiveChange?.(false)
      setError(cause instanceof Error && cause.name === 'NotAllowedError'
        ? t('请允许浏览器访问麦克风。') : t('无法启动录音，请检查麦克风。'))
    }
  }

  return <div className="microphone-recorder">
    {phase === 'idle' && <button type="button" disabled={disabled} onClick={start}>{t('🎙 开始录音')}</button>}
    {phase === 'requesting' && <span role="status">{t('等待麦克风权限…')}</span>}
    {phase === 'recording' && <div className="recording-controls" role="status">
      <span className="recording-indicator">{t('● 录音中')} {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')} / 1:59</span>
      <button type="button" onClick={() => stop()}>{t('停止并识别')}</button>
      <button type="button" onClick={() => stop(true)}>{t('放弃')}</button>
    </div>}
    {phase === 'processing' && <span role="status">{t('正在识别并区分角色…')}</span>}
    {error && <p className="recording-error" role="alert">{error}</p>}
    <small>{t('录音在本机识别，角色由本地模型自动区分。请核对结果。')}</small>
  </div>
}
