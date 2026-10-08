"""Recruiter discovery deep-link generator and outreach utilities."""

import urllib.parse


def build_linkedin_recruiter_search_url(
    company_name: str,
    keywords: list[str] | None = None,
) -> str:
    """Build a LinkedIn People search deep-link for university/technical recruiters."""
    search_terms = [company_name]
    if keywords:
        search_terms.extend(keywords)
    else:
        search_terms.extend(["university recruiter", "technical recruiter"])

    query = " ".join(search_terms)
    encoded_query = urllib.parse.quote(query)
    return f"https://www.linkedin.com/search/results/people/?keywords={encoded_query}"


def build_linkedin_hiring_manager_search_url(
    company_name: str,
    role_title: str | None = None,
) -> str:
    """Build a LinkedIn People search deep-link for engineering/product hiring managers."""
    terms = [company_name]
    if role_title:
        terms.append(role_title)
    terms.append("engineering manager")

    query = " ".join(terms)
    encoded_query = urllib.parse.quote(query)
    return f"https://www.linkedin.com/search/results/people/?keywords={encoded_query}"
