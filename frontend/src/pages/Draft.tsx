import { useDeferredValue, useEffect, useRef, useState } from 'react'
import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api, type PlayerDetail } from '../api'
import { emptyDraft, useDraft } from '../draft'
import { ROLES, ROLE_FR, SLOT_ROLES, f0, f2, fp } from '../lib'
import { Ctry, ErrorBox, Loading, PlayerLink, RoleTag, Ring, Src, StatusPill, useAgents, useMeta, useUi } from '../ui'

function Slots({ details }: { details: (PlayerDetail | undefined)[] }) {
  const { draft, setDraft } = useDraft()
  const agents = useAgents()
  const all = Object.values(agents)
  return <div className="slots">{draft.slots.map((s, i) => {
    const ro = SLOT_ROLES[i], sel = draft.selected === i ? ' sel' : ''
    const select = () => setDraft(d => ({ ...d, selected: i }))
    if (!s.player_id) return <div key={i} className={`slot emptyslot${sel}`} role="button" tabIndex={0} onClick={select}
      onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), select())} aria-label={`Slot ${ROLE_FR[ro]}, vide`}>
      <span className="plus">+</span><RoleTag role={ro} /><span className="sub">{sel ? 'Choisissez un joueur dans la liste' : 'Cliquez pour sélectionner'}</span></div>
    const p = details[i]
    const taken = draft.slots.filter((_, j) => j !== i).map(x => x.agent_id)
    const own = p?.agents.map(a => a.agent_id) ?? []
    return <div key={i} className={`slot${sel}`} role="button" tabIndex={0} onClick={e => { if (!(e.target as HTMLElement).closest('select,.link,.x')) select() }}
      aria-label={`Slot ${ROLE_FR[ro]}, ${p?.ign ?? ''}`}>
      <button className="x" onClick={e => { e.stopPropagation(); setDraft(d => { const slots = d.slots.slice(); slots[i] = { player_id: null, agent_id: null }; return { ...d, slots, selected: i } }) }} aria-label={`Retirer ${p?.ign ?? 'le joueur'}`}>×</button>
      <div className="sr"><RoleTag role={ro} /></div>
      <div className="ign">{p ? <PlayerLink id={p.player_id}>{p.ign}</PlayerLink> : '…'}</div>
      {p && <>
        <div className="info"><Ctry c={p.country_code} /><StatusPill p={p} />{p.rookie && <span className="pill rk">Court</span>}</div>
        <div className="big"><div><span>Rating</span><b>{f2(p.stats?.rating)}</b></div><div><span>ACS</span><b>{f0(p.stats?.acs)}</b></div><div><span>KAST</span><b>{fp(p.stats?.kast_pct)}</b></div></div>
      </>}
      <select aria-label={`Agent de ${p?.ign ?? ''}`} value={s.agent_id ?? ''} onChange={e => {
        const v = e.target.value ? +e.target.value : null
        setDraft(d => { const slots = d.slots.slice(); slots[i] = { ...slots[i], agent_id: v }; return { ...d, slots } })
      }}>
        <option value="">Agent à choisir</option>
        {p && p.agents.length > 0 && <optgroup label="Pool du joueur">{p.agents.map(a => <option key={a.agent_id} value={a.agent_id}>{a.name} · {fp(a.usage * 100)} · {f2(a.rating)}{taken.includes(a.agent_id) ? ' (déjà pris)' : ''}</option>)}</optgroup>}
        <optgroup label={own.length ? 'Hors pool' : 'Tous les agents'}>{all.filter(a => !own.includes(a.agent_id)).map(a => <option key={a.agent_id} value={a.agent_id}>{a.name} ({ROLE_FR[a.role]}){taken.includes(a.agent_id) ? ' (déjà pris)' : ''}</option>)}</optgroup>
      </select></div>
  })}</div>
}

function Pool() {
  const { draft, place } = useDraft()
  const { toast } = useUi()
  const [f, setF] = useState({ q: '', role: 'auto', status: 'all' })
  const q = useDeferredValue(f.q)
  const slotRole = SLOT_ROLES[draft.selected]
  const role = f.role === 'auto' ? (slotRole === 'flex' ? undefined : slotRole) : f.role === 'all' ? undefined : f.role
  const params = { q, role, min_rounds: 200, period: 180, limit: 150,
    status: f.status === 'free_agent' ? 'free_agent' : undefined, tier: ['VCT', 'Challengers'].includes(f.status) ? f.status : undefined }
  const { data, error } = useQuery({ queryKey: ['players', params], queryFn: () => api.players(params), placeholderData: keepPreviousData })
  const inDraft = draft.slots.map(s => s.player_id)
  const add = async (id: number, ign: string) => { if (await place(id) === 'dup') toast(`${ign} est déjà dans la composition`) }
  return <div className="card">
    <div className="card-h"><h3>Joueurs disponibles · {data?.total ?? '…'}</h3><Src t="players ⨝ player_stats_snapshot" /></div>
    <div className="pool-f">
      <div className="field"><label htmlFor="pool-q">Recherche</label><input id="pool-q" type="search" value={f.q} placeholder="Pseudo ou équipe" onChange={e => setF({ ...f, q: e.target.value })} /></div>
      <div className="field"><label htmlFor="pool-role">Rôle</label><select id="pool-role" value={f.role} onChange={e => setF({ ...f, role: e.target.value })}>
        <option value="auto">Slot sélectionné</option><option value="all">Tous (rôle inconnu inclus)</option>{ROLES.map(r => <option key={r} value={r}>{ROLE_FR[r]}</option>)}</select></div>
      <div className="field"><label htmlFor="pool-status">Statut</label><select id="pool-status" value={f.status} onChange={e => setF({ ...f, status: e.target.value })}>
        <option value="all">Tous</option><option value="free_agent">Sans équipe</option><option value="Challengers">Challengers</option><option value="VCT">VCT</option></select></div>
    </div>
    <div className="pool">
      <div className="prow prow-h"><span>Joueur · 180 j, 200 rounds min.</span><span className="rolec">Rôle</span><span className="r">Rating</span><span className="r">ACS</span><span /></div>
      {error ? <ErrorBox error={error} /> : !data ? <Loading /> : data.items.length ? data.items.map(p => {
        const inn = inDraft.includes(p.player_id)
        return <div key={p.player_id} className={`prow${inn ? ' in' : ''}`}>
          <div className="who"><div className="l1"><Ctry c={p.country_code} /><PlayerLink id={p.player_id}>{p.ign}</PlayerLink>{p.rookie && <span className="pill rk">C</span>}</div>
            <div className="l2">{p.team_id ? `${p.team_tag ?? p.team_name}${p.tier ? ' · ' + p.tier : ''}` : p.is_free_agent ? 'Sans équipe' : 'Inactif'}</div></div>
          <span className="rolec"><RoleTag role={p.role} /></span><span className="r" style={{ fontWeight: 700 }}>{f2(p.rating)}</span><span className="r">{f0(p.acs)}</span>
          {inn ? <span /> : <button className="add" onClick={() => add(p.player_id, p.ign)} aria-label={`Placer ${p.ign} dans le slot ${ROLE_FR[slotRole]}`}>+</button>}
        </div>
      }) : <div className="empty">Aucun joueur pour ce filtre. Les rôles ne sont connus que pour les joueurs du circuit VCT : essayez « Tous ».</div>}
    </div>
  </div>
}

function Analysis() {
  const { draft, setDraft, loadExample } = useDraft()
  const { toast } = useUi()
  const meta = useMeta()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { data: an, error } = useQuery({ queryKey: ['analyse', draft.slots], queryFn: () => api.analyse(draft.slots), placeholderData: keepPreviousData })
  const { data: saved } = useQuery({ queryKey: ['compositions'], queryFn: api.compositions })
  const save = useMutation({
    mutationFn: () => api.saveComposition(draft.name.trim() || `Composition ${(saved?.length ?? 0) + 1}`, draft.slots),
    onSuccess: c => { setDraft(d => ({ ...d, name: c.name })); qc.invalidateQueries({ queryKey: ['compositions'] }); toast(c.updated ? 'Composition mise à jour' : 'Composition sauvegardée') },
    onError: e => toast(`Échec : ${e.message}`),
  })
  const del = useMutation({
    mutationFn: (id: number) => api.deleteComposition(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['compositions'] }); toast('Composition supprimée') },
  })
  const full = draft.slots.every(s => s.player_id)
  const bar = (l: string, v: number) => <div className="bar-r"><span>{l}</span><div className="tr"><i style={{ width: `${v.toFixed(0)}%` }} /></div><b>{Math.round(v)}</b></div>
  return <div className="stack">
    <div className="card">
      <div className="card-h"><h3>Analyse de la composition</h3><Src t="player_stats_snapshot · player_agent_stats" /></div>
      {error ? <ErrorBox error={error} /> : !an ? <Loading /> : <>
        <div className="score-top"><div className="ring"><Ring v={an.score} /><div className="v"><div><b className="num">{an.score}</b><span>Note ValOpti</span></div></div></div>
          <div className="bars">{bar('Puissance de feu', an.parts.firepower)}{bar('Entry', an.parts.entry)}{bar('Utilitaire', an.parts.utility)}{bar('Clutch', an.parts.clutch)}{bar('Équilibre rôles', an.parts.balance)}</div></div>
        <div className="pad" style={{ borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}><span className="h-eyebrow" style={{ color: 'var(--muted)' }}>Victoire projetée par map vs équipe classée médiane</span><span className="sub num">Rating moyen {an.avg ? f2(an.avg) : '—'}</span></div>
          {full && meta ? <div className="mapstrip">{meta.map_pool.map(m => {
            const p = an.maps[String(m.map_id)] ?? 0.5, a = Math.abs(p - 0.5) * 2 * 0.5
            return <div key={m.map_id} className="mapcell" style={{ backgroundColor: p >= 0.5 ? `rgba(59,214,194,${a.toFixed(2)})` : `rgba(255,70,85,${a.toFixed(2)})` }}><span>{m.name}</span><b>{fp(p * 100)}</b></div>
          })}</div> : <div className="sub">Complétez les 5 slots pour voir la projection par map.</div>}
        </div>
        <div className="pad" style={{ borderTop: '1px solid var(--line)' }}><div className="alerts">{an.alerts.map((a, i) => <div key={i} className={`alert ${a.level}`}><i /><span>{a.text}</span></div>)}</div></div>
      </>}
      <div className="pad" style={{ borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className="saverow"><input value={draft.name} placeholder="Nom de la composition" aria-label="Nom de la composition" maxLength={80} onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} />
          <button className="btn sm" onClick={() => save.mutate()} disabled={save.isPending || !draft.slots.some(s => s.player_id)}>Sauvegarder</button></div>
        <div className="saverow">
          <button className="btn ghost sm" disabled={!full} onClick={() => nav('/predictions?a=draft')}>Prédire contre une équipe</button>
          <button className="btn ghost sm" onClick={() => setDraft(emptyDraft())}>Vider</button>
          <button className="btn ghost sm" onClick={() => loadExample()}>Charger un exemple</button>
        </div>
      </div>
    </div>
    <div className="card"><div className="card-h"><h3>Compositions sauvegardées</h3><Src t="compositions · composition_slots" /></div>
      <div className="saved">{saved?.length ? saved.map(c => <div key={c.composition_id} className="saved-row">
        <div style={{ minWidth: 0 }}><b>{c.name}</b><small>{c.slots.map(s => s.ign ?? '—').join(' · ')}</small></div>
        <span className="num" style={{ fontWeight: 700 }}>{c.score ?? '—'}</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button className="btn ghost sm" onClick={() => { setDraft({ name: c.name, slots: c.slots.map(s => ({ player_id: s.player_id, agent_id: s.agent_id })), selected: 0 }); toast(`« ${c.name} » chargée`) }}>Charger</button>
          <button className="btn ghost sm" onClick={() => del.mutate(c.composition_id)} aria-label={`Supprimer ${c.name}`}>×</button></div>
      </div>) : <div className="empty">Aucune composition sauvegardée. Nommez la composition en cours puis cliquez sur Sauvegarder.</div>}</div></div>
  </div>
}

export default function DraftPage() {
  const { draft, loadExample } = useDraft()
  const details = useQueries({
    queries: draft.slots.map(s => ({ queryKey: ['player', s.player_id, undefined], queryFn: () => api.player(s.player_id!), enabled: !!s.player_id })),
  }).map(q => q.data)
  const empty = draft.slots.every(s => !s.player_id) && !draft.name
  // exemple chargé une seule fois, à la première visite (brouillon vide au montage)
  const seeded = useRef(!empty)
  useEffect(() => { if (!seeded.current) { seeded.current = true; loadExample() } }, [loadExample])
  return <>
    <div className="sec-h"><div><div className="h-eyebrow">Draft Maker</div><h1 className="h2" style={{ fontSize: 40 }}>Composer un roster</h1></div>
      <span className="sub">Sélectionnez un slot, puis ajoutez un joueur. L’agent par défaut est le plus joué par le joueur dans ce rôle.</span></div>
    <Slots details={details} />
    <div className="draft-grid"><Pool /><Analysis /></div>
  </>
}

