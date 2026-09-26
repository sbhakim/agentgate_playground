"""Load and validate the bundled fixtures, and resolve replay aliases."""

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .schemas import LABEL_ORDER, MAX_ATTACK_CHARS, TOOL_ARGS, Policy

# Find fixtures even when the demo is launched from a different directory.
FIXTURES_DIR = Path(os.environ.get("AGENTGATE_FIXTURES", Path(__file__).resolve().parents[2] / "fixtures"))


@dataclass
class Catalog:
    documents: dict      # id -> {id, title, label, body, injection?}
    attacks: list        # preset visitor attacks for live mode
    contacts: dict       # email -> {email, name, class}
    presets: dict        # name -> policy fields
    scenarios: dict      # id -> scenario

    @property
    def doc_labels(self) -> dict[str, str]:
        return {d["id"]: d["label"] for d in self.documents.values()}

    @property
    def contact_classes(self) -> dict[str, str]:
        return {c["email"]: c["class"] for c in self.contacts.values()}


def _check(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(f"Invalid fixture: {message}")


def _read(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    docs = {d["id"]: d for d in _read("documents.json")["documents"]}
    pol = _read("policies.json")
    contacts = {c["email"]: c for c in pol["contacts"]}
    scenarios = {s["id"]: s for s in _read("scenarios.json")["scenarios"]}

    # A misspelled label should stop startup, not make a document public.
    for d in docs.values():
        _check(d["label"] in LABEL_ORDER, f"bad label on {d['id']}")
    for c in contacts.values():
        _check(c["class"] in ("internal", "external"), f"bad class on {c['email']}")
    for name, p in pol["presets"].items():
        _check(set(p["allowed_documents"]) <= docs.keys(), f"preset {name}: unknown document")
        _check(set(p["allowed_recipients"]) <= contacts.keys(), f"preset {name}: unknown recipient")
    for s in scenarios.values():
        _check(s["preset"] in pol["presets"], f"scenario {s['id']}: unknown preset")
        for v in s["variants"]:
            _check(v["document"] in docs, f"{s['id']}/{v['id']}: unknown preview document")
            _check(len(v["replay"]) == len(v["expected"]), f"{s['id']}/{v['id']}: expected length")
            for step in v["replay"]:
                _check(step["tool"] in TOOL_ARGS, f"{s['id']}/{v['id']}: unknown tool")
            _check(set(v["expected"]) <= {"allow", "deny", "require_approval"}, f"{s['id']}/{v['id']}: bad expected value")

    attacks = _read("attacks.json")["attacks"]
    for a in attacks:
        _check(0 < len(a["text"]) <= MAX_ATTACK_CHARS, f"attack {a['id']}: text length")

    return Catalog(docs, attacks, contacts, pol["presets"], scenarios)


def get_variant(scenario_id: str, variant_id: str) -> tuple[dict, dict]:
    scenario = load_catalog().scenarios[scenario_id]
    variant = next(v for v in scenario["variants"] if v["id"] == variant_id)
    return scenario, variant


def preset_policy(name: str) -> Policy:
    return Policy(version=1, **load_catalog().presets[name])


def resolve_aliases(args: dict, aliases: dict[str, str]) -> dict:
    """Replace known aliases; a denied draft stays unresolved and cannot be sent."""
    return {k: aliases.get(v, v) if isinstance(v, str) else v for k, v in args.items()}
