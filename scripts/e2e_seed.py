"""E2E test seed script.

Seeds the minimum prerequisite state for integration E2E tests:
- One test user
- One test organization
- Organization membership (user -> org, owner role)

Writes directly via app models. Does NOT use product API endpoints.
Run via: python -m scripts.e2e_seed
"""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

# Ensure the backend app package is importable.
# In the Docker image, CWD is /app and app/ is a direct child.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Import models to register metadata.
from app import models as _models  # noqa: F401
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.users import User

# Well-known IDs matching cypress.integration.config.ts env values.
USER_ID = UUID("00000000-0000-4000-a000-000000000001")
ORG_ID = UUID("00000000-0000-4000-a000-000000000002")
MEMBER_ID = UUID("00000000-0000-4000-a000-000000000003")


async def seed(database_url: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        # Idempotent: check if user already exists.
        existing = await session.get(User, USER_ID)
        if existing:
            print(f"Seed data already exists (user {USER_ID}). Skipping.")
            return

        user = User(
            id=USER_ID,
            clerk_user_id="local-auth-user",
            email="e2e-test@example.com",
            name="E2E Test User",
            preferred_name="E2E User",
            timezone="UTC",
        )
        org = Organization(
            id=ORG_ID,
            name="E2E Testing Org",
        )
        member = OrganizationMember(
            id=MEMBER_ID,
            organization_id=ORG_ID,
            user_id=USER_ID,
            role="owner",
            all_boards_read=True,
            all_boards_write=True,
        )

        session.add(user)
        session.add(org)
        session.add(member)
        await session.commit()

    print(f"Seeded: user={USER_ID} org={ORG_ID} member={MEMBER_ID}")

    await engine.dispose()


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)
    asyncio.run(seed(database_url))


if __name__ == "__main__":
    main()
