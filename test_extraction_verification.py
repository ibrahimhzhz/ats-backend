"""
Verification script: Run extraction against three test cases and print raw JSON.

Test cases:
1. Strong resume — clear dates, many skills, degree
2. Resume with employment gaps and no degree
3. Minimal / poorly formatted resume
"""
import asyncio
import json
import sys
import os

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.ai_engine import extract_candidate_facts, validate_extraction_result


# ---------------------------------------------------------------------------
# Test resume texts
# ---------------------------------------------------------------------------

STRONG_RESUME = """
Jane Smith
jane.smith@example.com | (555) 123-4567 | linkedin.com/in/janesmith

SUMMARY
Senior Software Engineer with 10+ years of experience building scalable SaaS platforms.

EXPERIENCE

Senior Software Engineer — Stripe (Remote)
January 2021 – Present
- Led migration of payment processing pipeline to Kubernetes, reducing deployment time by 60%
- Designed and implemented real-time fraud detection system handling 50M transactions/month
- Managed team of 5 engineers; mentored 3 junior developers
- Technologies: Python, Go, Kubernetes, PostgreSQL, Redis, Kafka, AWS

Software Engineer — Shopify
June 2017 – December 2020
- Built merchant analytics dashboard serving 500K daily active users
- Reduced API response latency by 200ms through query optimization
- Implemented CI/CD pipelines using GitHub Actions and Docker
- Technologies: Ruby on Rails, React, TypeScript, MySQL, Docker, GraphQL

Junior Developer — Accenture
March 2014 – May 2017
- Developed enterprise resource planning modules for Fortune 500 clients
- Technologies: Java, Spring Boot, Oracle DB, Angular

EDUCATION
Master of Science in Computer Science — Stanford University, 2014
Bachelor of Science in Mathematics — UC Berkeley, 2012

SKILLS
Python, Go, Ruby, Java, TypeScript, JavaScript, React, Angular, Kubernetes, Docker,
PostgreSQL, MySQL, Redis, Kafka, AWS, GCP, GraphQL, Git, CI/CD, Terraform

CERTIFICATIONS
AWS Solutions Architect – Associate (2022)
"""

GAPS_NO_DEGREE_RESUME = """
Mike Johnson
mike.j@gmail.com

WORK EXPERIENCE

Freelance Web Developer
March 2024 – Present
- Building WordPress and Shopify sites for small businesses
- HTML, CSS, JavaScript, PHP, WordPress

Data Entry Clerk — OfficeMax
January 2020 – June 2022
- Entered inventory data into proprietary system
- Created Excel macros to automate weekly reports
- Microsoft Excel, Microsoft Access

Warehouse Associate — Amazon
April 2018 – September 2018
- Operated forklift and managed inventory counts

Barista — Starbucks
August 2015 – December 2017
- Provided customer service, trained 10+ new hires

SKILLS
HTML, CSS, JavaScript, PHP, WordPress, Microsoft Excel, Microsoft Access
"""

MINIMAL_RESUME = """
alex t
alexthompson99@hotmail.com

worked at some company doing stuff 2019-2021
know python and excel
went to college
"""


async def run_test(label: str, resume_text: str) -> dict:
    print(f"\n{'='*80}")
    print(f"  TEST CASE: {label}")
    print(f"{'='*80}")
    try:
        result = await extract_candidate_facts(
            resume_text=resume_text,
            job_requirements={
                "must_have_skills": ["Python", "React", "AWS"],
                "minimum_years_experience": 3,
                "education_requirement": "Bachelor's",
                "offers_visa_sponsorship": False,
            },
            fail_on_unavailable=True,
        )
        print(json.dumps(result, indent=2, default=str))
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return {}


async def main():
    results = {}
    results["strong"] = await run_test("Strong resume (dates, skills, degree)", STRONG_RESUME)
    results["gaps"] = await run_test("Employment gaps, no degree", GAPS_NO_DEGREE_RESUME)
    results["minimal"] = await run_test("Minimal / poorly formatted", MINIMAL_RESUME)

    print("\n\n" + "="*80)
    print("  VALIDATION FUNCTION UNIT TEST")
    print("="*80)

    # Test validate_extraction_result with edge cases
    print("\n--- Edge case: extractable_text = False ---")
    edge1 = validate_extraction_result({"extractable_text": False})
    print(json.dumps(edge1, indent=2))

    print("\n--- Edge case: negative total_years_experience ---")
    edge2 = validate_extraction_result({
        "extractable_text": True,
        "total_years_experience": -5,
        "skills": [{"name": "python"}],
        "education": [],
        "jobs": [],
        "requires_visa_sponsorship": False,
        "has_measurable_impact": False,
        "has_contact_info": True,
        "has_clear_job_titles": True,
        "employment_gaps": False,
        "average_tenure_years": 2.0,
        "cover_letter_analysis": {"word_count": 0, "mentions_role_title": False, "skills_mentioned": [], "has_specific_example": False, "is_generic": True},
        "custom_answer_analysis": [],
    })
    print(f"total_years_experience corrected to: {edge2['total_years_experience']}")

    print("\n--- Edge case: skill missing name ---")
    edge3 = validate_extraction_result({
        "extractable_text": True,
        "total_years_experience": 5,
        "skills": [{"name": "python"}, {"years_used": 2}, {"name": ""}],
        "education": [],
        "jobs": [],
        "requires_visa_sponsorship": False,
        "has_measurable_impact": False,
        "has_contact_info": True,
        "has_clear_job_titles": True,
        "employment_gaps": False,
        "average_tenure_years": 2.0,
        "cover_letter_analysis": {"word_count": 0, "mentions_role_title": False, "skills_mentioned": [], "has_specific_example": False, "is_generic": True},
        "custom_answer_analysis": [],
    })
    print(f"Skills after validation: {edge3['skills']}")

    print("\n--- Edge case: job missing company ---")
    edge4 = validate_extraction_result({
        "extractable_text": True,
        "total_years_experience": 5,
        "skills": [],
        "education": [],
        "jobs": [
            {"title": "Engineer", "company": "Acme", "start_year": 2020, "is_current": True, "domain": "saas", "work_type": "remote"},
            {"title": "Dev", "start_year": 2018},
        ],
        "requires_visa_sponsorship": False,
        "has_measurable_impact": False,
        "has_contact_info": True,
        "has_clear_job_titles": True,
        "employment_gaps": False,
        "average_tenure_years": 2.5,
        "cover_letter_analysis": {"word_count": 0, "mentions_role_title": False, "skills_mentioned": [], "has_specific_example": False, "is_generic": True},
        "custom_answer_analysis": [],
    })
    print(f"Jobs after validation: {edge4['jobs']}")

    print("\nAll verification tests completed.")


if __name__ == "__main__":
    asyncio.run(main())
