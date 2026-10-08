"""Seed script to load curated companies catalog into the database."""

import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot.db.models import Company

logger = logging.getLogger(__name__)

DEFAULT_COMPANIES_YAML_PATH = Path(__file__).parent / "seed_data" / "companies.yaml"


def load_companies_yaml(file_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Parse and validate companies from YAML file."""
    path = Path(file_path) if file_path else DEFAULT_COMPANIES_YAML_PATH
    if not path.exists():
        raise FileNotFoundError(f"Companies YAML file not found at: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "companies" not in data:
        raise ValueError("Invalid companies YAML: expected top-level 'companies' key.")

    companies = data["companies"]
    if not isinstance(companies, list):
        raise ValueError("Invalid companies YAML: 'companies' must be a list.")

    return companies


async def seed_companies(
    session: AsyncSession,
    file_path: Path | str | None = None,
) -> tuple[int, int]:
    """Upsert seed companies from YAML into the database.

    Returns a tuple of (inserted_count, updated_count).
    """
    companies_data = load_companies_yaml(file_path)
    inserted_count = 0
    updated_count = 0

    for item in companies_data:
        name = str(item.get("name", "")).strip()
        ats = str(item.get("ats", "")).strip().lower()
        board_token = str(item.get("board_token", "")).strip()
        domains = list(item.get("domains") or [])
        tags = list(item.get("tags") or [])
        careers_url = item.get("careers_url")

        if not name or not ats or not board_token:
            logger.warning("Skipping invalid company record: %s", item)
            continue

        stmt = select(Company).where(Company.name == name)
        existing = await session.scalar(stmt)

        if existing:
            existing.ats = ats
            existing.board_token = board_token
            existing.domains = domains
            existing.tags = tags
            existing.careers_url = careers_url
            updated_count += 1
        else:
            new_company = Company(
                name=name,
                ats=ats,
                board_token=board_token,
                domains=domains,
                tags=tags,
                careers_url=careers_url,
            )
            session.add(new_company)
            inserted_count += 1

    await session.commit()
    logger.info(
        "Company seeding complete: %d inserted, %d updated (total: %d)",
        inserted_count,
        updated_count,
        len(companies_data),
    )
    return inserted_count, updated_count
