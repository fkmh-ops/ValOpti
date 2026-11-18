from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["duelist", "initiator", "controller", "sentinel", "flex"]


class Slot(BaseModel):
    player_id: int | None = None
    agent_id: int | None = None


class DraftIn(BaseModel):
    slots: list[Slot] = Field(min_length=5, max_length=5)
    period: int = 180

    @field_validator("slots")
    @classmethod
    def unique_players(cls, v: list[Slot]):
        ids = [s.player_id for s in v if s.player_id]
        if len(ids) != len(set(ids)):
            raise ValueError("un joueur ne peut occuper qu'un slot")
        return v


class CompositionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slots: list[Slot] = Field(min_length=5, max_length=5)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def strip(cls, v: str):
        v = v.strip()
        if not v:
            raise ValueError("nom vide")
        return v

    @field_validator("slots")
    @classmethod
    def unique_players(cls, v: list[Slot]):
        return DraftIn.unique_players(v)


class SideIn(BaseModel):
    """Une équipe existante, une composition sauvegardée, ou la composition en cours (non sauvegardée)."""
    kind: Literal["team", "composition", "draft"]
    team_id: int | None = None
    composition_id: int | None = None
    name: str | None = None
    slots: list[Slot] | None = None


class PredictIn(BaseModel):
    a: SideIn
    b: SideIn
    best_of: Literal[1, 3, 5] = 3
    save: bool = False   # journalise la prédiction (tables predictions / prediction_maps)
