export type Role = 'duelist' | 'initiator' | 'controller' | 'sentinel' | 'flex'
export type StatKey = 'rating' | 'acs' | 'kd' | 'kast_pct' | 'adr' | 'kpr' | 'apr' | 'fkpr' | 'fdpr' | 'hs_pct' | 'clutch_per100'

export interface Agent { agent_id: number; name: string; role: Role }
export interface GameMap { map_id: number; name: string }

export type Weights = Partial<Record<'d_elo' | 'd_map' | 'd_wr' | 'd_form', number>>
export interface Metrics { n: number; log_loss: number; brier: number; accuracy: number }

export interface Meta {
  snapshot_date: string
  model_version: string
  model_weights: Weights
  model_backtest: { split?: string; series_test?: Metrics; series_test_current?: Metrics; map_test?: Metrics }
  map_pool: GameMap[]
  agents: Agent[]
  regions: string[]
  periods: number[]
  default_period: number
  elo_reference: number
  counts: { players_tracked: number; free_agents: number; teams_active: number; maps_analysed: number }
}

export type Stats = Record<StatKey, number | null>

export interface PlayerRow extends Stats {
  player_id: number
  ign: string
  real_name: string | null
  country_code: string | null
  region: string | null
  status: 'active' | 'free_agent' | 'inactive' | null
  role: Role | null
  main_role: Role | null
  team_id: number | null
  team_name: string | null
  team_tag: string | null
  tier: string | null
  circuit: string | null
  last_team_id: number | null
  last_team_name: string | null
  agents: number[]
  rounds_played: number
  maps_played: number
  rookie: boolean
  is_free_agent: boolean
  pct: Record<StatKey, number | null>
}

export interface TeamRow {
  team_id: number
  name: string
  short_tag: string | null
  country_code: string | null
  logo_url: string | null
  region: string | null
  tier: string
  elo: number
  elo_matches: number
  wins_365: number
  losses_365: number
  last_match_date: string
  streak_type: 'W' | 'L' | null
  streak_length: number | null
  last5: string
  world_rank: number
  region_rank: number | null
  best_map?: { map: string; winrate: number; played: number } | null
  vlr_ranking?: { region: string; rank: number; rating: number } | null
}

export interface MapScore { map: string; s1: number; s2: number }
export interface MatchRow {
  match_id: number
  match_date: string
  event: string | null
  stage?: string | null
  team1_id: number
  team2_id: number
  team1: string
  team2: string
  team1_score: number
  team2_score: number
  winner_team_id: number | null
  maps: MapScore[]
}

export interface UpcomingMatch {
  match_id: number
  scheduled_at: string
  status: string
  event: string | null
  stage: string | null
  team1_id: number
  team1: string
  tag1: string | null
  team2_id: number
  team2: string
  tag2: string | null
  p_team1: number | null
}

export type SlimPlayer = Pick<PlayerRow, 'player_id' | 'ign' | 'country_code' | 'role' | 'rating' | 'acs' | 'team_tag' |
  'team_name' | 'is_free_agent' | 'rookie' | 'last_team_name' | 'rounds_played'>

export interface Home {
  upcoming: UpcomingMatch[]
  recent: MatchRow[]
  top_teams: TeamRow[]
  free_agents: SlimPlayer[]
  top_players: SlimPlayer[]
  counts: Meta['counts']
  snapshot_date: string
}

export interface AgentStat {
  agent_id: number; name: string; role: Role; usage: number; rounds: number; rating: number | null
  acs: number | null; kd: number | null; adr: number | null; kast_pct: number | null; maps: number
}

export interface PlayerDetail {
  player_id: number
  ign: string
  real_name: string | null
  country_code: string | null
  total_winnings_usd: number | null
  vlr_player_id: number | null
  region: string | null
  status: PlayerRow['status']
  first_seen: string | null
  last_seen: string | null
  maps_total: number | null
  main_role: Role | null
  role: Role | null
  team_id: number | null
  team_name: string | null
  team_tag: string | null
  last_team_id: number | null
  last_team_name: string | null
  period: number
  rookie: boolean
  is_free_agent: boolean
  stats: (Stats & { rounds_played: number; maps_played: number; pct_role: Record<StatKey, number | null>; pct_all: Record<StatKey, number | null> }) | null
  agents: AgentStat[]
  form: { match_date: string; map_name: string | null; rating: number; acs: number; agent_id: number | null }[]
  maps: { map_id: number; name: string; maps: number; rating: number; acs: number; won: number }[]
  career: { team_id: number; team_name: string; first_seen: string | null; last_seen: string | null; is_current: boolean }[]
}

export interface TeamDetail {
  team_id: number
  name: string
  short_tag: string | null
  country_code: string | null
  region: string | null
  tier: string | null
  elo: number | null
  wins_365: number | null
  losses_365: number | null
  streak_type: 'W' | 'L' | null
  streak_length: number | null
  last_match_date: string | null
  world_rank: number | null
  region_rank: number | null
  ranked: boolean
  roster: { player_id: number; ign: string; country_code: string | null; role: Role | null; rating: number | null; acs: number | null; kast_pct: number | null; rounds_played: number; form5: number | null }[]
  maps: { map_id: number; name: string; played: number; won: number }[]
  matches: MatchRow[]
  vlr_ranking: { region: string; rank: number; rating: number } | null
}

export interface Slot { player_id: number | null; agent_id: number | null }
export interface Alert { level: 'crit' | 'warn' | 'info' | 'ok'; text: string }
export interface DraftAnalysis {
  score: number
  parts: { firepower: number; entry: number; utility: number; clutch: number; balance: number }
  alerts: Alert[]
  maps: Record<string, number>
  avg: number
  players: SlimPlayer[]
}

export interface Composition {
  composition_id: number
  name: string
  score: number | null
  created_at: string
  updated_at: string
  notes: string | null
  slots: (Slot & { ign: string | null })[]
  updated?: boolean
}

export type SideIn =
  | { kind: 'team'; team_id: number }
  | { kind: 'composition'; composition_id: number }
  | { kind: 'draft'; name: string; slots: Slot[] }

export interface PredSide {
  key: string
  name: string
  tag: string
  elo: number
  elo_label: string
  form: number
  composition: boolean
  team: (TeamRow & { region: string | null; tier: string | null }) | null
  players: { player: SlimPlayer & { kast_pct: number | null }; agent_id: number | null }[]
}

export interface Prediction {
  p_a: number
  best_of: 1 | 3 | 5
  distribution: { score: string; a: number; b: number; p: number }[]
  likely_score: string
  veto: { side: 'a' | 'b' | null; action: 'ban' | 'pick' | 'decider'; map_id: number; p_a: number | null }[]
  factors: { level: number; map_pool: number; form: number }
  a: PredSide
  b: PredSide
  h2h: MatchRow[]
  model_version: string
  weights: Weights
}

export interface SearchHit { kind: 'team' | 'player'; id: number; label: string; sub: string; country_code: string | null; active: boolean }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch('/api' + path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) {
    let msg = r.statusText
    try {
      const j = await r.json()
      msg = typeof j.detail === 'string' ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join(', ') : msg
    } catch { /* corps non JSON */ }
    throw new ApiError(r.status, msg)
  }
  return r.status === 204 ? (undefined as T) : r.json()
}

const qs = (o: Record<string, string | number | null | undefined>) => {
  const p = new URLSearchParams()
  Object.entries(o).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== '' && v !== 'all') p.set(k, String(v)) })
  const s = p.toString()
  return s ? '?' + s : ''
}

export interface PlayerQuery {
  period?: number; q?: string; region?: string; role?: string; status?: string; tier?: string
  min_rounds?: number; sort?: string; dir?: 'asc' | 'desc'; limit?: number; offset?: number
}

export const api = {
  meta: () => req<Meta>('/meta'),
  home: () => req<Home>('/home'),
  search: (q: string, kind?: 'team' | 'player', limit = 8) => req<SearchHit[]>('/search' + qs({ q, kind, limit })),
  rankings: (region: string, limit = 100) => req<TeamRow[]>('/rankings' + qs({ region, limit })),
  players: (q: PlayerQuery) => req<{ total: number; period: number; items: PlayerRow[] }>('/players' + qs({ ...q })),
  player: (id: number, period?: number) => req<PlayerDetail>(`/players/${id}` + qs({ period })),
  team: (id: number) => req<TeamDetail>(`/teams/${id}`),
  analyse: (slots: Slot[], period?: number) => req<DraftAnalysis>('/draft/analyse', { method: 'POST', body: JSON.stringify({ slots, period }) }),
  compositions: () => req<Composition[]>('/compositions'),
  saveComposition: (name: string, slots: Slot[]) => req<Composition>('/compositions', { method: 'POST', body: JSON.stringify({ name, slots }) }),
  deleteComposition: (id: number) => req<void>(`/compositions/${id}`, { method: 'DELETE' }),
  predict: (a: SideIn, b: SideIn, best_of: number) => req<Prediction>('/predict', { method: 'POST', body: JSON.stringify({ a, b, best_of }) }),
}
