import type { CSSProperties } from 'react'
import type { Role, StatKey } from './api'

export const ROLES: Role[] = ['duelist', 'initiator', 'controller', 'sentinel']
export const SLOT_ROLES: Role[] = ['duelist', 'initiator', 'controller', 'sentinel', 'flex']
export const ROLE_FR: Record<Role, string> = {
  duelist: 'Duelliste', initiator: 'Initiateur', controller: 'Contrôleur', sentinel: 'Sentinelle', flex: 'Flex',
}
export const ROLE_COLOR: Record<Role, string> = {
  duelist: 'var(--duel)', initiator: 'var(--init)', controller: 'var(--ctrl)', sentinel: 'var(--sent)', flex: 'var(--flex)',
}

export const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v))
export const mean = (a: number[]) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0)

const nn = (v: number | null | undefined) => v === null || v === undefined || Number.isNaN(v)
export const f2 = (v: number | null | undefined) => (nn(v) ? '—' : (v as number).toFixed(2))
export const f1 = (v: number | null | undefined) => (nn(v) ? '—' : (v as number).toFixed(1))
export const f0 = (v: number | null | undefined) => (nn(v) ? '—' : String(Math.round(v as number)))
export const fp = (v: number | null | undefined) => (nn(v) ? '—' : Math.round(v as number) + '%')
export const money = (v: number | null | undefined) =>
  nn(v) ? '—' : (v as number) >= 1e6 ? '$' + ((v as number) / 1e6).toFixed(2) + ' M' : (v as number) >= 1e3 ? '$' + Math.round((v as number) / 1e3) + ' k' : '$' + v
export const dShort = (d: string | null | undefined) =>
  d ? new Date(d + 'T12:00:00Z').toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) : '—'
export const dLong = (d: string | null | undefined) =>
  d ? new Date(d + 'T12:00:00Z').toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }) : '—'
export const dTime = (at: string) =>
  new Date(at.replace(' ', 'T') + 'Z').toLocaleString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris' })
export const tagOf = (name: string, tag?: string | null) => tag || name.replace(/[^A-Za-z0-9 ]/g, '').split(/\s+/).map(w => w[0]).join('').slice(0, 4).toUpperCase() || name.slice(0, 3).toUpperCase()

export const STAT_COLS: [StatKey, string, (v: number | null) => string][] = [
  ['rating', 'Rating', f2], ['acs', 'ACS', f0], ['kd', 'K/D', f2], ['kast_pct', 'KAST', fp], ['adr', 'ADR', f0],
  ['kpr', 'KPR', f2], ['apr', 'APR', f2], ['fkpr', 'FKPR', f2], ['fdpr', 'FDPR', f2], ['hs_pct', 'HS%', fp],
  ['clutch_per100', 'CL/100', f1],
]

/** Couleur de fond selon le percentile (teal = haut, rouge = bas), comme la maquette. */
export function heat(p: number | null | undefined): CSSProperties | undefined {
  if (p === null || p === undefined) return undefined
  return p >= 50
    ? { backgroundColor: `rgba(59,214,194,${((p - 50) / 50 * 0.30).toFixed(3)})` }
    : { backgroundColor: `rgba(255,70,85,${((50 - p) / 50 * 0.24).toFixed(3)})` }
}

export const LS = {
  get<T>(k: string, d: T): T { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) as T : d } catch { return d } },
  set(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* stockage indisponible */ } },
}
