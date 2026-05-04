"""Tests for SkillLoader against the existing journal YAMLs."""
from __future__ import annotations

from paper_agent.skills import SkillLoader


def test_discovers_existing_yamls():
    loader = SkillLoader()
    keys = loader.list_skills()
    # at least the ones currently committed at repo root
    expected = {"nature", "science", "plos_one", "pnas",
                "scientific_reports", "nature_communications"}
    assert expected.issubset(set(keys)), f"missing some: {expected - set(keys)}"


def test_load_nature_rules():
    skill = SkillLoader().load("nature")
    assert skill.name == "Nature"
    assert skill.structure_rules, "nature.yaml should have structure_rules"
    assert skill.content_rules
    assert skill.compliance_rules
    assert skill.language_rules
    assert "Abstract" in skill.required_sections()
