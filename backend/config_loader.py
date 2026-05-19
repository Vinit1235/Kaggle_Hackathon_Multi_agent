"""
config_loader.py: Dynamic loader for domain configs, prompts, and user preferences.
Per SOP Section 5.3: Prompts are NEVER hardcoded — loaded from files at runtime.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from schemas import DomainConfig, DomainType, TeamMember

BASE_DIR = Path(__file__).parent
DOMAINS_DIR = BASE_DIR / "domains"
PROMPTS_DIR = BASE_DIR / "prompts"
PROJECT_ROOT = BASE_DIR.parent


class ConfigLoader:
    """Loads and caches domain configs, agent prompts, and user preferences."""

    def __init__(self):
        self._domain_cache: dict[str, dict] = {}
        self._prompt_cache: dict[str, str] = {}
        self._user_preferences: dict[str, Any] = {}

    def load_domain_config(self, domain: DomainType) -> DomainConfig:
        """Load a domain config JSON file into a structured DomainConfig."""
        domain_key = domain.value
        config_path = DOMAINS_DIR / f"{domain_key}.json"

        if not config_path.exists():
            raise FileNotFoundError(f"Domain config not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self._domain_cache[domain_key] = raw

        team_roles = [
            TeamMember(role=r["role"], model=r["model"], goal=r["goal"])
            for r in raw["team_roles"]
        ]
        config = DomainConfig(
            description=raw["description"],
            team_roles=team_roles,
            workflow=raw["workflow"],
        )
        logger.info(f"Loaded domain config: {domain_key} ({len(team_roles)} agents)")
        return config

    def get_raw_domain_config(self, domain: DomainType) -> dict:
        """Get the full raw JSON config including model params."""
        domain_key = domain.value
        if domain_key not in self._domain_cache:
            self.load_domain_config(domain)
        return self._domain_cache[domain_key]

    def list_available_domains(self) -> list[str]:
        if not DOMAINS_DIR.exists():
            return []
        return [f.stem for f in DOMAINS_DIR.glob("*.json")]

    def get_agent_model_config(self, domain: DomainType, agent_role: str) -> dict:
        """Get model-specific params for a particular agent in a domain."""
        raw = self.get_raw_domain_config(domain)
        for role_config in raw["team_roles"]:
            if role_config["role"] == agent_role:
                return {
                    "model": role_config.get("model", "gemini-2.0-flash"),
                    "temperature": role_config.get("temperature", 0.7),
                    "max_tokens": role_config.get("max_tokens", 2048),
                    "system_prompt_file": role_config.get("system_prompt_file", "prompts/worker_agent.md"),
                }
        
        # Fallback for framework-level core agents
        if agent_role in ["Lead", "Critic", "Synthesizer"]:
            prompt_files = {
                "Lead": "prompts/lead_agent.md",
                "Critic": "prompts/critic_agent.md",
                "Synthesizer": "prompts/worker_agent.md" # fallback or actual synthesizer prompt
            }
            return {
                "model": "gemini-2.5-flash",  # Stronger model for core roles
                "temperature": 0.5,
                "max_tokens": 4096,
                "system_prompt_file": prompt_files.get(agent_role, "prompts/worker_agent.md")
            }

        raise ValueError(f"Agent role '{agent_role}' not found in domain '{domain.value}'")

    def load_prompt(self, prompt_file: str, context: Optional[dict] = None) -> str:
        """Load a prompt from markdown file and inject context variables."""
        prompt_path = BASE_DIR / prompt_file
        if not prompt_path.exists():
            logger.warning(f"Prompt file not found: {prompt_path}")
            return ""
        cache_key = str(prompt_path)
        if cache_key not in self._prompt_cache:
            with open(prompt_path, "r", encoding="utf-8") as f:
                self._prompt_cache[cache_key] = f.read()
        prompt_text = self._prompt_cache[cache_key]
        if context:
            for key, value in context.items():
                prompt_text = prompt_text.replace(f"{{{key}}}", str(value))
        return prompt_text

    def build_agent_system_prompt(
        self, domain: DomainType, agent_role: str, user_preferences: Optional[dict] = None
    ) -> str:
        """Build complete system prompt: base prompt + domain + user prefs."""
        model_config = self.get_agent_model_config(domain, agent_role)
        base_prompt = self.load_prompt(model_config["system_prompt_file"])
        raw = self.get_raw_domain_config(domain)
        agent_goal = ""
        for role_cfg in raw["team_roles"]:
            if role_cfg["role"] == agent_role:
                agent_goal = role_cfg["goal"]
                break
        parts = [
            base_prompt,
            f"\n\n## Active Domain: {domain.value}",
            f"## Your Role: {agent_role}",
            f"## Your Specific Goal: {agent_goal}",
        ]
        if user_preferences:
            pref_section = "\n## User Preferences (MUST FOLLOW):\n"
            for key, value in user_preferences.items():
                pref_section += f"- **{key}:** {value}\n"
            parts.append(pref_section)
        return "\n".join(parts)

    def load_user_preferences(self, prefs_path: Optional[str] = None) -> dict[str, Any]:
        """Load user preferences from USER_PREFERENCES.md (CLAUDE.md Section 2)."""
        if prefs_path is None:
            prefs_path = str(PROJECT_ROOT / "User_Preference.md")
        path = Path(prefs_path)
        if not path.exists():
            logger.warning(f"User preferences not found: {prefs_path}")
            return {}
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        preferences = self._parse_preferences_md(content)
        self._user_preferences = preferences
        logger.info(f"User preferences loaded ({len(preferences)} sections)")
        return preferences

    def get_user_preferences(self) -> dict[str, Any]:
        return self._user_preferences

    def _parse_preferences_md(self, content: str) -> dict[str, Any]:
        preferences: dict[str, Any] = {}
        current_section = ""
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("### "):
                current_section = line.replace("### ", "").strip()
                for char in "👤🎨🔒":
                    current_section = current_section.replace(char, "").strip()
                preferences[current_section] = {}
            elif line.startswith("- **") and current_section:
                if ":**" in line:
                    parts = line.split(":**", 1)
                    key = parts[0].replace("- **", "").strip()
                    value = parts[1].strip().strip("[]").strip()
                    # Skip placeholder examples
                    if "e.g.," in value or "e.g." in value or value == "":
                        continue
                    if current_section in preferences:
                        preferences[current_section][key] = value
                elif line.startswith("  - [ ]") or line.startswith("  - [X]"):
                    # Checkboxes
                    if "[ ]" in line:
                        continue # Skip unchecked
                    key = line.replace("  - [X]", "").strip()
                    if current_section in preferences:
                        preferences[current_section][key] = "Yes"
        
        # Clean up empty sections
        return {k: v for k, v in preferences.items() if v}

    def load_constitution(self) -> str:
        """Load the CLAUDE.md global ruleset."""
        claude_path = PROJECT_ROOT / "CLAUDE.md"
        if not claude_path.exists():
            return ""
        with open(claude_path, "r", encoding="utf-8") as f:
            return f.read()

    def clear_caches(self) -> None:
        self._domain_cache.clear()
        self._prompt_cache.clear()
        logger.info("Config caches cleared")


config_loader = ConfigLoader()
