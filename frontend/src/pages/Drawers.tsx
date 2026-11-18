import { useEffect, useRef, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api, type StatKey } from '../api'
import { useDraft } from '../draft'
import { ROLE_FR, dShort, f0, f1, f2, fp, mean, money } from '../lib'
import { AgentChip, Ctry, ErrorBox, Loading, MBar, Radar, RoleTag, Spark, Src, StatusPill, TeamLink, WL, useUi } from '../ui'

function Shell({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    ref.current?.querySelector<HTMLButtonElement>('.close')?.focus()
    return () => { document.body.style.overflow = '' }
  }, [])
  return <aside className="drawer" ref={ref} role="dialog" aria-modal="true">{children}</aside>
}

const Close = () => { const { close } = useUi(); return <button className="close" onClick={close} aria-label="Fermer">×</button> }

export function PlayerDrawer({ id }: { id: number }) {
  const { data: p, error } = useQuery({ queryKey: ['player', id, undefined], queryFn: () => api.player(id) })
  const { place } = useDraft()
  const { toast, close } = useUi()
  const nav = useNavigate()
  if (error) return <Shell><div className="dr-h"><Close /></div><ErrorBox error={error} /></Shell>
  if (!p) return <Shell><div className="dr-h"><Close /></div><Loading /></Shell>
  const s = p.stats
  const roleLabel = p.main_role ? ROLE_FR[p.main_role].toLowerCase() + 's' : 'joueurs'
  const tile = (l: string, v: string, k: StatKey) => {
    const pc = s?.pct_role[k]
    return <div><span>{l}</span><b>{v}</b><small>{pc === null || pc === undefined ? '—' : `Top ${Math.max(1, 100 - Math.round(pc))}% ${roleLabel}`}</small></div>
  }
  const form = p.form.map(f => f.rating)
  const add = async () => {
    const r = await place(p.player_id)
    if (r === 'dup') { toast(`${p.ign} est déjà dans la composition`); return }
    close(); nav('/draft'); toast(`${p.ign} ajouté à la composition`)
  }
  return (
    <Shell>
      <div className="dr-h"><Close />
        <div className="meta"><Ctry c={p.country_code} /><RoleTag role={p.role} /><StatusPill p={p} />{p.rookie && <span className="pill rk">Échantillon court</span>}</div>
        <div className="ign">{p.ign}</div>
        <div className="meta">
          {p.real_name && <><span>{p.real_name}</span><span>·</span></>}
          <span>{p.team_id ? <TeamLink id={p.team_id}>{p.team_name}</TeamLink> : p.last_team_id ? <>Ex-<TeamLink id={p.last_team_id}>{p.last_team_name}</TeamLink></> : 'Sans équipe'}</span>
          <span>·</span><span className="num">{p.region ?? 'Région inconnue'} · vu le {dShort(p.last_seen)}</span>
          {p.total_winnings_usd ? <><span>·</span><span>gains {money(p.total_winnings_usd)}</span></> : null}
        </div>
      </div>
      <div className="dr-b">
        {s ? <>
          <div className="tiles num">{tile('Rating', f2(s.rating), 'rating')}{tile('ACS', f0(s.acs), 'acs')}{tile('K/D', f2(s.kd), 'kd')}{tile('KAST', fp(s.kast_pct), 'kast_pct')}{tile('ADR', f0(s.adr), 'adr')}</div>
          <div className="sub" style={{ marginTop: -12 }}>{s.rounds_played} rounds · {s.maps_played} maps sur {p.period} jours. Percentiles calculés face aux {roleLabel} ayant joué au moins 150 rounds.</div>
          <div className="two">
            <div><h4>Profil <Src t="percentiles par rôle" /></h4>
              <Radar label={`Profil en percentiles face aux ${roleLabel}`} axes={[['Rating', s.pct_role.rating], ['ACS', s.pct_role.acs], ['KAST', s.pct_role.kast_pct], ['ADR', s.pct_role.adr], ['Entry', s.pct_role.fkpr], ['Clutch', s.pct_role.clutch_per100]]} />
            </div>
            <div><h4>Forme · {form.length} maps <Src t="player_map_stats" /></h4>
              <Spark values={form} />
              <div className="sub num" style={{ marginTop: 6 }}>Moyenne 5 dernières : <b style={{ color: 'var(--fg)' }}>{f2(mean(form.slice(-5)))}</b> · période {f2(s.rating)}</div>
              <div className="tiles num" style={{ gridTemplateColumns: 'repeat(3,minmax(0,1fr))', marginTop: 12 }}>{tile('FKPR', f2(s.fkpr), 'fkpr')}{tile('CL/100', f1(s.clutch_per100), 'clutch_per100')}{tile('HS', fp(s.hs_pct), 'hs_pct')}</div>
            </div>
          </div>
        </> : <div className="card empty">Aucune map avec stats détaillées sur les {p.period} derniers jours (dernier match : {dShort(p.last_seen)}).</div>}
        <div><h4>Pool d’agents <Src t="player_agent_stats" /></h4>
          {p.agents.length ? <div className="tscroll"><table className="tbl"><thead><tr><th className="l">Agent</th><th>Usage</th><th>Maps</th><th>Rating</th><th>ACS</th><th>K/D</th></tr></thead><tbody>
            {p.agents.map(a => <tr key={a.agent_id} style={{ cursor: 'default' }}><td className="l"><AgentChip id={a.agent_id} /></td><td>{fp(a.usage * 100)}</td><td>{a.maps}</td><td className="hl">{f2(a.rating)}</td><td>{f0(a.acs)}</td><td>{f2(a.kd)}</td></tr>)}
          </tbody></table></div> : <div className="sub">Aucun agent référencé : vlr.gg ne fournit pas les agents, ils proviennent du dataset Kaggle (circuit VCT uniquement).</div>}
        </div>
        <div><h4>Rating par map · 12 mois <Src t="player_map_stats ⨝ match_maps" /></h4>
          {p.maps.length ? p.maps.map(m => {
            const d = m.rating - (s?.rating ?? 1)
            return <MBar key={m.map_id} label={m.name} delta={d} scale={0.2} value={<>{f2(m.rating)} <small>{m.maps} map{m.maps > 1 ? 's' : ''}</small></>} />
          }) : <div className="sub">Aucune map du pool actuel jouée sur 12 mois.</div>}
        </div>
        <div><h4>Parcours <Src t="player_team_membership" /></h4>
          <div className="hist">{p.career.length ? p.career.map(h => (
            <div key={h.team_id}><span><TeamLink id={h.team_id}>{h.team_name}</TeamLink>{h.is_current && <span className="pill fa" style={{ marginLeft: 6 }}>Actuel</span>}</span>
              <span>{h.first_seen?.slice(0, 7) ?? '?'} → {h.is_current ? 'auj.' : h.last_seen?.slice(0, 7) ?? '?'}</span></div>
          )) : <div><span className="sub">Aucune équipe connue</span><span /></div>}</div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="btn" onClick={add}>Ajouter au Draft Maker</button>
          {p.vlr_player_id && <a className="btn ghost" href={`https://www.vlr.gg/player/${p.vlr_player_id}`} target="_blank" rel="noreferrer">Profil vlr.gg</a>}
        </div>
      </div>
    </Shell>
  )
}

export function TeamDrawer({ id }: { id: number }) {
  const { data: t, error } = useQuery({ queryKey: ['team', id], queryFn: () => api.team(id) })
  const nav = useNavigate()
  const { close } = useUi()
  if (error) return <Shell><div className="dr-h"><Close /></div><ErrorBox error={error} /></Shell>
  if (!t) return <Shell><div className="dr-h"><Close /></div><Loading /></Shell>
  return (
    <Shell>
      <div className="dr-h"><Close />
        <div className="meta"><Ctry c={t.country_code} />{t.tier && <span className={`pill ${t.tier === 'VCT' ? 'vct' : 'ct'}`}>{t.tier}</span>}
          <span>{t.region ?? 'Région inconnue'}{t.region_rank ? ` · #${t.region_rank} régional` : ''}{t.world_rank ? ` · #${t.world_rank} mondial` : ''}</span></div>
        <div className="ign">{t.name}</div>
        <div className="meta num"><span>Elo {t.elo ?? '—'}</span><span>·</span><span>{t.wins_365 ?? 0}–{t.losses_365 ?? 0} sur 12 mois</span>
          {t.streak_type && <><span>·</span><span>Série {t.streak_length} {t.streak_type === 'W' ? 'V' : 'D'}</span></>}
          <span>·</span><span>dernier match {dShort(t.last_match_date)}</span></div>
        {!t.ranked && <div className="sub" style={{ marginTop: 8 }}>Hors classement : moins de 10 matchs ou inactive depuis plus de 180 jours.</div>}
      </div>
      <div className="dr-b">
        <div><h4>Roster <Src t="players.current_team_id" /></h4>
          {t.roster.length ? <div className="tscroll"><table className="tbl"><thead><tr><th className="l">Joueur</th><th className="l">Rôle</th><th>Rating</th><th>ACS</th><th>KAST</th><th>Forme</th></tr></thead><tbody>
            {t.roster.map(p => <tr key={p.player_id} onClick={() => nav({ search: `?player=${p.player_id}` })}>
              <td className="l"><div className="pcell" style={{ minWidth: 0 }}><Ctry c={p.country_code} /><b>{p.ign}</b></div></td>
              <td className="l"><RoleTag role={p.role} /></td><td className="hl">{f2(p.rating)}</td><td>{f0(p.acs)}</td><td>{fp(p.kast_pct)}</td><td>{f2(p.form5)}</td></tr>)}
          </tbody></table></div> : <div className="sub">Roster inconnu.</div>}
        </div>
        <div><h4>Winrate par map · 12 mois <Src t="match_maps" /></h4>
          {t.maps.map(m => { const wr = m.played ? m.won / m.played : 0.5; return <MBar key={m.map_id} label={m.name} delta={wr - 0.5} scale={0.5} value={<>{m.played ? fp(wr * 100) : '—'} <small>{m.won}/{m.played}</small></>} /> })}
        </div>
        <div><h4>Derniers matchs <Src t="matches" /></h4>
          <div className="card">{t.matches.length ? t.matches.map(m => {
            const home = m.team1_id === id, opp = home ? m.team2_id : m.team1_id, won = m.winner_team_id === id
            return <div className="rrow" key={m.match_id}><span className="nm">{m.winner_team_id ? <WL r={won ? 'W' : 'L'} /> : <span className="wl">=</span>}<span className="sub num">{dShort(m.match_date)}</span>
              <TeamLink id={opp}>{home ? m.team2 : m.team1}</TeamLink></span><b className="num">{home ? m.team1_score : m.team2_score}–{home ? m.team2_score : m.team1_score}</b></div>
          }) : <div className="empty">Aucun match.</div>}</div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="btn" onClick={() => { close(); nav(`/predictions?a=team:${id}`) }}>Prédire un match</button>
        </div>
      </div>
    </Shell>
  )
}

