import { useEffect, useRef, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, type MatchRow, type PredSide, type SideIn } from '../api'
import { useDraft } from '../draft'
import { clamp, dShort, f2, fp } from '../lib'
import { AgentChip, Ctry, ErrorBox, Loading, PlayerLink, Src, useMeta } from '../ui'

function useSideIn(key: string | null): SideIn | null {
  const { draft } = useDraft()
  if (!key) return null
  if (key === 'draft') return { kind: 'draft', name: draft.name || 'Composition en cours', slots: draft.slots }
  const [k, id] = key.split(':')
  if (k === 'team' && +id) return { kind: 'team', team_id: +id }
  if (k === 'composition' && +id) return { kind: 'composition', composition_id: +id }
  return null
}

function SidePicker({ id, label, value, current, onChange }: { id: string; label: string; value: string | null; current?: string; onChange: (k: string) => void }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const { draft } = useDraft()
  const { data: saved } = useQuery({ queryKey: ['compositions'], queryFn: api.compositions })
  const { data: top } = useQuery({ queryKey: ['rankings', 'all', 30], queryFn: () => api.rankings('all', 30) })
  const { data: hits } = useQuery({ queryKey: ['search-team', q], queryFn: () => api.search(q, 'team', 15), enabled: q.trim().length >= 2 })
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('click', h, true)
    return () => document.removeEventListener('click', h, true)
  }, [])
  const pick = (k: string) => { onChange(k); setOpen(false); setQ('') }
  const opt = (k: string, l: string, sub: string, c?: string | null) =>
    <button key={k} className={k === value ? 'on' : ''} onClick={() => pick(k)}>{c !== undefined && <Ctry c={c} />}<span>{l}</span><span className="k">{sub}</span></button>
  return <div className="field picker" ref={ref}>
    <label htmlFor={id}>{label}</label>
    <button id={id} type="button" className="picker-btn" onClick={() => setOpen(o => !o)} aria-expanded={open}>{current ?? 'Choisir…'}</button>
    {open && <div className="sres picker-pop">
      <div style={{ padding: 8 }}><input autoFocus type="search" placeholder="Rechercher une équipe" value={q} onChange={e => setQ(e.target.value)} style={{ width: '100%' }} /></div>
      {q.trim().length >= 2 ? (hits?.length ? hits.map(h => opt(`team:${h.id}`, h.label, h.sub, h.country_code)) : <div className="empty">{hits ? 'Aucune équipe' : 'Recherche…'}</div>) : <>
        <div className="picker-h">Vos compositions</div>
        {opt('draft', draft.name || 'Composition en cours', 'en cours')}
        {saved?.map(c => opt(`composition:${c.composition_id}`, c.name, `note ${c.score ?? '—'}`))}
        <div className="picker-h">Top 30 mondial</div>
        {top?.map(t => opt(`team:${t.team_id}`, t.name, `${t.region ?? '—'} · ${t.elo}`, t.country_code))}
      </>}
    </div>}
  </div>
}

function Factor({ l, sub, v }: { l: string; sub: string; v: number }) {
  const w = clamp(Math.abs(v) / 250 * 50, 0, 50)
  return <div className="factor"><div>{l}<small>{sub}</small></div>
    <div className="div"><i style={v >= 0 ? { left: `${50 - w}%`, width: `${w}%`, background: 'var(--red)' } : { left: '50%', width: `${w}%`, background: 'var(--fg)' }} /></div>
    <b>{v >= 0 ? '+' : '−'}{Math.abs(Math.round(v))}</b></div>
}

const Roster = ({ s }: { s: PredSide }) => <>{s.players.map(({ player: p, agent_id }) =>
  <div key={p.player_id} className="rrow"><span className="nm"><Ctry c={p.country_code} /><PlayerLink id={p.player_id}>{p.ign}</PlayerLink></span>
    <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}><AgentChip id={agent_id} /><b className="num">{f2(p.rating)}</b></span></div>)}
  {!s.players.length && <div className="empty">Roster inconnu</div>}</>

function H2H({ ms }: { ms: MatchRow[] }) {
  return <div className="card"><div className="card-h"><h3>Confrontations directes</h3><Src t="matches" /></div>
    {ms.length ? ms.map(m => { const w1 = m.winner_team_id === m.team1_id; return <div key={m.match_id} className="res-row">
      <span className="d num">{dShort(m.match_date)}</span><div className={`t ${w1 ? 'win' : 'lose'}`}><span>{m.team1}</span></div>
      <div className="sc num"><span className={w1 ? 'w' : 'l'}>{m.team1_score}</span><span className="l">:</span><span className={w1 ? 'l' : 'w'}>{m.team2_score}</span></div>
      <div className={`t r ${w1 ? 'lose' : 'win'}`}><span>{m.team2}</span></div>
      <div className="maps num">{m.maps.map((mm, i) => <span key={i}>{mm.map} {mm.s1}–{mm.s2}</span>)}</div></div> })
      : <div className="empty">Aucune confrontation référencée.</div>}</div>
}

export default function Predictions() {
  const meta = useMeta()
  const [params, setParams] = useSearchParams()
  const { data: top } = useQuery({ queryKey: ['rankings', 'all', 30], queryFn: () => api.rankings('all', 30) })
  const aKey = params.get('a') ?? (top ? `team:${top[0].team_id}` : null)
  const bKey = params.get('b') ?? (top ? `team:${top[aKey === `team:${top[0].team_id}` ? 1 : 0].team_id}` : null)
  const bo = [1, 3, 5].includes(Number(params.get('bo'))) ? Number(params.get('bo')) : 3
  const A = useSideIn(aKey), B = useSideIn(bKey)
  const set = (patch: Record<string, string>) => setParams(p => { const n = new URLSearchParams(p); if (aKey) n.set('a', aKey); if (bKey) n.set('b', bKey); Object.entries(patch).forEach(([k, v]) => n.set(k, v)); return n }, { replace: true })
  const { data: r, error, isFetching } = useQuery({
    queryKey: ['predict', A, B, bo], queryFn: () => api.predict(A!, B!, bo), enabled: !!A && !!B, placeholderData: keepPreviousData, retry: false,
  })
  const bt = meta?.model_backtest
  const num = (v: number | undefined, d = 2) => (v ?? 0).toLocaleString('fr-FR', { maximumFractionDigits: d })
  const mapName = (id: number) => meta?.map_pool.find(m => m.map_id === id)?.name ?? `#${id}`
  const pa = r ? Math.round(r.p_a * 100) : 0
  const sameErr = error instanceof ApiError && error.status === 422

  return <>
    <div className="sec-h"><div><div className="h-eyebrow">Prédictions</div><h1 className="h2" style={{ fontSize: 40 }}>Simuler un match</h1></div>
      <span className="sub">Comparez deux équipes existantes, ou testez une de vos compositions contre un adversaire réel.</span></div>
    <div className="card pr-ctrl">
      <SidePicker id="pr-a" label="Équipe A" value={aKey} current={r?.a.name} onChange={k => set({ a: k })} />
      <button className="swapb" onClick={() => set({ a: bKey ?? '', b: aKey ?? '' })} aria-label="Inverser les équipes"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M2 5h11l-3-3M14 11H3l3 3" /></svg></button>
      <SidePicker id="pr-b" label="Équipe B" value={bKey} current={r?.b.name} onChange={k => set({ b: k })} />
      <div className="seg" role="group" aria-label="Format">{[1, 3, 5].map(n => <button key={n} className={bo === n ? 'on' : ''} onClick={() => set({ bo: String(n) })}>BO{n}</button>)}</div>
    </div>
    <div id="pr-out" style={{ opacity: isFetching ? 0.6 : 1 }}>
      {error ? (sameErr ? <div className="card empty">{error.message} {String(error.message).includes('5 joueurs') && <Link to="/draft" style={{ color: 'var(--red-ink)' }}>Compléter dans le Draft Maker</Link>}</div> : <ErrorBox error={error} />)
        : !r ? <Loading /> : <>
          <div className="card">
            <div className="duel">
              <div className="side a"><span className="tag">{r.a.composition ? 'Composition' : `${r.a.team?.region ?? '—'} · ${r.a.team?.tier ?? ''}`}</span><span className="nm">{r.a.name}</span><span className="p num">{pa}%</span></div>
              <div className="mid"><span>Score probable</span><b className="num">{r.likely_score.replace('-', '–')}</b><span>BO{r.best_of}</span></div>
              <div className="side b"><span className="tag">{r.b.composition ? 'Composition' : `${r.b.team?.region ?? '—'} · ${r.b.team?.tier ?? ''}`}</span><span className="nm">{r.b.name}</span><span className="p num">{100 - pa}%</span></div>
            </div>
            <div className="bigbar"><i style={{ width: `${pa}%` }} /><i style={{ width: `${100 - pa}%` }} /></div>
            <div className="dist">{r.distribution.map(d => <div key={d.score} className={d.score === r.likely_score ? 'top' : ''}><span>{d.score.replace('-', '–')}</span><b>{fp(d.p * 100)}</b></div>)}</div>
          </div>
          <div className="grid-2">
            <div className="card"><div className="card-h"><h3>Veto simulé</h3><Src t="match_maps · winrate 12 mois" /></div>
              <div className="veto">{r.veto.map((st, i) => {
                const who = st.side === 'a' ? r.a.tag : st.side === 'b' ? r.b.tag : '—'
                return <div key={i} className={`vstep ${st.action}`}><span className="n">{i + 1}</span>
                  <span className={`act ${st.action}`}>{st.action === 'decider' ? 'Decider' : st.action === 'pick' ? `Pick ${who}` : `Ban ${who}`}</span><span className="mp">{mapName(st.map_id)}</span>
                  {st.p_a !== null ? <div className="pp"><span className="num">{fp(st.p_a * 100)}</span><div className="pbar"><i style={{ width: `${st.p_a * 100}%` }} /><i style={{ width: `${(1 - st.p_a) * 100}%` }} /></div><span className="r num">{fp((1 - st.p_a) * 100)}</span></div> : <span className="sub">{who}</span>}
                </div>
              })}</div>
              <div className="method">Pool actuel : les 7 cartes les plus jouées sur 90 jours. Chaque équipe bannit la carte où sa probabilité est la plus faible et choisit celle où elle est la plus forte.</div></div>
            <div className="stack">
              <div className="card"><div className="card-h"><h3>Facteurs de la prédiction</h3><span className="sub">Points Elo, + = avantage {r.a.tag}</span></div>
                <Factor l="Niveau d’équipe" sub={`${r.a.elo_label} ${r.a.elo} vs ${r.b.elo}`} v={r.factors.level} />
                <Factor l="Map pool" sub="Elo propre à chaque carte, maps jouées" v={r.factors.map_pool} />
                <Factor l="Forme récente" sub={`Rating moyen 5 maps : ${f2(r.a.form)} vs ${f2(r.b.form)}`} v={r.factors.form} />
                <div className="method">Δ = <code>{num(r.weights.d_elo)} × écart d’Elo</code> + <code>{num(r.weights.d_map)} × écart d’Elo sur la carte</code> + <code>{num(r.weights.d_form, 0)} × écart de forme</code>, puis <code>p = 1 / (1 + 10^(−Δ/400))</code> par map ; la série combine les maps du veto. Poids appris sur l’historique vlr.gg (régression logistique) et validés sur des matchs jamais vus{bt?.series_test ? ` : ${(bt.series_test.accuracy * 100).toFixed(1)} % de séries bien prédites depuis ${dShort(bt.split)} ${bt.split?.slice(0, 4)}, contre ${((bt.series_test_current?.accuracy ?? 0) * 100).toFixed(1)} % pour l’ancien modèle` : ''}. Rapport complet : <code>data/RAPPORT_MODELE.md</code>.{(r.a.composition || r.b.composition) && ' Pour une composition, l’Elo est estimé par régression sur le rating moyen des rosters des équipes classées, moins une pénalité si les rôles sont mal couverts.'}</div>
              </div>
              <div className="card"><div className="card-h"><h3>Rosters</h3><Src t="players.current_team_id · player_agent_stats" /></div><div className="rosters"><div><Roster s={r.a} /></div><div><Roster s={r.b} /></div></div></div>
            </div>
          </div>
          {r.a.team && r.b.team && <H2H ms={r.h2h} />}
        </>}
    </div>
  </>
}
