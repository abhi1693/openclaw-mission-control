# ruff: noqa: INP001
"""Integration tests for skills marketplace APIs."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_org_admin
from app.api.gateways import router as gateways_router
from app.api.skills_marketplace import (
    PackSkillCandidate,
    _collect_pack_skills_from_repo,
    _validate_pack_source_url,
)
from app.api.skills_marketplace import router as skills_marketplace_router
from app.db.session import get_session
from app.models.gateways import Gateway
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.skills import GatewayInstalledSkill, MarketplaceSkill, SkillPack
from app.services.organizations import OrganizationContext


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


def _build_test_app(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    organization: Organization,
) -> FastAPI:
    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(gateways_router)
    api_v1.include_router(skills_marketplace_router)
    app.include_router(api_v1)

    async def _override_get_session() -> AsyncSession:
        async with session_maker() as session:
            yield session

    async def _override_require_org_admin() -> OrganizationContext:
        return OrganizationContext(
            organization=organization,
            member=OrganizationMember(
                organization_id=organization.id,
                user_id=uuid4(),
                role="owner",
                all_boards_read=True,
                all_boards_write=True,
            ),
        )

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[require_org_admin] = _override_require_org_admin
    return app


async def _seed_base(
    session: AsyncSession,
) -> tuple[Organization, Gateway]:
    organization = Organization(id=uuid4(), name="Org One")
    gateway = Gateway(
        id=uuid4(),
        organization_id=organization.id,
        name="Gateway One",
        url="https://gateway.example.local",
        workspace_root="/workspace/openclaw",
    )
    session.add(organization)
    session.add(gateway)
    await session.commit()
    return organization, gateway


@pytest.mark.asyncio
async def test_install_skill_dispatches_instruction_and_persists_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, gateway = await _seed_base(session)
            skill = MarketplaceSkill(
                organization_id=organization.id,
                name="Deploy Helper",
                source_url="https://example.com/skills/deploy-helper.git",
                description="Handles deploy workflow checks.",
            )
            session.add(skill)
            await session.commit()
            await session.refresh(skill)

        app = _build_test_app(session_maker, organization=organization)
        sent_messages: list[dict[str, str | bool]] = []

        async def _fake_send_agent_message(
            _self: object,
            *,
            session_key: str,
            config: object,
            agent_name: str,
            message: str,
            deliver: bool = False,
        ) -> None:
            del config
            sent_messages.append(
                {
                    "session_key": session_key,
                    "agent_name": agent_name,
                    "message": message,
                    "deliver": deliver,
                },
            )

        monkeypatch.setattr(
            "app.api.skills_marketplace.GatewayDispatchService.send_agent_message",
            _fake_send_agent_message,
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/api/v1/skills/marketplace/{skill.id}/install",
                params={"gateway_id": str(gateway.id)},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["installed"] is True
        assert body["gateway_id"] == str(gateway.id)
        assert len(sent_messages) == 1
        assert sent_messages[0]["agent_name"] == "Gateway Agent"
        assert sent_messages[0]["deliver"] is True
        assert sent_messages[0]["session_key"] == f"agent:mc-gateway-{gateway.id}:main"
        message = str(sent_messages[0]["message"])
        assert "SKILL INSTALL REQUEST" in message
        assert str(skill.source_url) in message
        assert "/workspace/openclaw/skills" in message

        async with session_maker() as session:
            installed_rows = (
                await session.exec(
                    select(GatewayInstalledSkill).where(
                        col(GatewayInstalledSkill.gateway_id) == gateway.id,
                        col(GatewayInstalledSkill.skill_id) == skill.id,
                    ),
                )
            ).all()
            assert len(installed_rows) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_gateway_removes_installed_skill_rows() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, gateway = await _seed_base(session)
            skill = MarketplaceSkill(
                organization_id=organization.id,
                name="Deploy Helper",
                source_url="https://example.com/skills/deploy-helper.git",
            )
            session.add(skill)
            await session.commit()
            await session.refresh(skill)
            session.add(
                GatewayInstalledSkill(
                    gateway_id=gateway.id,
                    skill_id=skill.id,
                ),
            )
            await session.commit()

        app = _build_test_app(session_maker, organization=organization)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.delete(f"/api/v1/gateways/{gateway.id}")

        assert response.status_code == 200
        assert response.json() == {"ok": True}

        async with session_maker() as session:
            deleted_gateway = await session.get(Gateway, gateway.id)
            assert deleted_gateway is None
            remaining_installs = (
                await session.exec(
                    select(GatewayInstalledSkill).where(
                        col(GatewayInstalledSkill.gateway_id) == gateway.id,
                    ),
                )
            ).all()
            assert remaining_installs == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_marketplace_skills_marks_installed_cards() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, gateway = await _seed_base(session)
            first = MarketplaceSkill(
                organization_id=organization.id,
                name="First Skill",
                source_url="https://example.com/skills/first",
            )
            second = MarketplaceSkill(
                organization_id=organization.id,
                name="Second Skill",
                source_url="https://example.com/skills/second",
            )
            session.add(first)
            session.add(second)
            await session.commit()
            await session.refresh(first)
            await session.refresh(second)

            session.add(
                GatewayInstalledSkill(
                    gateway_id=gateway.id,
                    skill_id=first.id,
                ),
            )
            await session.commit()

        app = _build_test_app(session_maker, organization=organization)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/api/v1/skills/marketplace",
                params={"gateway_id": str(gateway.id)},
            )

        assert response.status_code == 200
        cards = response.json()
        assert len(cards) == 2
        cards_by_id = {item["id"]: item for item in cards}
        assert cards_by_id[str(first.id)]["installed"] is True
        assert cards_by_id[str(first.id)]["installed_at"] is not None
        assert cards_by_id[str(second.id)]["installed"] is False
        assert cards_by_id[str(second.id)]["installed_at"] is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_pack_clones_and_upserts_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, _gateway = await _seed_base(session)
            pack = SkillPack(
                organization_id=organization.id,
                name="Antigravity Awesome Skills",
                source_url="https://github.com/sickn33/antigravity-awesome-skills",
            )
            session.add(pack)
            await session.commit()
            await session.refresh(pack)

        app = _build_test_app(session_maker, organization=organization)

        collected = [
            PackSkillCandidate(
                name="Skill Alpha",
                description="Alpha description",
                source_url="https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/alpha",
                category="testing",
                risk="low",
                source="skills/alpha",
            ),
            PackSkillCandidate(
                name="Skill Beta",
                description="Beta description",
                source_url="https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/beta",
                category="automation",
                risk="medium",
                source="skills/beta",
            ),
        ]

        def _fake_collect_pack_skills(source_url: str) -> list[PackSkillCandidate]:
            assert source_url == "https://github.com/sickn33/antigravity-awesome-skills"
            return collected

        monkeypatch.setattr(
            "app.api.skills_marketplace._collect_pack_skills",
            _fake_collect_pack_skills,
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            first_sync = await client.post(f"/api/v1/skills/packs/{pack.id}/sync")
            second_sync = await client.post(f"/api/v1/skills/packs/{pack.id}/sync")

        assert first_sync.status_code == 200
        first_body = first_sync.json()
        assert first_body["pack_id"] == str(pack.id)
        assert first_body["synced"] == 2
        assert first_body["created"] == 2
        assert first_body["updated"] == 0

        assert second_sync.status_code == 200
        second_body = second_sync.json()
        assert second_body["pack_id"] == str(pack.id)
        assert second_body["synced"] == 2
        assert second_body["created"] == 0
        assert second_body["updated"] == 0

        async with session_maker() as session:
            synced_skills = (
                await session.exec(
                    select(MarketplaceSkill).where(
                        col(MarketplaceSkill.organization_id) == organization.id,
                    ),
                )
            ).all()
            assert len(synced_skills) == 2
            by_source = {skill.source_url: skill for skill in synced_skills}
            assert (
                by_source[
                    "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/alpha"
                ].name
                == "Skill Alpha"
            )
            assert (
                by_source[
                    "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/alpha"
                ].category
                == "testing"
            )
            assert (
                by_source[
                    "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/alpha"
                ].risk
                == "low"
            )
            assert (
                by_source[
                    "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/beta"
                ].description
                == "Beta description"
            )
            assert (
                by_source[
                    "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/beta"
                ].source
                == "skills/beta"
            )
    finally:
        await engine.dispose()


def test_validate_pack_source_url_allows_https_github_repo_with_optional_dot_git() -> None:
    _validate_pack_source_url("https://github.com/org/repo")
    _validate_pack_source_url("https://github.com/org/repo.git")


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/org/repo",
        "file:///tmp/repo",
        "ssh://github.com/org/repo",
        "https://localhost/repo",
        "https://127.0.0.1/repo",
        "https://[::1]/repo",
    ],
)
def test_validate_pack_source_url_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_pack_source_url(url)


def test_validate_pack_source_url_rejects_git_ssh_scp_like_syntax() -> None:
    # Not a URL, but worth asserting we fail closed.
    with pytest.raises(ValueError):
        _validate_pack_source_url("git@github.com:org/repo.git")


@pytest.mark.asyncio
async def test_create_skill_pack_rejects_non_https_source_url() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, _gateway = await _seed_base(session)
            await session.commit()

        app = _build_test_app(session_maker, organization=organization)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/skills/packs",
                json={"source_url": "http://github.com/sickn33/antigravity-awesome-skills"},
            )

        assert response.status_code == 400
        assert (
            "scheme" in response.json()["detail"].lower()
            or "https" in response.json()["detail"].lower()
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_skill_pack_rejects_localhost_source_url() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, _gateway = await _seed_base(session)
            await session.commit()

        app = _build_test_app(session_maker, organization=organization)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/v1/skills/packs",
                json={"source_url": "https://localhost/skills-pack"},
            )

        assert response.status_code == 400
        assert (
            "hostname" in response.json()["detail"].lower()
            or "not allowed" in response.json()["detail"].lower()
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_skill_pack_is_unique_by_normalized_source_url() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, _gateway = await _seed_base(session)
            await session.commit()

        app = _build_test_app(session_maker, organization=organization)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            first = await client.post(
                "/api/v1/skills/packs",
                json={"source_url": "https://github.com/org/repo"},
            )
            spaced = await client.post(
                "/api/v1/skills/packs",
                json={"source_url": " https://github.com/org/repo.git  "},
            )
            second = await client.post(
                "/api/v1/skills/packs",
                json={"source_url": "https://github.com/org/repo/"},
            )
            third = await client.post(
                "/api/v1/skills/packs",
                json={"source_url": "https://github.com/org/repo.git"},
            )
            packs = await client.get("/api/v1/skills/packs")

        assert first.status_code == 200
        assert spaced.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 200
        assert spaced.json()["id"] == first.json()["id"]
        assert spaced.json()["source_url"] == first.json()["source_url"]
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["source_url"] == first.json()["source_url"]
        assert third.json()["id"] == first.json()["id"]
        assert third.json()["source_url"] == first.json()["source_url"]
        assert packs.status_code == 200
        pack_items = packs.json()
        assert len(pack_items) == 1
        assert pack_items[0]["source_url"] == "https://github.com/org/repo"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_skill_packs_includes_skill_count() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, _gateway = await _seed_base(session)
            pack = SkillPack(
                organization_id=organization.id,
                name="Pack One",
                source_url="https://github.com/sickn33/antigravity-awesome-skills",
            )
            session.add(pack)
            session.add(
                MarketplaceSkill(
                    organization_id=organization.id,
                    name="Skill One",
                    source_url=(
                        "https://github.com/sickn33/antigravity-awesome-skills"
                        "/tree/main/skills/alpha"
                    ),
                )
            )
            session.add(
                MarketplaceSkill(
                    organization_id=organization.id,
                    name="Skill Two",
                    source_url=(
                        "https://github.com/sickn33/antigravity-awesome-skills"
                        "/tree/main/skills/beta"
                    ),
                )
            )
            session.add(
                MarketplaceSkill(
                    organization_id=organization.id,
                    name="Other Repo Skill",
                    source_url="https://github.com/other/repo/tree/main/skills/other",
                )
            )
            await session.commit()

        app = _build_test_app(session_maker, organization=organization)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/v1/skills/packs")

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["name"] == "Pack One"
        assert items[0]["skill_count"] == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_skill_pack_rejects_duplicate_normalized_source_url() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, _gateway = await _seed_base(session)
            pack_a = SkillPack(
                organization_id=organization.id,
                source_url="https://github.com/org/repo",
                name="Pack A",
            )
            pack_b = SkillPack(
                organization_id=organization.id,
                source_url="https://github.com/org/other-repo",
                name="Pack B",
            )
            session.add(pack_a)
            session.add(pack_b)
            await session.commit()
            await session.refresh(pack_a)
            await session.refresh(pack_b)

        app = _build_test_app(session_maker, organization=organization)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.patch(
                f"/api/v1/skills/packs/{pack_b.id}",
                json={"source_url": "https://github.com/org/repo/"},
            )

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

        async with session_maker() as session:
            pack_rows = (
                await session.exec(
                    select(SkillPack)
                    .where(col(SkillPack.organization_id) == organization.id)
                    .order_by(col(SkillPack.created_at).asc())
                )
            ).all()
        assert len(pack_rows) == 2
        assert {str(pack.source_url) for pack in pack_rows} == {
            "https://github.com/org/repo",
            "https://github.com/org/other-repo",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_update_skill_pack_normalizes_source_url_on_update() -> None:
    engine = await _make_engine()
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with session_maker() as session:
            organization, _gateway = await _seed_base(session)
            pack = SkillPack(
                organization_id=organization.id,
                source_url="https://github.com/org/old",
                name="Initial",
            )
            session.add(pack)
            await session.commit()
            await session.refresh(pack)

        app = _build_test_app(session_maker, organization=organization)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.patch(
                f"/api/v1/skills/packs/{pack.id}",
                json={"source_url": " https://github.com/org/new.git/ "},
            )

        assert response.status_code == 200
        assert response.json()["source_url"] == "https://github.com/org/new"

        async with session_maker() as session:
            updated = (
                await session.exec(
                    select(SkillPack).where(col(SkillPack.id) == pack.id),
                )
            ).one()
            assert str(updated.source_url) == "https://github.com/org/new"
    finally:
        await engine.dispose()


def test_collect_pack_skills_from_repo_uses_root_index_when_present(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "skills").mkdir()
    indexed_dir = repo_dir / "skills" / "indexed-fallback"
    indexed_dir.mkdir()
    (indexed_dir / "SKILL.md").write_text("# Should Not Be Used\n", encoding="utf-8")

    (repo_dir / "skills_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "first",
                    "name": "Index First",
                    "description": "From index one",
                    "path": "skills/index-first",
                    "category": "uncategorized",
                    "risk": "unknown",
                },
                {
                    "id": "second",
                    "name": "Index Second",
                    "description": "From index two",
                    "path": "skills/index-second/SKILL.md",
                    "category": "catalog",
                    "risk": "low",
                },
                {
                    "id": "root",
                    "name": "Root Skill",
                    "description": "Root from index",
                    "path": "SKILL.md",
                    "category": "uncategorized",
                    "risk": "unknown",
                },
            ]
        ),
        encoding="utf-8",
    )

    skills = _collect_pack_skills_from_repo(
        repo_dir=repo_dir,
        source_url="https://github.com/sickn33/antigravity-awesome-skills",
        branch="main",
    )

    assert len(skills) == 3
    by_source = {skill.source_url: skill for skill in skills}
    assert (
        "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/index-first"
        in by_source
    )
    assert (
        "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/index-second"
        in by_source
    )
    assert "https://github.com/sickn33/antigravity-awesome-skills/tree/main" in by_source
    assert (
        by_source[
            "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/index-first"
        ].name
        == "Index First"
    )
    assert (
        by_source[
            "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/index-first"
        ].category
        == "uncategorized"
    )
    assert (
        by_source[
            "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/index-first"
        ].risk
        == "unknown"
    )
    assert (
        by_source[
            "https://github.com/sickn33/antigravity-awesome-skills/tree/main/skills/index-first"
        ].source
        == "skills/index-first"
    )
    assert (
        by_source["https://github.com/sickn33/antigravity-awesome-skills/tree/main"].name
        == "Root Skill"
    )


def test_collect_pack_skills_from_repo_supports_root_skill_md(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "SKILL.md").write_text(
        "---\nname: x-research-skill\ndescription: Root skill package\n---\n",
        encoding="utf-8",
    )

    skills = _collect_pack_skills_from_repo(
        repo_dir=repo_dir,
        source_url="https://github.com/rohunvora/x-research-skill",
        branch="main",
    )

    assert len(skills) == 1
    only_skill = skills[0]
    assert only_skill.name == "x-research-skill"
    assert only_skill.description == "Root skill package"
    assert only_skill.source_url == "https://github.com/rohunvora/x-research-skill/tree/main"


def test_collect_pack_skills_from_repo_supports_top_level_skill_folders(
    tmp_path: Path,
) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    first = repo_dir / "content-idea-generator"
    second = repo_dir / "homepage-audit"
    first.mkdir()
    second.mkdir()
    (first / "SKILL.md").write_text("# Content Idea Generator\n", encoding="utf-8")
    (second / "SKILL.md").write_text("# Homepage Audit\n", encoding="utf-8")

    skills = _collect_pack_skills_from_repo(
        repo_dir=repo_dir,
        source_url="https://github.com/BrianRWagner/ai-marketing-skills",
        branch="main",
    )

    assert len(skills) == 2
    by_source = {skill.source_url: skill for skill in skills}
    assert (
        "https://github.com/BrianRWagner/ai-marketing-skills/tree/main/content-idea-generator"
        in by_source
    )
    assert (
        "https://github.com/BrianRWagner/ai-marketing-skills/tree/main/homepage-audit" in by_source
    )


def test_collect_pack_skills_from_repo_streams_large_index(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "SKILL.md").write_text("# Fallback Skill\n", encoding="utf-8")

    huge_description = "x" * (300 * 1024)
    (repo_dir / "skills_index.json").write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "id": "oversized",
                        "name": "Huge Index Skill",
                        "description": huge_description,
                        "path": "skills/ignored",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    skills = _collect_pack_skills_from_repo(
        repo_dir=repo_dir,
        source_url="https://github.com/example/oversized-pack",
        branch="main",
    )

    assert len(skills) == 1
    assert (
        skills[0].source_url == "https://github.com/example/oversized-pack/tree/main/skills/ignored"
    )
    assert skills[0].name == "Huge Index Skill"
