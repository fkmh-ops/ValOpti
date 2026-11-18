import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, type PlayerDetail, type Role, type Slot } from './api'
import { LS, SLOT_ROLES } from './lib'

export interface Draft { name: string; slots: Slot[]; selected: number }

const emptySlots = (): Slot[] => SLOT_ROLES.map(() => ({ player_id: null, agent_id: null }))
export const emptyDraft = (): Draft => ({ name: '', slots: emptySlots(), selected: 0 })

/** Agent par défaut : le plus joué dans le rôle du slot, sinon le plus joué tout court, en évitant les doublons. */
export function defaultAgent(p: Pick<PlayerDetail, 'agents'>, role: Role, taken: (number | null)[]): number | null {
  const ok = p.agents.filter(a => !taken.includes(a.agent_id))
  const match = ok.find(a => role !== 'flex' && a.role === role)
  return (match ?? ok[0] ?? p.agents[0])?.agent_id ?? null
}

interface DraftCtx {
  draft: Draft
  setDraft: (d: Draft | ((d: Draft) => Draft)) => void
  place: (playerId: number) => Promise<'placed' | 'dup'>
  loadExample: () => Promise<void>
}
const Ctx = createContext<DraftCtx>(null as unknown as DraftCtx)
export const useDraft = () => useContext(Ctx)

export function DraftProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [draft, setDraftState] = useState<Draft>(() => {
    const d = LS.get<Draft | null>('valopti.draft', null)
    return d && Array.isArray(d.slots) && d.slots.length === 5 ? d : emptyDraft()
  })
  useEffect(() => LS.set('valopti.draft', draft), [draft])
  const setDraft = useCallback((d: Draft | ((d: Draft) => Draft)) => setDraftState(d), [])

  const detail = useCallback((id: number) => qc.fetchQuery({ queryKey: ['player', id, undefined], queryFn: () => api.player(id) }), [qc])

  const place = useCallback(async (playerId: number) => {
    if (draft.slots.some(s => s.player_id === playerId)) return 'dup' as const
    const p = await detail(playerId)
    setDraftState(d => {
      if (d.slots.some(s => s.player_id === playerId)) return d
      let i = d.selected
      if (d.slots[i].player_id) { const e = d.slots.findIndex(s => !s.player_id); if (e >= 0) i = e }
      const taken = d.slots.filter((_, j) => j !== i).map(s => s.agent_id)
      const slots = d.slots.slice()
      slots[i] = { player_id: playerId, agent_id: defaultAgent(p, SLOT_ROLES[i], taken) }
      const nx = slots.findIndex(s => !s.player_id)
      return { ...d, slots, selected: nx >= 0 ? nx : i }
    })
    return 'placed' as const
  }, [draft.slots, detail])

  const loadExample = useCallback(async () => {
    const used: number[] = []
    const slots: Slot[] = []
    for (const role of SLOT_ROLES) {
      const r = await api.players({ region: 'EMEA', role: role === 'flex' ? undefined : role, min_rounds: 400, limit: 12, period: 180 })
      const pick = r.items.find(p => !used.includes(p.player_id) && (role === 'flex' ? p.role : p.role !== 'flex'))
        ?? r.items.find(p => !used.includes(p.player_id))
      if (!pick) { slots.push({ player_id: null, agent_id: null }); continue }
      used.push(pick.player_id)
      const det = await detail(pick.player_id)
      slots.push({ player_id: pick.player_id, agent_id: defaultAgent(det, role, slots.map(s => s.agent_id)) })
    }
    setDraftState({ name: 'Exemple — meilleurs EMEA par rôle (180 j)', slots, selected: 4 })
  }, [detail])

  return <Ctx.Provider value={{ draft, setDraft, place, loadExample }}>{children}</Ctx.Provider>
}
