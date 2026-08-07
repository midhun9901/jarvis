import { useEffect, useRef } from 'react'

export default function Orb({ state, onClick }) {
  const canvasRef = useRef(null)
  const animRef = useRef(null)
  const particlesRef = useRef([])
  const stateRef = useRef(state)

  useEffect(() => {
    stateRef.current = state
  }, [state])

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    const W = canvas.width = 400
    const H = canvas.height = 400
    const cx = W / 2
    const cy = H / 2

    const stateColors = {
      idle:      { core: '#1e3a5f', glow: '#3b82f6', particles: '#60a5fa' },
      listening: { core: '#0d3320', glow: '#22c55e', particles: '#4ade80' },
      thinking:  { core: '#2d1b4e', glow: '#a855f7', particles: '#c084fc' },
      speaking:  { core: '#1a2e4a', glow: '#38bdf8', particles: '#7dd3fc' },
      sleep:     { core: '#080d12', glow: '#1e3a5f', particles: '#1e3a5f' },
    }

    // Init particles
    const NUM_PARTICLES = 80
    particlesRef.current = Array.from({ length: NUM_PARTICLES }, (_, i) => {
      const angle = (i / NUM_PARTICLES) * Math.PI * 2
      const radius = 80 + Math.random() * 60
      return {
        angle,
        radius,
        baseRadius: radius,
        speed: 0.002 + Math.random() * 0.004,
        size: 1 + Math.random() * 2.5,
        opacity: 0.3 + Math.random() * 0.7,
        drift: Math.random() * Math.PI * 2,
        driftSpeed: 0.01 + Math.random() * 0.02,
      }
    })

    let tick = 0

    function draw() {
      animRef.current = requestAnimationFrame(draw)
      tick++
      ctx.clearRect(0, 0, W, H)

      const s = stateRef.current
      const colors = stateColors[s] || stateColors.idle

      // Speed multiplier per state
      const speedMult = s === 'listening' ? 2 : s === 'thinking' ? 3 : s === 'speaking' ? 2.5 : 1

      // Outer glow rings
      const glowLayers = [
        { r: 140, alpha: 0.08 },
        { r: 115, alpha: 0.12 },
        { r: 95,  alpha: 0.18 },
      ]
      for (const g of glowLayers) {
        const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, g.r)
        grad.addColorStop(0, colors.glow + '00')
        grad.addColorStop(0.5, colors.glow + Math.floor(g.alpha * 255).toString(16).padStart(2, '0'))
        grad.addColorStop(1, colors.glow + '00')
        ctx.beginPath()
        ctx.arc(cx, cy, g.r, 0, Math.PI * 2)
        ctx.fillStyle = grad
        ctx.fill()
      }

      // Pulse ring animation
      if (s === 'speaking' || s === 'listening') {
        const pulseR = 90 + Math.sin(tick * 0.15 * speedMult) * 20
        const pg = ctx.createRadialGradient(cx, cy, pulseR - 8, cx, cy, pulseR + 8)
        pg.addColorStop(0, colors.glow + '00')
        pg.addColorStop(0.5, colors.glow + '60')
        pg.addColorStop(1, colors.glow + '00')
        ctx.beginPath()
        ctx.arc(cx, cy, pulseR, 0, Math.PI * 2)
        ctx.strokeStyle = colors.glow + '80'
        ctx.lineWidth = 2
        ctx.stroke()
      }

      // Core orb
      const orbR = 75 + Math.sin(tick * 0.03 * speedMult) * 4
      const coreGrad = ctx.createRadialGradient(cx - 20, cy - 20, 5, cx, cy, orbR)
      coreGrad.addColorStop(0, '#a8d4ff')
      coreGrad.addColorStop(0.3, colors.glow)
      coreGrad.addColorStop(0.7, colors.core)
      coreGrad.addColorStop(1, '#000510')
      ctx.beginPath()
      ctx.arc(cx, cy, orbR, 0, Math.PI * 2)
      ctx.fillStyle = coreGrad
      ctx.fill()

      // Inner shine
      const shineGrad = ctx.createRadialGradient(cx - 25, cy - 25, 0, cx - 25, cy - 25, 35)
      shineGrad.addColorStop(0, 'rgba(255,255,255,0.25)')
      shineGrad.addColorStop(1, 'rgba(255,255,255,0)')
      ctx.beginPath()
      ctx.arc(cx, cy, orbR, 0, Math.PI * 2)
      ctx.fillStyle = shineGrad
      ctx.fill()

      // Thinking spin lines
      if (s === 'thinking') {
        for (let i = 0; i < 6; i++) {
          const a = (tick * 0.04) + (i / 6) * Math.PI * 2
          const r1 = orbR + 5
          const r2 = orbR + 20 + Math.sin(tick * 0.1 + i) * 8
          ctx.beginPath()
          ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1)
          ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2)
          ctx.strokeStyle = colors.glow + 'aa'
          ctx.lineWidth = 1.5
          ctx.stroke()
        }
      }

      // Particles
      for (const p of particlesRef.current) {
        p.angle += p.speed * speedMult
        p.drift += p.driftSpeed * speedMult

        const wobble = Math.sin(p.drift) * (s === 'speaking' ? 18 : s === 'thinking' ? 25 : 8)
        const r = p.baseRadius + wobble
        const x = cx + Math.cos(p.angle) * r
        const y = cy + Math.sin(p.angle) * r

        const alpha = p.opacity * (0.6 + Math.sin(p.drift * 2) * 0.4)
        ctx.beginPath()
        ctx.arc(x, y, p.size, 0, Math.PI * 2)
        ctx.fillStyle = colors.particles + Math.floor(alpha * 255).toString(16).padStart(2, '0')
        ctx.fill()
      }
    }

    draw()
    return () => cancelAnimationFrame(animRef.current)
  }, [])

  return (
    <canvas
      ref={canvasRef}
      onClick={onClick}
      style={{ cursor: 'pointer', borderRadius: '50%' }}
      aria-label="JARVIS orb - click to speak"
    />
  )
}
