import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { LS, dShort } from '../lib'
import { Ctry, ErrorBox, Loading, Src, WL, useMeta, useUi } from '../ui'

export default function Rankings() {
  const meta = useMeta()
  const { openTeam } = useUi()
  const [rg, setRg] = useState(() => LS.get('valopti.rank', 'all'))
  const choose = (r: string) => { setRg(r); LS.set('valopti.rank', r) }
  const { data, error, isFetching } = useQuery({ queryKey: ['rankings', rg, 100], queryFn: () => api.rankings(rg, 100), placeholderData: keepPreviousData })
  return <>
    <div className="sec-h"><div><div className="h-eyebrow">Classement</div><h1 className="h2" style={{ fontSize: 40 }}>Équipes</h1></div>
      <div className="tabs">{['all', ...(meta?.regions ?? []), 'gc'].map(r => <button key={r} className={rg === r ? 'on' : ''} onClick={() => choose(r)}>{r === 'all' ? 'Monde' : r === 'gc' ? 'Game Changers' : r}</button>)}</div></div>
    <div className="card">
      <div className="card-h"><h3>{rg === 'all' ? 'Classement mondial' : rg === 'gc' ? 'Circuit Game Changers' : 'Région ' + rg} · top 100</h3><Src t="team_profile (Elo ValOpti)" /></div>
      {error ? <ErrorBox error={error} /> : !data ? <Loading /> : <div className="tscroll" style={{ opacity: isFetching ? 0.6 : 1 }}><table className="tbl"><thead><tr>
        <th className="l">#</th><th className="l">Équipe</th><th className="l">Région</th><th className="l">Tier</th><th>Elo</th><th>V–D 12 mois</th><th className="l">5 derniers</th><th>Série</th><th>Meilleure map</th><th>Dernier match</th></tr></thead>
        <tbody>{data.map((t, i) => <tr key={t.team_id} onClick={() => openTeam(t.team_id)}>
          <td className="l num" style={{ fontFamily: 'var(--f-display)', fontSize: 20, color: 'var(--muted)' }}>{rg === 'all' || rg === 'gc' ? t.world_rank : t.region_rank ?? i + 1}</td>
          <td className="l"><div className="pcell"><Ctry c={t.country_code} /><div><b>{t.name}</b><br /><small>{t.short_tag ?? ''}</small></div></div></td>
          <td className="l">{t.region ?? '—'}</td>
          <td className="l"><span className={`pill ${t.tier === 'VCT' ? 'vct' : 'ct'}`}>{t.tier}</span></td>
          <td className="hl">{t.elo}</td><td>{t.wins_365}–{t.losses_365}</td>
          <td className="l"><span className="form5">{[...t.last5].map((r, j) => <WL key={j} r={r} />)}</span></td>
          <td>{t.streak_length} {t.streak_type === 'W' ? 'V' : 'D'}</td>
          <td>{t.best_map ? <>{t.best_map.map} <span style={{ color: 'var(--dim)' }}>{Math.round(t.best_map.winrate * 100)}%</span></> : '—'}</td>
          <td className="num" style={{ color: 'var(--muted)' }}>{dShort(t.last_match_date)}</td>
        </tr>)}</tbody></table></div>}
      <div className="method">Elo ValOpti : recalculé chronologiquement sur tous les matchs terminés depuis 2020 (forfaits exclus). Réglages choisis par backtest : K = 64 sur les 15 premiers matchs puis 40, majoré pour un 2-0, départ selon le circuit du premier match (VCT 1700, Challengers 1600, autres 1450), retour partiel vers la moyenne après 6 mois d’inactivité. Équipes classées : au moins 10 matchs et un match sur les 180 derniers jours. Tier déduit des événements disputés sur 12 mois. Les équipes Game Changers ne rencontrent quasiment jamais les autres circuits : leur Elo n’est pas comparable et elles ont leur propre classement. Les classements vlr.gg de la base ne couvrent que 8 régions secondaires et ne sont pas utilisés ici.</div>
    </div>
  </>
}
