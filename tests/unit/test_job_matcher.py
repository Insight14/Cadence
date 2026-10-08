"""Unit tests for JobMatcher engine: ranking, filtering, blurb generation, alert deduplication."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot.db.models import Company, JobPosting, ResumeProfile, User, UserCompanyPref
from jobpilot.embeddings.client import FakeEmbeddingsClient
from jobpilot.jobs.matcher import JobMatcher
from jobpilot.llm.client import FakeLLMClient
from jobpilot.resume.extractor import ResumeProfileExtractor
from jobpilot.resume.service import process_and_save_resume


@pytest.mark.asyncio
async def test_job_matcher_scoring_and_filtering(db_session: AsyncSession) -> None:
    embedder = FakeEmbeddingsClient(dimension=64)
    mock_llm = FakeLLMClient(
        default_response="Direct match for your distributed systems and Python skills."
    )
    matcher = JobMatcher(embeddings_client=embedder, llm_client=mock_llm)

    # 1. Create User
    user = User(email="student@university.edu", telegram_chat_id=12345678)
    db_session.add(user)
    await db_session.flush()

    # 2. Create Candidate Resume Profile
    user_vec = await embedder.embed_text("Python Distributed Systems Backend Engineer")
    profile = ResumeProfile(
        user_id=user.id,
        structured_json={
            "skills": ["Python", "Docker", "PostgreSQL"],
            "domains": ["Backend", "Distributed Systems"],
            "project_themes": ["Raft Consensus"],
            "target_roles": ["Backend Intern"],
            "summary": "CS junior specializing in distributed systems.",
        },
        embedding=user_vec,
    )
    db_session.add(profile)

    # 3. Create Companies (one active, one muted)
    comp_a = Company(
        name="TechCorp",
        ats="greenhouse",
        board_token="techcorp",
        tags=["Backend", "Distributed Systems"],
    )
    comp_muted = Company(
        name="MutedCorp",
        ats="lever",
        board_token="mutedcorp",
        tags=["Backend"],
    )
    db_session.add_all([comp_a, comp_muted])
    await db_session.flush()

    # Mute comp_muted for user
    pref = UserCompanyPref(user_id=user.id, company_id=comp_muted.id, status="muted")
    db_session.add(pref)

    # 4. Create Job Postings
    job_match_vec = await embedder.embed_text("Python Distributed Systems Backend Engineer")
    job_unrelated_vec = await embedder.embed_text("Fashion Marketing Coordinator Brand Design")

    job_good = JobPosting(
        company_id=comp_a.id,
        external_id="job-101",
        title="Software Engineer Intern - Distributed Systems",
        url="https://techcorp.com/jobs/101",
        location="New York, NY",
        is_open=True,
        embedding=job_match_vec,
    )
    job_muted = JobPosting(
        company_id=comp_muted.id,
        external_id="job-202",
        title="Software Engineer Intern",
        url="https://mutedcorp.com/jobs/202",
        is_open=True,
        embedding=job_match_vec,
    )
    job_unrelated = JobPosting(
        company_id=comp_a.id,
        external_id="job-303",
        title="Marketing Specialist",
        url="https://techcorp.com/jobs/303",
        is_open=True,
        embedding=job_unrelated_vec,
    )
    db_session.add_all([job_good, job_muted, job_unrelated])
    await db_session.commit()

    # 5. Find Matches
    matches = await matcher.find_matches_for_user(db_session, user.id, min_score=0.80)

    # Only job_good should match (job_muted is muted; job_unrelated has low similarity score)
    assert len(matches) == 1
    assert matches[0].job.id == job_good.id
    assert matches[0].company.name == "TechCorp"
    assert matches[0].similarity_score > 0.90
    assert "distributed systems" in (matches[0].why_matched or "").lower()


@pytest.mark.asyncio
async def test_process_and_save_resume_service(db_session: AsyncSession) -> None:
    embedder = FakeEmbeddingsClient(dimension=64)
    mock_llm = FakeLLMClient(
        default_response="""
        {
            "skills": ["Rust", "Python"],
            "domains": ["Robotics", "Autonomy"],
            "project_themes": ["SLAM Navigation"],
            "target_roles": ["Robotics Intern"],
            "graduation_year": 2026,
            "work_authorization": "US Citizen",
            "summary": "Robotics student."
        }
        """
    )
    extractor = ResumeProfileExtractor(llm_client=mock_llm)

    # Pre-seed target company with matching tag
    robotics_comp = Company(
        name="RoboTech",
        ats="ashby",
        board_token="robotech",
        tags=["Robotics", "AI"],
    )

    db_session.add(robotics_comp)
    await db_session.flush()

    user = User(email="robotics_grad@mit.edu")
    db_session.add(user)
    await db_session.flush()

    resume_txt = b"Alex Rivera\nEducation: MIT Robotics\nSkills: Rust, Python, SLAM"
    res_prof, structured, auto_watched = await process_and_save_resume(
        session=db_session,
        user_id=user.id,
        filename="resume.txt",
        file_bytes=resume_txt,
        extractor=extractor,
        embeddings_client=embedder,
    )

    assert res_prof.user_id == user.id
    assert "Rust" in structured.skills
    assert "Robotics" in structured.domains
    assert len(auto_watched) == 1
    assert auto_watched[0].name == "RoboTech"
