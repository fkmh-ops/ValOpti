"""Référentiels statiques : agents/rôles, cartes, régions."""

# Nom canonique -> rôle. Les clés « kaggle » sont en minuscules sans ponctuation.
AGENTS: list[tuple[str, str]] = [
    ("Jett", "duelist"), ("Raze", "duelist"), ("Reyna", "duelist"), ("Phoenix", "duelist"),
    ("Yoru", "duelist"), ("Neon", "duelist"), ("Iso", "duelist"), ("Waylay", "duelist"),
    ("Sova", "initiator"), ("Fade", "initiator"), ("Skye", "initiator"), ("Breach", "initiator"),
    ("KAY/O", "initiator"), ("Gekko", "initiator"), ("Tejo", "initiator"),
    ("Omen", "controller"), ("Viper", "controller"), ("Astra", "controller"),
    ("Brimstone", "controller"), ("Harbor", "controller"), ("Clove", "controller"),
    ("Miks", "controller"),
    ("Killjoy", "sentinel"), ("Cypher", "sentinel"), ("Sage", "sentinel"), ("Chamber", "sentinel"),
    ("Deadlock", "sentinel"), ("Vyse", "sentinel"), ("Veto", "sentinel"),
]
# Rôles ajoutés après la maquette, à faire valider par l'équipe
AGENTS_TO_CONFIRM = {"Miks", "Veto"}


def agent_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


AGENT_BY_KEY = {agent_key(n): n for n, _ in AGENTS}

# Vraies cartes Valorant. Tout le reste de game_maps est du bruit de parsing du veto.
REAL_MAPS = {
    "Ascent", "Bind", "Haven", "Split", "Icebox", "Breeze", "Fracture", "Pearl", "Lotus",
    "Sunset", "Abyss", "Corrode", "Summit",
}

REGIONS = ["EMEA", "Americas", "Pacific", "China"]

_AMERICAS = (
    "us ca br mx ar cl co pe uy ve ec bo py cr gt do pr pa hn sv ni cu jm tt bs bb ht gy sr "
    "la-n la-s na latam sx"
).split()
_PACIFIC = "kr jp ph id th vn sg my tw hk mo au nz in pk bd mn kh mm lk np la bn mv ap oce sea".split()
_CHINA = ["cn"]
# Codes neutres : pas d'information de région
UNKNOWN_CODES = {"un", "", "int", "international", "world", "wa"}

_MACRO = {c: "Americas" for c in _AMERICAS}
_MACRO.update({c: "Pacific" for c in _PACIFIC})
_MACRO.update({c: "China" for c in _CHINA})


def macro_region(code: str | None) -> str | None:
    """Code pays / région vlr.gg -> macro-région VCT. None si inconnu."""
    if not code:
        return None
    code = code.strip().lower()
    if code in UNKNOWN_CODES:
        return None
    if code in _MACRO:
        return _MACRO[code]
    if code in ("eu", "emea", "cis", "mena") or len(code) == 2:
        return "EMEA"
    return None
