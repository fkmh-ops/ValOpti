import { useDeferredValue, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api, type PlayerQuery } from '../api'
import { LS, ROLES, ROLE_FR, STAT_COLS, heat } from '../lib'
import { AgentChip, Ctry, ErrorBox, Loading, RoleTag, Src, useMeta, useUi } from '../ui'

const PAGE = 100
type F = Required<Pick<PlayerQuery, 'q' | 'region' | 'role' | 'status' | 'tier' | 'min_rounds' | 'period' | 'sort' | 'dir'>>
const DEFAULT: F = { q: '', region: 'all', role: 'all', status: 'all', tier: 'all', min_rounds: 200, period: 180, sort: 'rating', dir: 'desc' }

export default function Scouting() {
  const meta = useMeta()
  const { openPlayer } = useUi()
  const [f, setF] = useState<F>(() => ({ ...DEFAULT, ...LS.get<Partial<F>>('valopti.scouting', {}), q: '' }))
  const [limit, setLimit] = useState(PAGE)
  const q = useDeferredValue(f.q)
  const set = (patch: Partial<F>) => { const n = { ...f, ...patch }; setF(n); setLimit(PAGE); LS.set('valopti.scouting', { ...n, q: '' }) }
  const { data, error, isFetching } = useQuery({
    queryKey: ['players', { ...f, q, limit }],
    queryFn: () => api.players({ ...f, q, limit }),
    placeholderData: keepPreviousData,
  })
  const sortBy = (k: string) => set(f.sort === k ? { dir: f.dir === 'desc' ? 'asc' : 'desc' } : { sort: k, dir: k === 'ign' || k === 'fdpr' ? 'asc' : 'desc' })
  const Th = ({ k, l, cls = '' }: { k: string; l: string; cls?: string }) =>
    <th data-sort={k} className={`${cls} ${f.sort === k ? 'sorted' + (f.dir === 'asc' ? ' asc' : '') : ''}`} onClick={() => sortBy(k)}>{l}</th>

  return <>
    <div className="sec-h"><div><div className="h-eyebrow">Scouting</div><h1 className="h2" style={{ fontSize: 40 }}>Base joueurs</h1></div>
      <span className="sub">Stats pondérées par rounds sur la période. Comparez de préférence au sein d’un même circuit : un rating élevé dans un circuit plus faible vaut moins. Couleur : percentile du joueur dans la base (teal = haut, rouge = bas). <Src t="player_stats_snapshot · player_agent_stats" /></span></div>
    <div className="card pad filters" style={{ gridTemplateColumns: '2fr repeat(6,1fr)' }}>
      <div className="field"><label htmlFor="sc-q">Recherche</label><input id="sc-q" type="search" value={f.q} placeholder="Pseudo, nom, équipe" onChange={e => set({ q: e.target.value })} /></div>
      <div className="field"><label htmlFor="sc-region">Région</label><select id="sc-region" value={f.region} onChange={e => set({ region: e.target.value })}>
        <option value="all">Toutes</option>{meta?.regions.map(r => <option key={r} value={r}>{r}</option>)}</select></div>
      <div className="field"><label htmlFor="sc-role">Rôle</label><select id="sc-role" value={f.role} onChange={e => set({ role: e.target.value })}>
        <option value="all">Tous</option>{[...ROLES, 'flex' as const].map(r => <option key={r} value={r}>{ROLE_FR[r]}</option>)}</select></div>
      <div className="field"><label htmlFor="sc-status">Statut</label><select id="sc-status" value={f.status} onChange={e => set({ status: e.target.value })}>
        <option value="all">Tous</option><option value="free_agent">Sans équipe</option><option value="contracted">Sous contrat</option><option value="rookie">Échantillon &lt; 650 rnd</option></select></div>
      <div className="field"><label htmlFor="sc-tier">Circuit</label><select id="sc-tier" value={f.tier} onChange={e => set({ tier: e.target.value })}>
        <option value="all">Tous</option>{['VCT', 'Challengers', 'Game Changers', 'Autre'].map(t => <option key={t} value={t}>{t}</option>)}</select></div>
      <div className="field"><label htmlFor="sc-min">Rounds min.</label><select id="sc-min" value={f.min_rounds} onChange={e => set({ min_rounds: +e.target.value })}>
        {[0, 200, 400, 800].map(v => <option key={v} value={v}>{v || 'Aucun'}</option>)}</select></div>
      <div className="field"><label htmlFor="sc-period">Période</label><select id="sc-period" value={f.period} onChange={e => set({ period: +e.target.value })}>
        {(meta?.periods ?? [90, 180, 365]).map(v => <option key={v} value={v}>{v} jours</option>)}</select></div>
    </div>
    <div className="card">
      <div className="card-h"><h3>{data ? `${data.total.toLocaleString('fr-FR')} joueur${data.total > 1 ? 's' : ''}` : '…'}</h3>
        <span className="sub">{isFetching ? 'Mise à jour…' : 'Cliquez sur un joueur pour ouvrir sa fiche. Rôle déduit des agents joués (circuit VCT).'}</span></div>
      {error ? <ErrorBox error={error} /> : !data ? <Loading /> : data.items.length ? <>
        <div className="tscroll"><table className="tbl"><thead><tr>
          <Th k="ign" l="Joueur" cls="l" /><th className="l">Rôle</th><th className="l">Agents</th><Th k="rounds_played" l="Rnd" />
          {STAT_COLS.map(([k, l]) => <Th key={k} k={k} l={l} />)}</tr></thead>
          <tbody>{data.items.map(p => <tr key={p.player_id} onClick={() => openPlayer(p.player_id)}>
            <td className="l"><div className="pcell"><Ctry c={p.country_code} /><div><b>{p.ign}</b> {p.rookie && <span className="pill rk">Court</span>}<br />
              <small>{p.team_name ?? (p.is_free_agent ? `Sans équipe${p.last_team_name ? ' · ex-' + p.last_team_name : ''}` : 'Inactif')}</small></div></div></td>
            <td className="l"><RoleTag role={p.role} /></td>
            <td className="l">{p.agents.length ? <span style={{ display: 'inline-flex', gap: 4 }}>{p.agents.map(a => <AgentChip key={a} id={a} />)}</span> : <span className="sub">—</span>}</td>
            <td className="num" style={{ color: 'var(--muted)' }}>{p.rounds_played}</td>
            {STAT_COLS.map(([k, , fmt]) => <td key={k} className={k === 'rating' ? 'hl' : ''} style={heat(p.pct[k])}>{fmt(p[k])}</td>)}
          </tr>)}</tbody></table></div>
        {data.total > data.items.length && <div className="pad" style={{ textAlign: 'center' }}>
          <button className="btn ghost sm" onClick={() => setLimit(l => l + PAGE)}>Afficher {Math.min(PAGE, data.total - data.items.length)} de plus</button></div>}
      </> : <div className="empty">Aucun joueur ne correspond à ces filtres. Élargissez la région, la période ou baissez le minimum de rounds.</div>}
    </div>
  </>
}
