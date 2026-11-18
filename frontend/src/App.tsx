import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { NavLink, Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import { api } from './api'
import { dLong } from './lib'
import { Ctry, LogoSymbol, useMeta, useUi } from './ui'
import { PlayerDrawer, TeamDrawer } from './pages/Drawers'
import Home from './pages/Home'
import Scouting from './pages/Scouting'
import DraftPage from './pages/Draft'
import Predictions from './pages/Predictions'
import Rankings from './pages/Rankings'

const NAV = [['/', 'Accueil'], ['/scouting', 'Scouting'], ['/draft', 'Draft Maker'], ['/predictions', 'Prédictions'], ['/classement', 'Classement']] as const

function Search() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const { openPlayer, openTeam } = useUi()
  const { data } = useQuery({ queryKey: ['search', q], queryFn: () => api.search(q), enabled: q.trim().length >= 2, staleTime: 60_000 })
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('click', h, true)
    return () => document.removeEventListener('click', h, true)
  }, [])
  return (
    <div className="search" ref={box}>
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="7" cy="7" r="5" /><path d="M11 11l3.5 3.5" /></svg>
      <input type="search" placeholder="Joueur ou équipe" autoComplete="off" aria-label="Rechercher un joueur ou une équipe"
        value={q} onChange={e => { setQ(e.target.value); setOpen(true) }} onKeyDown={e => e.key === 'Escape' && setOpen(false)} />
      {open && q.trim().length >= 2 && (
        <div className="sres">
          {data?.length ? data.map(h => (
            <button key={h.kind + h.id} onClick={() => { setOpen(false); setQ(''); h.kind === 'player' ? openPlayer(h.id) : openTeam(h.id) }}>
              <Ctry c={h.country_code} /><span>{h.label}</span><span className="k">{h.kind === 'team' ? 'Équipe' : h.sub}</span>
            </button>
          )) : <div className="empty">{data ? `Aucun résultat pour « ${q} »` : 'Recherche…'}</div>}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [params] = useSearchParams()
  const loc = useLocation()
  const meta = useMeta()
  const [dev, setDev] = useState(false)
  const { close } = useUi()
  useEffect(() => { window.scrollTo(0, 0) }, [loc.pathname])
  useEffect(() => { document.body.classList.toggle('dev', dev) }, [dev])
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [close])
  const player = Number(params.get('player')) || null
  const team = Number(params.get('team')) || null

  return (
    <>
      <LogoSymbol />
      <header className="top">
        <div className="wrap">
          <NavLink className="brand" to="/" aria-label="ValOpti, accueil">
            <svg aria-hidden="true"><use href="#logo" /></svg>
            <span className="wordmark">VAL<span className="o">O</span><span className="r">PTI</span></span>
          </NavLink>
          <nav className="nav">
            {NAV.map(([to, l]) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'on' : '')}>{l}</NavLink>)}
          </nav>
          <Search />
        </div>
      </header>
      <main className="wrap">
        <div className="view">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/scouting" element={<Scouting />} />
            <Route path="/draft" element={<DraftPage />} />
            <Route path="/predictions" element={<Predictions />} />
            <Route path="/classement" element={<Rankings />} />
            <Route path="*" element={<div className="card empty">Page introuvable.</div>} />
          </Routes>
        </div>
      </main>
      <footer>
        <div className="wrap">
          <span>ValOpti · The Draft Maker — données vlr.gg nettoyées{meta ? `, à jour au ${dLong(meta.snapshot_date)}` : ''}. Agents : dataset Kaggle VCT. Modèle {meta?.model_version ?? '…'}.</span>
          <button type="button" aria-pressed={dev} onClick={() => setDev(d => !d)}>{dev ? 'Masquer les tables SQL' : 'Afficher les tables SQL'}</button>
        </div>
      </footer>
      {(player || team) && <div className="scrim" onClick={close} />}
      {player && <PlayerDrawer id={player} />}
      {!player && team && <TeamDrawer id={team} />}
    </>
  )
}
