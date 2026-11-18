-- =====================================================================
--  ValOpti — requêtes du site + tables à ajouter
--  À exécuter après schema.sql. Compatible SQLite 3.25+ / PostgreSQL 13+
--  (paramètres nommés :param, à remplacer par $1, $2... côté PostgreSQL)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. PRÉREQUIS : rôles des agents (colonne agents.role « à renseigner »)
--    Le Draft Maker et les alertes de composition en dépendent.
-- ---------------------------------------------------------------------
UPDATE agents SET role = 'duelist'    WHERE name IN ('Jett','Raze','Reyna','Phoenix','Yoru','Neon','Iso','Waylay');
UPDATE agents SET role = 'initiator'  WHERE name IN ('Sova','Fade','Skye','Breach','KAY/O','Gekko','Tejo');
UPDATE agents SET role = 'controller' WHERE name IN ('Omen','Viper','Astra','Brimstone','Harbor','Clove');
UPDATE agents SET role = 'sentinel'   WHERE name IN ('Killjoy','Cypher','Sage','Chamber','Deadlock','Vyse');

-- ---------------------------------------------------------------------
-- 1. NOUVELLES TABLES : compositions et prédictions
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compositions (
    composition_id INTEGER PRIMARY KEY,
    name           TEXT      NOT NULL,
    owner_email    TEXT,                          -- recruteur / compte client
    created_at     TIMESTAMP NOT NULL,
    updated_at     TIMESTAMP NOT NULL,
    score          INTEGER,                       -- note ValOpti au moment de la sauvegarde (0-100)
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS composition_slots (
    composition_id INTEGER NOT NULL REFERENCES compositions(composition_id) ON DELETE CASCADE,
    slot_index     INTEGER NOT NULL CHECK (slot_index BETWEEN 0 AND 4),
    slot_role      TEXT    NOT NULL CHECK (slot_role IN ('duelist','initiator','controller','sentinel','flex')),
    player_id      INTEGER REFERENCES players(player_id),
    agent_id       INTEGER REFERENCES agents(agent_id),
    PRIMARY KEY (composition_id, slot_index),
    UNIQUE (composition_id, player_id)
);

-- Journal des prédictions : permet de mesurer la précision du modèle a posteriori
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id     INTEGER PRIMARY KEY,
    created_at        TIMESTAMP NOT NULL,
    match_id          INTEGER REFERENCES matches(match_id),        -- NULL pour une simulation libre
    side_a_team_id    INTEGER REFERENCES teams(team_id),
    side_a_comp_id    INTEGER REFERENCES compositions(composition_id),
    side_b_team_id    INTEGER REFERENCES teams(team_id),
    side_b_comp_id    INTEGER REFERENCES compositions(composition_id),
    best_of           INTEGER NOT NULL CHECK (best_of IN (1,3,5)),
    p_side_a          REAL    NOT NULL,                            -- probabilité de victoire de A sur la série
    predicted_score   TEXT,                                        -- '2-1'
    model_version     TEXT    NOT NULL,                            -- ex. 'elo-map-form-v1'
    factors_json      TEXT,                                        -- contributions (niveau, map pool, forme)
    CHECK (side_a_team_id IS NOT NULL OR side_a_comp_id IS NOT NULL),
    CHECK (side_b_team_id IS NOT NULL OR side_b_comp_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS prediction_maps (
    prediction_id INTEGER NOT NULL REFERENCES predictions(prediction_id) ON DELETE CASCADE,
    step          INTEGER NOT NULL,
    action        TEXT    NOT NULL CHECK (action IN ('ban','pick','decider')),
    side          TEXT    CHECK (side IN ('a','b')),               -- NULL pour le decider
    map_id        INTEGER NOT NULL REFERENCES game_maps(map_id),
    p_side_a      REAL,                                            -- NULL pour une map bannie
    PRIMARY KEY (prediction_id, step)
);

-- ---------------------------------------------------------------------
-- 2. SCOUTING — tableau joueurs (dernier snapshot 90 j)
--    filtres : :region (ou NULL), :role (ou NULL), :free_agents_only (0/1), :min_rounds
-- ---------------------------------------------------------------------
-- name: scouting_players
WITH last_snap AS (
    SELECT MAX(snapshot_date) AS d FROM player_stats_snapshot WHERE timespan_days = 90
),
main_role AS (                       -- rôle principal = rôle de l'agent le plus joué
    SELECT player_id, role FROM (
        SELECT pas.player_id, a.role,
               ROW_NUMBER() OVER (PARTITION BY pas.player_id ORDER BY pas.usage DESC) AS rn
        FROM player_agent_stats pas JOIN agents a ON a.agent_id = pas.agent_id
    ) x WHERE rn = 1
)
SELECT  p.player_id, p.ign, p.real_name, p.country_code,
        t.team_id, t.name AS team_name, t.short_tag,
        (p.current_team_id IS NULL)          AS is_free_agent,
        mr.role                              AS main_role,
        s.agents, s.rounds_played,
        s.rating, s.acs, s.kd, s.kast_pct, s.adr, s.kpr, s.apr, s.fkpr, s.fdpr, s.hs_pct, s.clutch_pct
FROM player_stats_snapshot s
JOIN last_snap ls       ON ls.d = s.snapshot_date
JOIN players p          ON p.player_id = s.player_id
LEFT JOIN teams t       ON t.team_id = p.current_team_id
LEFT JOIN main_role mr  ON mr.player_id = p.player_id
WHERE s.timespan_days = 90
  AND (:region IS NULL OR s.region = :region)
  AND (:role   IS NULL OR mr.role = :role)
  AND (:free_agents_only = 0 OR p.current_team_id IS NULL)
  AND s.rounds_played >= :min_rounds
ORDER BY s.rating DESC;

-- ---------------------------------------------------------------------
-- 3. FICHE JOUEUR
-- ---------------------------------------------------------------------
-- name: player_agent_pool
SELECT a.name, a.role, pas.usage, pas.rounds, pas.rating, pas.acs, pas.kd, pas.adr, pas.kast_pct
FROM player_agent_stats pas JOIN agents a ON a.agent_id = pas.agent_id
WHERE pas.player_id = :player_id
ORDER BY pas.usage DESC;

-- name: player_rating_by_map
SELECT gm.name AS map_name, COUNT(*) AS maps_played,
       AVG(s.rating) AS avg_rating, AVG(s.acs) AS avg_acs
FROM player_map_stats s
JOIN match_maps mm ON mm.match_map_id = s.match_map_id
JOIN game_maps gm  ON gm.map_id = mm.map_id
WHERE s.player_id = :player_id
GROUP BY gm.name
ORDER BY avg_rating DESC;

-- name: player_form_last10   (sparkline « Forme · 10 maps »)
SELECT m.match_date, gm.name AS map_name, s.rating, s.acs, ag.name AS agent
FROM player_map_stats s
JOIN match_maps mm ON mm.match_map_id = s.match_map_id
JOIN matches m     ON m.match_id = mm.match_id
LEFT JOIN game_maps gm ON gm.map_id = mm.map_id
LEFT JOIN agents ag    ON ag.agent_id = s.agent_id
WHERE s.player_id = :player_id AND s.rating IS NOT NULL
ORDER BY m.match_date DESC, mm.map_number DESC
LIMIT 10;

-- name: player_career
SELECT t.name AS team_name,
       MIN(ptm.first_seen_date) AS first_seen_date,
       MAX(ptm.last_seen_date)  AS last_seen_date,
       MAX(CASE WHEN ptm.is_current THEN 1 ELSE 0 END) AS is_current
FROM player_team_membership ptm JOIN teams t ON t.team_id = ptm.team_id
WHERE ptm.player_id = :player_id
GROUP BY t.team_id, t.name                          -- plusieurs sources par équipe : on fusionne
ORDER BY is_current DESC, last_seen_date DESC;

-- ---------------------------------------------------------------------
-- 4. CLASSEMENT ET FICHE ÉQUIPE
-- ---------------------------------------------------------------------
-- name: rankings_latest   (:region NULL = toutes)
SELECT r.rank, t.team_id, t.name, t.short_tag, t.country_code, r.region,
       r.rating, r.wins, r.losses, r.streak_type, r.streak_length, r.earnings_usd
FROM team_rankings r JOIN teams t ON t.team_id = r.team_id
WHERE r.snapshot_date = (SELECT MAX(snapshot_date) FROM team_rankings)
  AND (:region IS NULL OR r.region = :region)
ORDER BY r.rating DESC;

-- name: team_last5   (pastilles V/D)
SELECT m.match_id, m.match_date,
       CASE WHEN m.winner_team_id = :team_id THEN 'W' ELSE 'L' END AS result
FROM matches m
WHERE m.status = 'final' AND :team_id IN (m.team1_id, m.team2_id)
ORDER BY m.match_date DESC
LIMIT 5;

-- name: team_map_winrate   (la vue v_team_map_record existe déjà)
SELECT map_name, maps_played, maps_won, 1.0 * maps_won / maps_played AS winrate
FROM v_team_map_record WHERE team_id = :team_id
ORDER BY winrate DESC;

-- ---------------------------------------------------------------------
-- 5. ACCUEIL
-- ---------------------------------------------------------------------
-- name: upcoming_matches
SELECT m.match_id, m.scheduled_at, COALESCE(e.name, m.event_label) AS event, m.stage,
       t1.team_id AS team1_id, t1.name AS team1, t1.short_tag AS tag1,
       t2.team_id AS team2_id, t2.name AS team2, t2.short_tag AS tag2
FROM matches m
LEFT JOIN events e ON e.event_id = m.event_id
JOIN teams t1 ON t1.team_id = m.team1_id
JOIN teams t2 ON t2.team_id = m.team2_id
WHERE m.status = 'upcoming'
ORDER BY m.scheduled_at
LIMIT 6;

-- name: recent_results
SELECT m.match_id, m.match_date, COALESCE(e.name, m.event_label) AS event,
       t1.name AS team1, m.team1_score, m.team2_score, t2.name AS team2, m.winner_team_id,
       (SELECT GROUP_CONCAT(gm.name || ' ' || mm.team1_score || '-' || mm.team2_score, ' · ')
          FROM match_maps mm JOIN game_maps gm ON gm.map_id = mm.map_id
         WHERE mm.match_id = m.match_id) AS maps       -- PostgreSQL : STRING_AGG(..., ' · ' ORDER BY mm.map_number)
FROM matches m
LEFT JOIN events e ON e.event_id = m.event_id
JOIN teams t1 ON t1.team_id = m.team1_id
JOIN teams t2 ON t2.team_id = m.team2_id
WHERE m.status = 'final'
ORDER BY m.match_date DESC
LIMIT 7;

-- ---------------------------------------------------------------------
-- 6. ENTRÉES DU MODÈLE DE PRÉDICTION (par équipe)
--    Δ_map = 0,6 × (rating_A − rating_B)
--          + 300 × (winrate_lissé_A − winrate_lissé_B)
--          + 500 × (forme_A − forme_B)
--    p_map = 1 / (1 + 10^(−Δ/400))
-- ---------------------------------------------------------------------
-- name: model_team_rating
SELECT r.team_id, r.rating
FROM team_rankings r
WHERE r.team_id = :team_id
ORDER BY r.snapshot_date DESC
LIMIT 1;

-- name: model_team_map_winrate   (lissage bayésien : +2 victoires / +4 maps)
SELECT gm.map_id, gm.name,
       COALESCE(v.maps_won, 0)    AS won,
       COALESCE(v.maps_played, 0) AS played,
       (COALESCE(v.maps_won, 0) + 2.0) / (COALESCE(v.maps_played, 0) + 4.0) AS winrate_smoothed
FROM game_maps gm
LEFT JOIN v_team_map_record v ON v.map_name = gm.name AND v.team_id = :team_id;

-- name: model_team_form   (rating moyen du roster actuel sur ses 5 dernières maps)
WITH roster AS (
    SELECT player_id FROM v_player_latest_team WHERE team_id = :team_id
),
last_maps AS (
    SELECT s.player_id, s.rating,
           ROW_NUMBER() OVER (PARTITION BY s.player_id ORDER BY m.match_date DESC, mm.map_number DESC) AS rn
    FROM player_map_stats s
    JOIN match_maps mm ON mm.match_map_id = s.match_map_id
    JOIN matches m     ON m.match_id = mm.match_id
    WHERE s.player_id IN (SELECT player_id FROM roster) AND s.rating IS NOT NULL
)
SELECT AVG(rating) AS form_rating FROM last_maps WHERE rn <= 5;
