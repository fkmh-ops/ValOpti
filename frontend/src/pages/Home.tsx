import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api, type SlimPlayer } from '../api'
import { ROLE_FR, dLong, dShort, dTime, f0, f2, tagOf } from '../lib'
import { Ctry, ErrorBox, Loading, Src, StatusPill, TeamLink, useUi } from '../ui'

function PlayerSide({ list, value }: { list: SlimPlayer[]; value: (p: SlimPlayer) => [string, string] }) {
  const { openPlayer } = useUi()
  return <div className="side-list">{list.map((p, i) => {
    const [v, sub] = value(p)
    return <button key={p.player_id} className="side-row" onClick={() => openPlayer(p.player_id)}>
      <span className="n">{i + 1}</span><span className="nm"><Ctry c={p.country_code} /><span>{p.ign}</span></span>
      <span className="v">{v}<small>{sub}</small></span></button>
  })}</div>
}

export default function Home() {
  const { data, error } = useQuery({ queryKey: ['home'], queryFn: api.home })
  const { openTeam } = useUi()
  const nav = useNavigate()
  if (error) return <ErrorBox error={error} />
  if (!data) return <Loading />
  const c = data.counts
  return <>
    <section className="hero">
      <div>
        <div className="h-eyebrow">The Draft Maker</div>
        <h1 className="h1">Recrutez sur des chiffres que vous pouvez défendre.</h1>
        <p>Scouting des joueurs pros et Challengers, simulation de compositions et prédictions de matchs. Chaque note est expliquée, pour justifier un recrutement devant votre staff ou vos investisseurs.</p>
        <div className="ctas"><Link className="btn" to="/draft">Ouvrir le Draft Maker</Link><Link className="btn ghost" to="/scouting">Scouter des joueurs</Link></div>
        <div className="kpis num">
          <div><b>{c.players_tracked.toLocaleString('fr-FR')}</b><span>Joueurs actifs · 180 j</span></div>
          <div><b>{c.free_agents.toLocaleString('fr-FR')}</b><span>Sans équipe</span></div>
          <div><b>{c.teams_active.toLocaleString('fr-FR')}</b><span>Équipes classées</span></div>
          <div><b>{c.maps_analysed.toLocaleString('fr-FR')}</b><span>Maps analysées</span></div>
        </div>
      </div>
      <svg className="hero-mark" viewBox="200 10 540 510" aria-hidden="true"><use href="#logo" /></svg>
    </section>
    <div className="grid-main">
      <div className="stack">
        <section>
          <div className="sec-h"><h2 className="h2">Matchs programmés</h2><span className="sub">Au {dLong(data.snapshot_date)}, date des dernières données <Src t="matches · status = upcoming" /></span></div>
          {data.upcoming.length ? <div className="up-grid">{data.upcoming.map(u => {
            const pa = u.p_team1 === null ? null : Math.round(u.p_team1 * 100)
            return <button key={u.match_id} className="up" onClick={() => nav(`/predictions?a=team:${u.team1_id}&b=team:${u.team2_id}`)}>
              <div className="meta"><span>{u.event}{u.status === 'live' ? ' · LIVE' : ''}</span><span className="num">{dTime(u.scheduled_at)}</span></div>
              <div className="teams"><div className="tm"><b>{tagOf(u.team1, u.tag1)}</b><small>{u.team1}</small></div><span className="vs">BO3</span><div className="tm r"><b>{tagOf(u.team2, u.tag2)}</b><small>{u.team2}</small></div></div>
              {pa !== null && <><div className="pct num"><span>{pa}%</span><span>{100 - pa}%</span></div>
                <div className="pbar"><i style={{ width: `${pa}%` }} /><i style={{ width: `${100 - pa}%` }} /></div></>}
              <span className="hint">Voir la prédiction et le veto →</span></button>
          })}</div> : <div className="card empty">Aucun match programmé avec deux équipes connues.</div>}
        </section>
        <section>
          <div className="sec-h"><h2 className="h2">Résultats récents · VCT</h2><Src t="matches ⨝ match_maps" /></div>
          <div className="card">{data.recent.map(m => {
            const w1 = m.winner_team_id === m.team1_id
            return <div key={m.match_id} className="res-row">
              <span className="d num">{dShort(m.match_date)}</span>
              <div className="ev">{m.event}{m.stage ? ` · ${m.stage}` : ''}</div>
              <span />
              <div className={`t ${w1 ? 'win' : 'lose'}`}><span><TeamLink id={m.team1_id}>{m.team1}</TeamLink></span></div>
              <div className="sc num"><span className={w1 ? 'w' : 'l'}>{m.team1_score}</span><span className="l">:</span><span className={w1 ? 'l' : 'w'}>{m.team2_score}</span></div>
              <div className={`t r ${w1 ? 'lose' : 'win'}`}><span><TeamLink id={m.team2_id}>{m.team2}</TeamLink></span></div>
              <div className="maps num">{m.maps.map((mm, i) => <span key={i}>{mm.map} {mm.s1}–{mm.s2}</span>)}</div>
            </div>
          })}</div>
        </section>
      </div>
      <aside className="stack">
        <div className="card"><div className="card-h"><h3>Classement mondial</h3><Link className="sub" to="/classement">Tout voir →</Link></div>
          <div className="side-list">{data.top_teams.map((t, i) => <button key={t.team_id} className="side-row" onClick={() => openTeam(t.team_id)}>
            <span className="n">{i + 1}</span><span className="nm"><Ctry c={t.country_code} /><span>{t.name}</span></span>
            <span className="v">{t.elo}<small>{t.wins_365}–{t.losses_365}</small></span></button>)}</div></div>
        <div className="card"><div className="card-h"><h3>Sans équipe à suivre</h3><Src t="player_profile · status = free_agent" /></div>
          <PlayerSide list={data.free_agents} value={p => [f2(p.rating), (p.role ? ROLE_FR[p.role] : '') + (p.last_team_name ? ` · ex-${p.last_team_name}` : '')]} />
          <div className="method">Joueur dont la dernière équipe a disputé au moins 2 matchs sans lui. Statut déduit des feuilles de match, à vérifier avant contact.</div></div>
        <div className="card"><div className="card-h"><h3>Meilleurs ratings · 180 j</h3><Src t="player_stats_snapshot" /></div>
          <div className="side-list">{data.top_players.map((p, i) => <PlayerTop key={p.player_id} p={p} i={i} />)}</div></div>
      </aside>
    </div>
  </>
}

function PlayerTop({ p, i }: { p: SlimPlayer; i: number }) {
  const { openPlayer } = useUi()
  return <button className="side-row" onClick={() => openPlayer(p.player_id)}>
    <span className="n">{i + 1}</span><span className="nm"><Ctry c={p.country_code} /><span>{p.ign}</span><StatusPill p={p} /></span>
    <span className="v">{f2(p.rating)}<small>{f0(p.acs)} ACS</small></span></button>
}
