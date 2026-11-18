import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api, type Agent, type Meta, type Role } from './api'
import { ROLE_COLOR, ROLE_FR, clamp } from './lib'

/* ------------------------------------------------------------ contexte UI */
interface Ui { toast: (t: string) => void; openPlayer: (id: number) => void; openTeam: (id: number) => void; close: () => void }
const UiCtx = createContext<Ui>(null as unknown as Ui)
export const useUi = () => useContext(UiCtx)

export function UiProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null)
  const timer = useRef<number>(undefined)
  const [, setParams] = useSearchParams()
  const toast = useCallback((t: string) => {
    setMsg(t); window.clearTimeout(timer.current); timer.current = window.setTimeout(() => setMsg(null), 2400)
  }, [])
  const open = useCallback((k: 'player' | 'team', id: number) => setParams(p => {
    const n = new URLSearchParams(p); n.delete('player'); n.delete('team'); n.set(k, String(id)); return n
  }), [setParams])
  const close = useCallback(() => setParams(p => { const n = new URLSearchParams(p); n.delete('player'); n.delete('team'); return n }), [setParams])
  const value = { toast, openPlayer: (id: number) => open('player', id), openTeam: (id: number) => open('team', id), close }
  return <UiCtx.Provider value={value}>{children}{msg && <div className="toast" role="status">{msg}</div>}</UiCtx.Provider>
}

/* ---------------------------------------------------------------- données */
export function useMeta(): Meta | undefined {
  return useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity }).data
}
export function useAgents(): Record<number, Agent> {
  const m = useMeta()
  return Object.fromEntries((m?.agents ?? []).map(a => [a.agent_id, a]))
}

/* ------------------------------------------------------------- composants */
export function LogoSymbol() {
  return (
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
      <defs>
        <symbol id="logo" viewBox="200 10 540 510">
          <line x1="470" y1="20" x2="470" y2="40" stroke="#ECE8E1" strokeWidth="8" />
          <line x1="470" y1="490" x2="470" y2="510" stroke="#ECE8E1" strokeWidth="8" />
          <line x1="213" y1="265" x2="262" y2="265" stroke="#FF4655" strokeWidth="8" />
          <line x1="678" y1="265" x2="727" y2="265" stroke="#FF4655" strokeWidth="8" />
          <polygon points="470,53 654,159 654,371 470,477 286,371 286,159" fill="#16222E" stroke="#FF4655" strokeWidth="9" />
          <polygon points="470,90 622,177 622,353 470,440 318,353 318,177" fill="none" stroke="#5C6B78" strokeWidth="2.5" />
          <polygon points="387,203 435,203 470,273 470,370" fill="#ECE8E1" />
          <polygon points="470,273 505,203 553,203 470,370" fill="#FF4655" />
        </symbol>
      </defs>
    </svg>
  )
}

export function RoleIcon({ role }: { role: Role }) {
  const c = ROLE_COLOR[role]
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      {role === 'duelist' && <path d="M2 13 8 2l6 11-6-3.5z" fill={c} />}
      {role === 'initiator' && <><circle cx="8" cy="9" r="2.3" fill={c} /><path d="M2.8 9a5.2 5.2 0 0 1 10.4 0" fill="none" stroke={c} strokeWidth="1.7" /></>}
      {role === 'controller' && <circle cx="8" cy="8" r="5.6" fill={c} fillOpacity=".35" stroke={c} strokeWidth="1.6" />}
      {role === 'sentinel' && <path d="M8 1.6 13.6 4v4.4c0 3-2.4 5.1-5.6 6-3.2-.9-5.6-3-5.6-6V4z" fill={c} />}
      {role === 'flex' && <><path d="M8 1.6 14.4 8 8 14.4 1.6 8z" fill="none" stroke={c} strokeWidth="1.7" /><path d="M8 5.5 10.5 8 8 10.5 5.5 8z" fill={c} /></>}
    </svg>
  )
}

export function RoleTag({ role }: { role: Role | null | undefined }) {
  if (!role) return <span className="role" title="Aucun agent référencé pour ce joueur">—</span>
  return <span className="role"><RoleIcon role={role} />{ROLE_FR[role]}</span>
}

export function AgentChip({ id }: { id: number | null | undefined }) {
  const ag = useAgents()
  const a = id ? ag[id] : undefined
  if (!a) return <span className="achip" style={{ color: 'var(--dim)' }}>Agent ?</span>
  return <span className="achip"><i style={{ background: ROLE_COLOR[a.role] }} />{a.name}</span>
}

export const Ctry = ({ c }: { c: string | null | undefined }) => <span className="ctry">{c && c !== 'un' ? c : '··'}</span>
export const Src = ({ t }: { t: string }) => <span className="src">{t}</span>

export function StatusPill({ p }: { p: { team_tag?: string | null; team_name?: string | null; team_id?: number | null; is_free_agent?: boolean } }) {
  if (p.team_id || p.team_tag || p.team_name) return <span className="pill ct">{p.team_tag || p.team_name}</span>
  if (p.is_free_agent) return <span className="pill fa" title="A quitté sa dernière équipe (elle a joué 2 matchs ou plus sans lui)">Sans équipe</span>
  return <span className="pill ct">Inactif</span>
}

export function PlayerLink({ id, children }: { id: number; children: ReactNode }) {
  const { openPlayer } = useUi()
  return <button className="link" onClick={e => { e.stopPropagation(); openPlayer(id) }}>{children}</button>
}
export function TeamLink({ id, children }: { id: number | null | undefined; children: ReactNode }) {
  const { openTeam } = useUi()
  if (!id) return <span>{children}</span>
  return <button className="link" onClick={e => { e.stopPropagation(); openTeam(id) }}>{children}</button>
}

export function Loading({ label = 'Chargement…' }: { label?: string }) {
  return <div className="empty loading">{label}</div>
}
export function ErrorBox({ error }: { error: unknown }) {
  return <div className="empty" style={{ color: 'var(--red-ink)' }}>Erreur : {error instanceof Error ? error.message : String(error)}</div>
}

export function Ring({ v }: { v: number }) {
  const c = 2 * Math.PI * 52
  return (
    <svg viewBox="0 0 120 120">
      <circle cx="60" cy="60" r="52" fill="none" stroke="var(--panel-2)" strokeWidth="9" />
      <circle cx="60" cy="60" r="52" fill="none" stroke="var(--red)" strokeWidth="9" strokeDasharray={`${(v / 100 * c).toFixed(1)} ${c.toFixed(1)}`} />
    </svg>
  )
}

export function Radar({ axes, label }: { axes: [string, number | null][]; label: string }) {
  const vals = axes.map(([, v]) => (v ?? 0) / 100)
  const n = axes.length
  const pt = (i: number, r: number): [number, number] => { const a = (-90 + i * 360 / n) * Math.PI / 180; return [Math.cos(a) * r * 88, Math.sin(a) * r * 88] }
  const ring = (r: number) => axes.map((_, i) => pt(i, r).map(x => x.toFixed(1)).join(',')).join(' ')
  return (
    <svg className="radar" viewBox="-152 -118 304 236" role="img" aria-label={label}>
      {[0.25, 0.5, 0.75, 1].map(r => <polygon key={r} points={ring(r)} fill="none" stroke={r === 1 ? '#5C6B78' : 'rgba(236,232,225,.10)'} strokeWidth={r === 1 ? 1.4 : 1} />)}
      {axes.map((_, i) => { const [x, y] = pt(i, 1); return <line key={i} x1="0" y1="0" x2={x.toFixed(1)} y2={y.toFixed(1)} stroke="rgba(236,232,225,.08)" /> })}
      <polygon points={vals.map((v, i) => pt(i, Math.max(0.04, v)).map(x => x.toFixed(1)).join(',')).join(' ')} fill="rgba(255,70,85,.22)" stroke="#FF4655" strokeWidth="2" />
      {vals.map((v, i) => { const [x, y] = pt(i, Math.max(0.04, v)); return <circle key={i} cx={x.toFixed(1)} cy={y.toFixed(1)} r="2.6" fill="#ECE8E1" /> })}
      {axes.map(([l, v], i) => { const [x, y] = pt(i, 1.17); return <text key={l} x={x.toFixed(1)} y={(y + 3).toFixed(1)} textAnchor={Math.abs(x) < 5 ? 'middle' : x > 0 ? 'start' : 'end'}>{l.toUpperCase()} {v === null ? '—' : Math.round(v)}</text> })}
    </svg>
  )
}

export function Spark({ values }: { values: number[] }) {
  if (values.length < 2) return <div className="sub">Pas assez de maps récentes.</div>
  const W = 260, H = 70, lo = 0.5, hi = 1.7
  const x = (i: number) => 8 + i * (W - 16) / (values.length - 1)
  const y = (v: number) => H - 6 - (clamp(v, lo, hi) - lo) / (hi - lo) * (H - 14)
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = values.length - 1
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Rating sur les ${values.length} dernières maps`}>
      <line x1="0" x2={W} y1={y(1)} y2={y(1)} stroke="rgba(236,232,225,.22)" strokeDasharray="3 4" />
      <text x={W - 2} y={y(1) - 4} textAnchor="end" fill="#66737F" fontSize="9">1.00</text>
      <polygon points={`${x(0)},${H} ${pts} ${x(last)},${H}`} fill="rgba(255,70,85,.12)" />
      <polyline points={pts} fill="none" stroke="#FF4655" strokeWidth="2" />
      {values.map((v, i) => <circle key={i} cx={x(i).toFixed(1)} cy={y(v).toFixed(1)} r={i === last ? 4 : 2} fill={i === last ? '#ECE8E1' : '#FF4655'} />)}
    </svg>
  )
}

/** Barre divergente centrée (winrate / écart de rating par map). */
export function MBar({ label, delta, scale, value }: { label: string; delta: number; scale: number; value: ReactNode }) {
  const w = clamp(Math.abs(delta) / scale * 50, 0, 50)
  const style = delta >= 0 ? { left: '50%', width: `${w}%`, background: 'var(--teal)' } : { left: `${50 - w}%`, width: `${w}%`, background: 'var(--red)' }
  return <div className="mbar"><span>{label}</span><div className="tr"><i style={style} /></div><b>{value}</b></div>
}

export const WL = ({ r }: { r: string }) => <span className={`wl ${r === 'W' ? 'w' : 'l'}`}>{r === 'W' ? 'V' : 'D'}</span>
