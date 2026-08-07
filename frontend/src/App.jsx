import { useState, useEffect, useRef, useCallback } from 'react'
import Orb from './components/Orb.jsx'

const WS_URL   = 'ws://localhost:8000/ws'
const SLEEP_MS = 5 * 60 * 1000
const COMMAND_INACTIVITY_MS = 10 * 1000
const WAKE_WORD_RE = /\b(jarvis|jervis|jar\s*vess|jarves)\b/i
const STOP_LISTENING_RE = /^\s*(stop|stop listening|go to sleep|sleep|stand by|standby|pause listening)\s*[.!?]?\s*$/i

const DEFAULT_STATS = { active_model: '—', prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, daily_limit: 100000 }

export default function App() {
  const [orbState, setOrbState]     = useState('idle')
  const [statusText, setStatusText] = useState('Connecting...')
  const [messages, setMessages]     = useState([])
  const [connected, setConnected]   = useState(false)
  const [activated, setActivated]   = useState(() => localStorage.getItem('jarvis_activated') === '1')
  const [audioUnlocked, setAudioUnlocked] = useState(false)
  const [asleep, setAsleep]         = useState(false)
  const [voiceMode, setVoiceMode]   = useState('wake')
  const [transcript, setTranscript] = useState('')
  const [typedCommand, setTypedCommand] = useState('')
  const [screenContent, setScreenContent] = useState(null)
  const [stats, setStats]           = useState(DEFAULT_STATS)
  const audioCtxRef = useRef(null)

  const wsRef           = useRef(null)
  const recognitionRef  = useRef(null)
  const audioRef        = useRef(null)
  const mediaRecorderRef = useRef(null)
  const micStreamRef    = useRef(null)
  const sttAudioCtxRef  = useRef(null)
  const analyserFrameRef = useRef(null)
  const headerChunkRef = useRef(null)
  const preRollChunksRef = useRef([])
  const utteranceChunksRef = useRef([])
  const recordingSpeechRef = useRef(false)
  const silenceStartRef = useRef(null)
  const speechStartRef  = useRef(null)
  const discardRecordingRef = useRef(true)
  const listeningRef    = useRef(false)
  const speakingRef     = useRef(false)
  const processingRef   = useRef(false)
  const shouldListenRef = useRef(false)
  const sleepTimerRef   = useRef(null)
  const commandInactivityRef = useRef(null)
  const voiceModeRef    = useRef('wake')
  const asleepRef       = useRef(false)
  const messagesEndRef  = useRef(null)
  const extensionCommandSeqRef = useRef(0)
  const reconnectTimerRef = useRef(null)
  const wsClosedByUsRef = useRef(false)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    const fetchStats = () =>
      fetch('http://localhost:8000/stats')
        .then(r => r.json())
        .then(d => { if (d.active_model) setStats(d) })
        .catch(() => {})
    fetchStats()
    const id = setInterval(fetchStats, 5000)
    return () => clearInterval(id)
  }, [])

  const unlockAudio = useCallback(() => {
    if (audioCtxRef.current) return
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const buf = ctx.createBuffer(1, 1, 22050)
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.connect(ctx.destination)
    src.start(0)
    audioCtxRef.current = ctx
    setAudioUnlocked(true)
  }, [])

  // Synthesized power-up arpeggio — no audio asset needed
  const playBootChime = useCallback(() => {
    const ctx = audioCtxRef.current
    if (!ctx) return
    const now = ctx.currentTime
    const notes = [392.0, 523.25, 659.25, 783.99] // G4 C5 E5 G5
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'triangle'
      osc.frequency.value = freq
      const t = now + i * 0.09
      gain.gain.setValueAtTime(0.0001, t)
      gain.gain.exponentialRampToValueAtTime(0.16, t + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(t)
      osc.stop(t + 0.4)
    })
  }, [])

  const ensureMicrophoneAccess = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) return true
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach(t => t.stop())
      return true
    } catch {
      shouldListenRef.current = false
      setOrbState('error')
      setStatusText('Microphone blocked')
      return false
    }
  }, [])

  const goToSleep = useCallback(() => {
    asleepRef.current = true
    setAsleep(true)
    shouldListenRef.current = false
    stopListening()
    setOrbState('sleep')
    setStatusText('Sleeping...')
    clearTimeout(sleepTimerRef.current)
  }, [])

  // Re-arm the auto-sleep countdown on every activity signal
  const resetSleepTimer = useCallback(() => {
    clearTimeout(sleepTimerRef.current)
    sleepTimerRef.current = setTimeout(goToSleep, SLEEP_MS)
  }, [goToSleep])

  const wakeUp = useCallback(() => {
    if (!asleepRef.current) return
    asleepRef.current = false
    setAsleep(false)
    setOrbState('idle')
    shouldListenRef.current = true
    resetSleepTimer()
    setTimeout(() => startListening(), 200)
  }, [resetSleepTimer])

  const clearCommandInactivity = useCallback(() => {
    clearTimeout(commandInactivityRef.current)
    commandInactivityRef.current = null
  }, [])

  const enterWakeMode = useCallback((message = 'Waiting for "Jarvis"...') => {
    clearCommandInactivity()
    voiceModeRef.current = 'wake'
    setVoiceMode('wake')
    shouldListenRef.current = true
    processingRef.current = false
    asleepRef.current = false
    setAsleep(false)
    setTranscript('')
    setOrbState('idle')
    setStatusText(message)
    stopListening()
    setTimeout(() => startListening(), 250)
  }, [clearCommandInactivity])

  const armCommandInactivity = useCallback(() => {
    clearCommandInactivity()
    commandInactivityRef.current = setTimeout(() => {
      enterWakeMode('Timed out. Waiting for "Jarvis"...')
    }, COMMAND_INACTIVITY_MS)
  }, [clearCommandInactivity, enterWakeMode])

  const enterCommandMode = useCallback((message = 'Yes, sir. Listening...') => {
    voiceModeRef.current = 'command'
    setVoiceMode('command')
    shouldListenRef.current = true
    processingRef.current = false
    asleepRef.current = false
    setAsleep(false)
    setTranscript('')
    setOrbState('listening')
    setStatusText(message)
    armCommandInactivity()
    stopListening()
    setTimeout(() => startListening(), 250)
  }, [armCommandInactivity])

  const commandAfterWakeWord = useCallback((text) => {
    const match = WAKE_WORD_RE.exec(text || '')
    if (!match) return null
    return (text.slice(match.index + match[0].length) || '').trim().replace(/^[.,:;!?-]+/, '').trim()
  }, [])

  const runExtensionCommand = useCallback((target, command) => {
    const commandId = `ext-${Date.now()}-${extensionCommandSeqRef.current++}`
    return new Promise((resolve) => {
      const onMessage = (event) => {
        const data = event.data
        if (!data || data.type !== 'JARVIS_EXTENSION_RESULT' || data.commandId !== commandId) return
        window.clearTimeout(timeoutId)
        window.removeEventListener('message', onMessage)
        resolve({ ok: Boolean(data.ok), text: data.text || 'Extension finished.', status: data.status || 'done', details: data.details || null })
      }
      const timeoutId = window.setTimeout(() => {
        window.removeEventListener('message', onMessage)
        resolve({ ok: false, text: `The ${target} extension did not respond.`, status: 'error', details: null })
      }, 15000)
      window.addEventListener('message', onMessage)
      window.postMessage({ type: 'JARVIS_EXTENSION_COMMAND', target, command, commandId }, '*')
    })
  }, [])

  const connectWS = useCallback(() => {
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws
    ws.onopen = () => { setConnected(true); setStatusText('Click anywhere to activate') }
    ws.onclose = () => {
      setConnected(false)
      setStatusText('Server offline')
      // Don't reconnect after unmount — that leaked sockets on every hot-reload
      if (!wsClosedByUsRef.current) reconnectTimerRef.current = setTimeout(connectWS, 3000)
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'thinking')      { setOrbState('thinking'); setStatusText('Thinking...') }
      if (data.type === 'status')        { setStatusText(data.message) }
      if (data.type === 'response')      { resetSleepTimer(); setMessages(prev => [...prev, { role: 'jarvis', text: data.text }]) }
      if (data.type === 'user_transcript') { setTranscript(''); setMessages(prev => [...prev, { role: 'user', text: data.text }]) }
      if (data.type === 'stt_empty') {
        processingRef.current = false
        setTranscript('')
        setOrbState(voiceModeRef.current === 'wake' ? 'idle' : 'listening')
        setStatusText(data.message || (voiceModeRef.current === 'wake' ? 'Waiting for "Jarvis"...' : 'Listening...'))
        if (shouldListenRef.current && !speakingRef.current) setTimeout(() => startListening(), 250)
        return
      }
      if (data.type === 'wake_detected') {
        processingRef.current = false
        const command = (data.command || '').trim()
        if (command) {
          voiceModeRef.current = 'command'
          setVoiceMode('command')
          clearCommandInactivity()
          setTranscript('')
          setMessages(prev => [...prev, { role: 'user', text: command }])
          processingRef.current = true
          setOrbState('thinking')
          setStatusText('Thinking...')
          wsRef.current?.send(JSON.stringify({ type: 'transcript', text: command }))
        } else {
          enterCommandMode('Yes, sir. Listening...')
        }
        return
      }
      if (data.type === 'sleep_listening') {
        enterWakeMode(data.message || 'Standing by. Say "Jarvis" to wake me.')
        return
      }
      if (data.type === 'screen_display') {
        data.content_type === 'close' ? setScreenContent(null) : setScreenContent(data)
        return
      }
      if (data.type === 'wake') {
        if (asleepRef.current) wakeUp()
        else if (!listeningRef.current && !speakingRef.current && !processingRef.current) {
          shouldListenRef.current = true
          startListening()
        }
        return
      }
      if (data.type === 'extension_command') {
        setOrbState('thinking'); setStatusText('Running extension...')
        runExtensionCommand(data.target, data.command).then((result) => {
          wsRef.current?.send(JSON.stringify({ type: 'extension_result', target: data.target, text: result.text, status: result.status || (result.ok ? 'done' : 'error') }))
        })
        return
      }
      if (data.type === 'audio') {
        processingRef.current = false
        speakingRef.current   = true
        setOrbState('speaking')
        setStatusText('Speaking...')
        stopListening()
        const blob  = b64ToBlob(data.data, 'audio/mpeg')
        const url   = URL.createObjectURL(blob)
        const audio = new Audio(url)
        audioRef.current = audio
        audio.onended = () => {
          URL.revokeObjectURL(url)
          speakingRef.current = false
          if (voiceModeRef.current === 'command') {
            setOrbState('listening')
            setStatusText('Listening...')
            armCommandInactivity()
          } else {
            setOrbState('idle')
            setStatusText('Waiting for "Jarvis"...')
          }
          if (shouldListenRef.current) setTimeout(() => startListening(), 300)
        }
        audio.play().catch(() => { speakingRef.current = false; if (shouldListenRef.current) startListening() })
      }
    }
  }, [])

  useEffect(() => {
    wsClosedByUsRef.current = false
    connectWS()
    return () => {
      wsClosedByUsRef.current = true
      clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
    }
  }, [connectWS])

  const initRecognition = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { setStatusText('Use Google Chrome for voice'); return null }
    const r = new SR()
    r.continuous = true; r.interimResults = true; r.lang = 'en-US'; r.maxAlternatives = 1
    r.onresult = (e) => {
      if (speakingRef.current || processingRef.current) return
      let interim = '', final = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript
        e.results[i].isFinal ? (final += t) : (interim += t)
      }
      if (interim) setTranscript(interim)
      if (final.trim()) {
        setTranscript('')
        const text = final.trim()
        if (voiceModeRef.current === 'wake') {
          const command = commandAfterWakeWord(text)
          if (command === null) {
            setOrbState('idle')
            setStatusText('Waiting for "Jarvis"...')
            return
          }
          if (!command) {
            enterCommandMode('Yes, sir. Listening...')
            return
          }
          voiceModeRef.current = 'command'
          setVoiceMode('command')
          clearCommandInactivity()
          setMessages(prev => [...prev, { role: 'user', text: command }])
          processingRef.current = true
          setOrbState('thinking')
          setStatusText('Thinking...')
          wsRef.current?.send(JSON.stringify({ type: 'transcript', text: command }))
          return
        }
        if (STOP_LISTENING_RE.test(text)) {
          enterWakeMode('Standing by. Say "Jarvis" to wake me.')
          return
        }
        resetSleepTimer()
        clearCommandInactivity()
        setMessages(prev => [...prev, { role: 'user', text }])
        processingRef.current = true
        setOrbState('thinking')
        setStatusText('Thinking...')
        wsRef.current?.send(JSON.stringify({ type: 'transcript', text }))
      }
    }
    r.onstart = () => { listeningRef.current = true }
    r.onend   = () => {
      listeningRef.current = false
      if (shouldListenRef.current && !speakingRef.current && !processingRef.current)
        setTimeout(() => startListening(), 200)
    }
    r.onerror = (e) => {
      if (e.error === 'aborted' || e.error === 'no-speech') return
      shouldListenRef.current = false
      setOrbState('error')
      setStatusText(
        e.error === 'not-allowed'
          ? 'Microphone blocked'
          : e.error === 'audio-capture'
            ? 'No mic detected'
            : e.error === 'network'
              ? 'Speech network error - type below'
              : `Error: ${e.error}`
      )
    }
    recognitionRef.current = r
    return r
  }, [])

  const cleanupServerListening = useCallback(() => {
    if (analyserFrameRef.current) cancelAnimationFrame(analyserFrameRef.current)
    analyserFrameRef.current = null
    micStreamRef.current?.getTracks().forEach(t => t.stop())
    micStreamRef.current = null
    sttAudioCtxRef.current?.close().catch(() => {})
    sttAudioCtxRef.current = null
    mediaRecorderRef.current = null
    headerChunkRef.current = null
    preRollChunksRef.current = []
    utteranceChunksRef.current = []
    recordingSpeechRef.current = false
    silenceStartRef.current = null
    speechStartRef.current = null
    listeningRef.current = false
  }, [])

  const sendAudioForTranscription = useCallback(async (chunks, mime) => {
    if (!chunks.length || wsRef.current?.readyState !== WebSocket.OPEN) return
    const blob = new Blob(chunks, { type: mime || 'audio/webm' })
    const mode = voiceModeRef.current
    if (blob.size < (mode === 'wake' ? 500 : 1500)) return
    processingRef.current = true
    if (mode === 'wake') {
      setOrbState('idle')
      setStatusText('Checking wake word...')
    } else {
      clearCommandInactivity()
      setOrbState('thinking')
      setStatusText('Transcribing...')
    }
    const data = await blobToBase64(blob)
    wsRef.current?.send(JSON.stringify({ type: 'audio_transcript', mode, mime: blob.type, data }))
  }, [clearCommandInactivity])

  const stopServerListening = useCallback((discard = true) => {
    discardRecordingRef.current = discard
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      try { recorder.stop() } catch {}
    } else {
      cleanupServerListening()
    }
  }, [cleanupServerListening])

  const startServerListening = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') return false
    if (listeningRef.current || speakingRef.current || processingRef.current) return true

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const ctx = new (window.AudioContext || window.webkitAudioContext)()
      const source = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 1024
      source.connect(analyser)

      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm'
      const recorder = new MediaRecorder(stream, { mimeType: mime })
      const samples = new Uint8Array(analyser.fftSize)

      micStreamRef.current = stream
      sttAudioCtxRef.current = ctx
      mediaRecorderRef.current = recorder
      listeningRef.current = true
      discardRecordingRef.current = true
      setOrbState(voiceModeRef.current === 'wake' ? 'idle' : 'listening')
      setStatusText(voiceModeRef.current === 'wake' ? 'Waiting for "Jarvis"...' : 'Listening...')

      recorder.ondataavailable = (event) => {
        if (!event.data?.size) return
        if (!headerChunkRef.current) headerChunkRef.current = event.data
        preRollChunksRef.current.push(event.data)
        if (preRollChunksRef.current.length > 5) preRollChunksRef.current.shift()
        if (recordingSpeechRef.current) utteranceChunksRef.current.push(event.data)
      }

      recorder.onstop = () => {
        const discard = discardRecordingRef.current
        const chunks = utteranceChunksRef.current.slice()
        const recordingMime = recorder.mimeType
        cleanupServerListening()
        if (!discard) sendAudioForTranscription(chunks, recordingMime)
      }

      recorder.start(250)

      const tick = () => {
        if (!mediaRecorderRef.current || mediaRecorderRef.current.state === 'inactive') return
        analyser.getByteTimeDomainData(samples)
        let sum = 0
        for (const value of samples) {
          const centered = (value - 128) / 128
          sum += centered * centered
        }
        const rms = Math.sqrt(sum / samples.length)
        const now = performance.now()
        const hasSpeech = rms > (voiceModeRef.current === 'wake' ? 0.018 : 0.025)

        if (hasSpeech) {
          silenceStartRef.current = null
          if (!recordingSpeechRef.current) {
            recordingSpeechRef.current = true
            speechStartRef.current = now
            utteranceChunksRef.current = [
              headerChunkRef.current,
              ...preRollChunksRef.current.filter(chunk => chunk !== headerChunkRef.current),
            ].filter(Boolean)
            setTranscript('Listening...')
          }
        } else if (recordingSpeechRef.current) {
          if (!silenceStartRef.current) silenceStartRef.current = now
          const silentFor = now - silenceStartRef.current
          const utteranceFor = now - (speechStartRef.current || now)
          if (silentFor > 950 || utteranceFor > 12000) {
            setTranscript('')
            stopServerListening(false)
            return
          }
        }

        analyserFrameRef.current = requestAnimationFrame(tick)
      }

      analyserFrameRef.current = requestAnimationFrame(tick)
      return true
    } catch {
      cleanupServerListening()
      setOrbState('error')
      setStatusText('Microphone blocked')
      return true
    }
  }, [cleanupServerListening, sendAudioForTranscription, stopServerListening])

  const startListening = useCallback(async () => {
    if (listeningRef.current || speakingRef.current || processingRef.current) return
    const usingServerStt = await startServerListening()
    if (usingServerStt) return
    if (!recognitionRef.current) initRecognition()
    try {
      recognitionRef.current?.start()
      setOrbState(voiceModeRef.current === 'wake' ? 'idle' : 'listening')
      setStatusText(voiceModeRef.current === 'wake' ? 'Waiting for "Jarvis"...' : 'Listening...')
    } catch {}
  }, [initRecognition, startServerListening])

  const stopListening = useCallback(() => {
    stopServerListening(true)
    try { recognitionRef.current?.stop() } catch {}
    listeningRef.current = false
  }, [stopServerListening])

  const submitCommand = useCallback((event) => {
    event.preventDefault()
    const text = typedCommand.trim()
    if (!text || !connected) return
    setTypedCommand('')
    resetSleepTimer()
    setMessages(prev => [...prev, { role: 'user', text }])
    processingRef.current = true
    setOrbState('thinking')
    setStatusText('Thinking...')
    wsRef.current?.send(JSON.stringify({ type: 'transcript', text }))
  }, [connected, resetSleepTimer, typedCommand])

  useEffect(() => {
    const onFocus = () => { if (asleepRef.current) wakeUp() }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [wakeUp])

  const activate = useCallback(async () => {
    if (activated) return
    unlockAudio()
    playBootChime()
    const allowed = await ensureMicrophoneAccess()
    if (!allowed) return
    setActivated(true)
    localStorage.setItem('jarvis_activated', '1')
    initRecognition()
    voiceModeRef.current = 'wake'
    setVoiceMode('wake')
    shouldListenRef.current = true
    asleepRef.current = false
    resetSleepTimer()
    startListening()
  }, [activated, ensureMicrophoneAccess, unlockAudio, playBootChime, initRecognition, startListening, resetSleepTimer])

  useEffect(() => {
    if (!(activated && connected)) return
    let cancelled = false
    ;(async () => {
      const allowed = await ensureMicrophoneAccess()
      if (!allowed || cancelled) return
      initRecognition()
      voiceModeRef.current = 'wake'
      setVoiceMode('wake')
      shouldListenRef.current = true
      asleepRef.current = false
      resetSleepTimer()
      setTimeout(() => { if (!cancelled) startListening() }, 500)
    })()
    return () => { cancelled = true }
  }, [activated, connected, ensureMicrophoneAccess, initRecognition, resetSleepTimer, startListening])

  const interruptSpeech = useCallback(() => {
    if (!speakingRef.current) return
    audioRef.current?.pause()
    speakingRef.current = false
    setOrbState('listening')
    setStatusText('Listening...')
    if (shouldListenRef.current) setTimeout(() => startListening(), 200)
  }, [startListening])

  const handleOrbClick = useCallback(() => {
    unlockAudio()
    if (!activated) { activate(); return }
    if (asleepRef.current) { wakeUp(); return }
    interruptSpeech()
  }, [activated, activate, wakeUp, interruptSpeech, unlockAudio])

  // Press Escape to cut Jarvis off mid-sentence
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') interruptSpeech() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [interruptSpeech])

  const needsAudioUnlock = activated && !audioUnlocked
  const pct = Math.min((stats.total_tokens / stats.daily_limit) * 100, 100)
  const barColor = stats.total_tokens > 80000 ? '#ef4444' : stats.total_tokens > 50000 ? '#f59e0b' : '#00d4ff'

  const stateLabel = {
    idle:      voiceMode === 'wake' ? 'WAKE WORD ARMED' : 'STANDBY',
    listening: transcript ? `"${transcript}"` : 'LISTENING',
    thinking:  statusText.toUpperCase(),
    speaking:  'SPEAKING',
    sleep:     'OFFLINE — CTRL+ALT+SPACE TO WAKE',
    error:     statusText.toUpperCase(),
  }

  return (
    <div
      className={`app${asleep ? ' sleeping' : ''}`}
      onClick={!activated ? activate : asleep ? () => { unlockAudio(); wakeUp() } : unlockAudio}
    >
      {/* Scanline overlay */}
      <div className="scanline" />

      {/* Header */}
      <div className="header">
        <div className="header-left">
          <div className="logo">J.A.R.V.I.S.</div>
          <div className="logo-sub">JUST A RATHER VERY INTELLIGENT SYSTEM</div>
        </div>
        <div className="header-right">
          {activated && audioUnlocked && (
            <div className={`mic-badge mode-${voiceMode}`}><span className="mic-dot" />{voiceMode === 'wake' ? 'WAKE WORD' : 'LIVE MIC'}</div>
          )}
          <div className="conn-indicator">
            <div className={`status-dot ${connected ? 'online' : 'offline'}`} />
            <span className="conn-label">{connected ? 'ONLINE' : 'OFFLINE'}</span>
          </div>
        </div>
      </div>

      {/* System dashboard — always visible */}
      <div className="hud-panel token-dashboard">
        <div className="hud-corner tl"/><div className="hud-corner tr"/>
        <div className="hud-corner bl"/><div className="hud-corner br"/>
        <div className="dash-section">
          <div className="dash-key">NEURAL CORE</div>
          <div className="dash-val model-name">{stats.active_model.split('/').pop()}</div>
        </div>
        <div className="dash-divider"/>
        <div className="dash-section">
          <div className="dash-key">TOKENS IN</div>
          <div className="dash-val">{stats.prompt_tokens.toLocaleString()}</div>
        </div>
        <div className="dash-section">
          <div className="dash-key">TOKENS OUT</div>
          <div className="dash-val">{stats.completion_tokens.toLocaleString()}</div>
        </div>
        <div className="dash-divider"/>
        <div className="dash-section quota-section">
          <div className="dash-key">DAILY QUOTA</div>
          <div className="quota-bar-row">
            <div className="quota-track">
              <div className="quota-fill" style={{ width: `${pct}%`, background: barColor, boxShadow: `0 0 6px ${barColor}` }}/>
            </div>
            <div className="dash-val quota-num">{stats.total_tokens.toLocaleString()} <span className="quota-sep">/</span> {stats.daily_limit.toLocaleString()}</div>
          </div>
        </div>
      </div>

      {/* First-ever activation overlay */}
      {!activated && (
        <div className="activate-overlay">
          <div className="activate-rings">
            <div className="ring r1"/><div className="ring r2"/><div className="ring r3"/>
          </div>
          <div className="activate-text">CLICK TO INITIALIZE</div>
          <div className="activate-sub">MICROPHONE ACCESS REQUIRED</div>
        </div>
      )}

      {needsAudioUnlock && (
        <div className="unlock-banner" onClick={unlockAudio}>
          ▶ CLICK TO ENABLE AUDIO OUTPUT
        </div>
      )}

      {/* Orb */}
      <div className="orb-area">
        <div className="orb-frame">
          <div className="orb-ring orb-ring-1"/>
          <div className="orb-ring orb-ring-2"/>
          <Orb state={orbState} onClick={handleOrbClick} />
        </div>
        <div className={`status-label state-${orbState}`}>
          {stateLabel[orbState] || statusText.toUpperCase()}
        </div>
        {orbState === 'speaking' && <div className="hint">[ CLICK ORB TO INTERRUPT ]</div>}
      </div>

      {activated && (
        <form className="command-bar" onSubmit={submitCommand} onClick={(e) => e.stopPropagation()}>
          <input
            value={typedCommand}
            onChange={(e) => setTypedCommand(e.target.value)}
            placeholder="TYPE COMMAND"
            disabled={!connected}
            aria-label="Type command"
          />
          <button type="submit" disabled={!connected || !typedCommand.trim()}>SEND</button>
        </form>
      )}

      {/* Chat log */}
      {messages.length > 0 && (
        <div className="hud-panel chat-log">
          <div className="hud-corner tl"/><div className="hud-corner tr"/>
          <div className="hud-corner bl"/><div className="hud-corner br"/>
          <div className="chat-log-header">COMMS LOG</div>
          {messages.map((m, i) => (
            <div key={i} className={`message ${m.role}`}>
              <span className="msg-label">{m.role === 'user' ? '▸ YOU' : '▸ JARVIS'}</span>
              <span className="msg-text">{m.text}</span>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      )}

      {/* Screen panel */}
      {screenContent && (
        <div className={`screen-panel ${screenContent.content_type === 'mails_list' ? 'mail-screen' : ''}`}>
          <div className="hud-corner tl"/><div className="hud-corner tr"/>
          <div className="hud-corner bl"/><div className="hud-corner br"/>
          <div className="screen-panel-header">
            <span className="screen-panel-title">
              {screenContent.content_type === 'map'      ? '— NAVIGATION —' :
               screenContent.content_type === 'email'    ? '— SECURE MESSAGE —' :
               screenContent.content_type === 'calendar' ? `— ${screenContent.data.label || 'SCHEDULE'} —` :
                                                           '— INBOX —'}
            </span>
            <button className="screen-close-btn" onClick={() => setScreenContent(null)}>✕</button>
          </div>
          {screenContent.content_type === 'map'        && <MapPanel       data={screenContent.data} />}
          {screenContent.content_type === 'email'      && <EmailPanel     data={screenContent.data} />}
          {screenContent.content_type === 'mails_list' && <MailsListPanel data={screenContent.data} />}
          {screenContent.content_type === 'calendar'   && <CalendarPanel  data={screenContent.data} />}
        </div>
      )}
    </div>
  )
}

// ── Screen sub-components ─────────────────────────────────────────────────────

function MapPanel({ data }) {
  return (
    <div className="map-panel">
      <div className="map-route-info">
        <div className="map-endpoint">
          <span className="map-label">ORIGIN</span>
          <span className="map-place">{data.origin}</span>
        </div>
        <div className="map-arrow">↓</div>
        <div className="map-endpoint">
          <span className="map-label">DESTINATION</span>
          <span className="map-place">{data.destination}</span>
        </div>
      </div>
      <iframe className="map-frame" src={data.embed_url} allowFullScreen loading="lazy" referrerPolicy="no-referrer-when-downgrade" title="Directions" />
      <a href={data.maps_url} target="_blank" rel="noopener noreferrer" className="map-link-btn">↗ OPEN IN GOOGLE MAPS</a>
    </div>
  )
}

function EmailPanel({ data }) {
  return (
    <div className="email-panel">
      <div className="email-meta">
        <div className="email-field"><span className="email-label">FROM</span><span className="email-value">{data.sender}</span></div>
        <div className="email-field"><span className="email-label">SUBJECT</span><span className="email-value">{data.subject}</span></div>
        <div className="email-field"><span className="email-label">DATE</span><span className="email-value">{data.date}</span></div>
      </div>
      <div className="email-body">{data.body}</div>
    </div>
  )
}

function MailsListPanel({ data }) {
  const mails = data.mails || []
  const label = data.query || 'recent inbox'
  const unreadCount = mails.filter((mail) => mail.unread).length
  const cleanSender = (sender = '') => sender.replace(/<[^>]+>/g, '').replace(/"/g, '').trim() || 'Unknown sender'
  const cleanSnippet = (snippet = '') => snippet.replace(/\s+/g, ' ').trim()

  return (
    <div className="gmail-shell">
      <aside className="gmail-sidebar">
        <button className="gmail-compose">Compose</button>
        <div className="gmail-nav-item active"><span>Inbox</span><b>{mails.length}</b></div>
        <div className="gmail-nav-item"><span>Starred</span></div>
        <div className="gmail-nav-item"><span>Snoozed</span></div>
        <div className="gmail-nav-item"><span>Sent</span></div>
      </aside>

      <section className="gmail-main">
        <div className="gmail-toolbar">
          <div className="gmail-toolbar-left">
            <span className="gmail-checkbox" />
            <span className="gmail-refresh">Refresh</span>
            <span className="gmail-label">{label}</span>
          </div>
          <div className="gmail-toolbar-right">
            <span>{mails.length ? `1-${mails.length}` : '0'} of {mails.length}</span>
            {unreadCount > 0 && <span className="gmail-unread-pill">{unreadCount} unread</span>}
          </div>
        </div>

        <div className="gmail-tabs">
          <div className="gmail-tab active">Primary</div>
          <div className="gmail-tab">Promotions</div>
          <div className="gmail-tab">Updates</div>
        </div>

        <div className="gmail-list">
          {mails.map((mail, i) => (
            <div key={mail.id} className={`gmail-row ${mail.unread ? 'unread' : ''}`}>
              <div className="gmail-row-controls">
                <span className="gmail-checkbox" />
                <span className="gmail-star">*</span>
                <span className="gmail-index">{i + 1}</span>
              </div>
              <div className="gmail-sender">{cleanSender(mail.sender)}</div>
              <div className="gmail-message">
                <span className="gmail-subject">{mail.subject || '(no subject)'}</span>
                {mail.snippet && <span className="gmail-snippet"> - {cleanSnippet(mail.snippet)}</span>}
              </div>
              <div className="gmail-date">{mail.date_label || ''}</div>
            </div>
          ))}
          {mails.length === 0 && <div className="gmail-empty">No messages in this view.</div>}
        </div>
      </section>
    </div>
  )
}

function CalendarPanel({ data }) {
  const events = data.events || []
  if (events.length === 0) return <div className="calendar-empty">NO EVENTS SCHEDULED</div>
  const groups = {}
  for (const e of events) {
    const key = e.label || 'UPCOMING'
    if (!groups[key]) groups[key] = []
    groups[key].push(e)
  }
  return (
    <div className="calendar-panel">
      {Object.entries(groups).map(([label, evts]) => (
        <div key={label} className="cal-group">
          <div className="cal-group-label">{label}</div>
          {evts.map(e => (
            <div key={e.id} className="cal-event">
              <div className="cal-event-time">{e.all_day ? 'ALL DAY' : (e.time_start || '—')}</div>
              <div className="cal-event-info">
                <div className="cal-event-title">{e.title}</div>
                {e.location && <div className="cal-event-loc">{e.location}</div>}
                {e.link && <a href={e.link} target="_blank" rel="noopener noreferrer" className="cal-event-link">↗ JOIN</a>}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function b64ToBlob(b64, mime) {
  const bytes = atob(b64)
  const arr = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
  return new Blob([arr], { type: mime })
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onloadend = () => resolve(String(reader.result || '').split(',')[1] || '')
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}
