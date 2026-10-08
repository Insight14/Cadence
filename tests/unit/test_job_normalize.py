"""Unit tests for job normalization, HTML cleaning, and role classification."""

from jobpilot.jobs.normalize import clean_html_to_text, is_student_or_new_grad_role


def test_clean_html_to_text() -> None:
    # Empty / None
    assert clean_html_to_text(None) is None
    assert clean_html_to_text("") is None
    assert clean_html_to_text("   ") is None

    # HTML tags and entities
    html_sample = (
        "<div><p>We are seeking a <strong>Software Engineering Intern</strong>"
        " &amp; passionate builder.</p>"
        "<p>Requirements:<ul><li>Python &lt;3.12&gt;</li>"
        "<li>FastAPI &quot;expert&quot;</li></ul></p></div>"
    )
    cleaned = clean_html_to_text(html_sample)
    assert cleaned is not None
    assert "<strong>" not in cleaned
    assert "&amp;" not in cleaned
    assert "Software Engineering Intern & passionate builder." in cleaned
    assert "Python <3.12>" in cleaned
    assert 'FastAPI "expert"' in cleaned


def test_is_student_or_new_grad_role_positive_titles() -> None:
    positive_titles = [
        "Software Engineering Intern - Summer 2026",
        "SWE Co-op (Fall 2025)",
        "New Grad Software Engineer (2026)",
        "University Graduate - Machine Learning",
        "Associate Software Engineer",
        "Early Career Frontend Developer",
        "Entry Level Data Analyst",
        "Campus Recruiting - Systems Engineer",
        "Undergraduate Research Intern",
        "Rotational Engineering Program (New Grad)",
        "Apprenticeship - Cloud Operations",
        "Summer 2026 Engineering Internship",
    ]
    for title in positive_titles:
        assert is_student_or_new_grad_role(title) is True, f"Failed for: {title}"


def test_is_student_or_new_grad_role_negative_titles() -> None:
    negative_titles = [
        "Senior Software Engineer",
        "Staff Software Engineer - Infrastructure",
        "Principal Architect",
        "Director of Engineering",
        "Engineering Manager",
        "VP of Product",
        "Lead Backend Engineer",
        "Sr. DevOps Engineer",
    ]
    for title in negative_titles:
        assert is_student_or_new_grad_role(title) is False, f"Failed for: {title}"


def test_is_student_or_new_grad_role_description_fallback() -> None:
    # Generic title with student keywords in description
    title = "Software Engineer"
    desc_intern = "This is a 12-week summer internship for currently enrolled students."
    assert is_student_or_new_grad_role(title, description_text=desc_intern) is True

    desc_senior = (
        "Requires 8+ years of production experience leading large distributed systems teams."
    )
    assert is_student_or_new_grad_role(title, description_text=desc_senior) is False
