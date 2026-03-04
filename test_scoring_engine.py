# test_scoring_engine.py
# Tests all pure scoring functions in isolation using mock data
# matching the three verified extraction test cases from ai_engine.py

from scoring import (
    normalize_skill,
    extract_seniority_level,
    score_experience,
    score_skills,
    calculate_education_score,
    calculate_application_quality_score,
    DEGREE_RANK,
    SENIORITY_LEVELS,
)

# ---------------------------------------------------------------
# normalize_skill tests
# ---------------------------------------------------------------

def test_normalize_skill_canonical():
    assert normalize_skill("ReactJS") == "react"
    assert normalize_skill("react.js") == "react"
    assert normalize_skill("PostgreSQL") == "postgres"
    assert normalize_skill("Kubernetes") == "k8s"
    assert normalize_skill("Node.js") == "node"

def test_normalize_skill_unknown():
    assert normalize_skill("SomeBrandNewFramework") == "somebrandnewframework"

def test_normalize_skill_already_canonical():
    assert normalize_skill("react") == "react"
    assert normalize_skill("aws") == "aws"

# ---------------------------------------------------------------
# extract_seniority_level tests
# ---------------------------------------------------------------

def test_seniority_senior():
    assert extract_seniority_level("Senior Software Engineer") == 3

def test_seniority_junior():
    assert extract_seniority_level("Junior Developer") == 1

def test_seniority_default():
    assert extract_seniority_level("Software Engineer") == 2

def test_seniority_empty():
    assert extract_seniority_level("") == 2
    assert extract_seniority_level(None) == 2

def test_seniority_lead():
    assert extract_seniority_level("Tech Lead") == 4

# ---------------------------------------------------------------
# score_experience tests
# ---------------------------------------------------------------

JANE_JOBS = [
    {"title": "Senior Software Engineer", "company": "Stripe",
     "start_year": 2021, "end_year": None, "is_current": True,
     "domain": "fintech", "work_type": "remote"},
    {"title": "Software Engineer", "company": "Shopify",
     "start_year": 2017, "end_year": 2020, "is_current": False,
     "domain": "ecommerce", "work_type": "unknown"},
    {"title": "Junior Developer", "company": "Accenture",
     "start_year": 2014, "end_year": 2017, "is_current": False,
     "domain": "enterprise", "work_type": "unknown"},
]

def test_experience_exact_match():
    result = score_experience(5, 5, [], None)
    assert result["total_exp_score"] == 15

def test_experience_over_by_small_amount():
    result = score_experience(7, 5, [], None)
    assert result["total_exp_score"] == 15

def test_experience_hard_overqualified_no_penalty():
    result = score_experience(15, 3, [], None, overqualification_penalty=False)
    assert result["total_exp_score"] == 15

def test_experience_hard_overqualified_with_penalty():
    result = score_experience(15, 3, [], None, overqualification_penalty=True)
    assert result["total_exp_score"] == 8

def test_experience_zero_years_senior_role():
    result = score_experience(0, 5, [], None)
    assert result["total_exp_score"] == 0

def test_experience_under_by_one():
    result = score_experience(4, 5, [], None)
    assert result["total_exp_score"] == 11

def test_experience_domain_full_match():
    result = score_experience(12, 5, JANE_JOBS, "fintech")
    assert result["domain_exp_score"] == 10

def test_experience_domain_no_match():
    result = score_experience(12, 5, JANE_JOBS, "healthcare")
    assert result["domain_exp_score"] == 1

def test_experience_no_domain_required():
    result = score_experience(12, 5, JANE_JOBS, None)
    assert result["domain_exp_score"] == 10

def test_experience_total_capped_at_25():
    result = score_experience(12, 5, JANE_JOBS, "fintech")
    assert result["total"] <= 25

# ---------------------------------------------------------------
# score_skills tests — Test Case 1 (Jane Smith)
# ---------------------------------------------------------------

JANE_SKILLS_DETAILED = [
    {"name": "python", "years_used": 5.0, "last_used_year": 2023, "job_index": 0},
    {"name": "go", "years_used": 5.0, "last_used_year": 2023, "job_index": 0},
    {"name": "kubernetes", "years_used": 5.0, "last_used_year": 2023, "job_index": 0},
    {"name": "postgresql", "years_used": 5.0, "last_used_year": 2023, "job_index": 0},
    {"name": "aws", "years_used": 5.0, "last_used_year": 2023, "job_index": 0},
    {"name": "react", "years_used": 3.0, "last_used_year": 2020, "job_index": 1},
    {"name": "typescript", "years_used": 3.0, "last_used_year": 2020, "job_index": 1},
    {"name": "java", "years_used": 3.0, "last_used_year": 2017, "job_index": 2},
]

def test_skills_all_required_matched():
    result = score_skills(
        skills_detailed=JANE_SKILLS_DETAILED,
        required_skills=["Python", "React", "AWS"],
        nice_to_have_skills=[],
        job_seniority_level=3,
    )
    assert result["required_score"] == 20
    assert set(result["matched_required"]) == {"py", "react", "aws"}
    assert result["missing_required"] == []

def test_skills_alias_normalization():
    result = score_skills(
        skills_detailed=[{"name": "ReactJS", "years_used": 2.0,
                          "last_used_year": 2024, "job_index": 0}],
        required_skills=["react"],
        nice_to_have_skills=[],
        job_seniority_level=2,
    )
    assert result["required_score"] == 20

def test_skills_partial_match():
    result = score_skills(
        skills_detailed=JANE_SKILLS_DETAILED,
        required_skills=["Python", "React", "AWS", "Docker", "Terraform"],
        nice_to_have_skills=[],
        job_seniority_level=3,
    )
    assert result["required_score"] < 20
    assert "docker" in result["missing_required"]
    assert "terraform" in result["missing_required"]

def test_skills_nice_to_have_no_penalty():
    result_with = score_skills(
        skills_detailed=JANE_SKILLS_DETAILED,
        required_skills=["Python"],
        nice_to_have_skills=["Terraform", "Ansible"],
        job_seniority_level=3,
    )
    result_without = score_skills(
        skills_detailed=JANE_SKILLS_DETAILED,
        required_skills=["Python"],
        nice_to_have_skills=[],
        job_seniority_level=3,
    )
    # Missing nice-to-have should never make total lower than having none required
    assert result_without["nice_to_have_score"] == 8
    assert result_with["nice_to_have_score"] == 0

def test_skills_depth_recency_senior_role():
    result = score_skills(
        skills_detailed=JANE_SKILLS_DETAILED,
        required_skills=["Python", "React", "AWS"],
        nice_to_have_skills=[],
        job_seniority_level=3,
    )
    assert result["depth_recency_score"] > 0

def test_skills_total_capped_at_35():
    result = score_skills(
        skills_detailed=JANE_SKILLS_DETAILED,
        required_skills=["Python", "React", "AWS"],
        nice_to_have_skills=["go", "typescript"],
        job_seniority_level=3,
    )
    assert result["total"] <= 35

def test_skills_empty_required():
    result = score_skills(
        skills_detailed=JANE_SKILLS_DETAILED,
        required_skills=[],
        nice_to_have_skills=[],
        job_seniority_level=2,
    )
    assert result["required_score"] == 20

# ---------------------------------------------------------------
# calculate_education_score tests
# ---------------------------------------------------------------

JANE_EDUCATION = [
    {"degree": "master", "field_of_study": "computer science",
     "institution": "stanford university", "year": 2014},
    {"degree": "bachelor", "field_of_study": "mathematics",
     "institution": "uc berkeley", "year": 2012},
]

def test_education_master_required_bachelor():
    result = calculate_education_score(JANE_EDUCATION, "bachelor", 12, "engineering")
    assert result["degree_score"] == 10

def test_education_field_cs_engineering():
    result = calculate_education_score(JANE_EDUCATION, "bachelor", 12, "engineering")
    assert result["field_score"] == 5  # CS = 1.0 multiplier

def test_education_no_degree_experience_substitution():
    result = calculate_education_score([], "bachelor", 9, "engineering")
    assert result["degree_score"] == 9

def test_education_no_degree_insufficient_exp():
    result = calculate_education_score([], "bachelor", 2, "engineering")
    assert result["degree_score"] == 0

def test_education_equivalent_accepted():
    result = calculate_education_score(
        [{"degree": "none", "field_of_study": None,
          "institution": None, "year": None}],
        "Equivalent experience accepted",
        6,
        "engineering"
    )
    assert result["degree_score"] > 0

def test_education_one_level_below():
    edu = [{"degree": "associate", "field_of_study": "computer science",
             "institution": "community college", "year": 2018}]
    result = calculate_education_score(edu, "bachelor", 3, "engineering")
    assert result["degree_score"] == 6

def test_education_total_capped_at_15():
    result = calculate_education_score(JANE_EDUCATION, "bachelor", 12, "engineering")
    assert result["total"] <= 15

# ---------------------------------------------------------------
# calculate_application_quality_score tests
# ---------------------------------------------------------------

def test_app_quality_not_required_full_points():
    result = calculate_application_quality_score(
        cover_letter=None,
        cover_letter_analysis=None,
        portfolio_url=None,
        linkedin_url=None,
        custom_answer_analysis=None,
        require_cover_letter=False,
        require_portfolio=False,
        require_linkedin=False,
        custom_questions=[],
    )
    assert result["total"] == 15

def test_app_quality_cover_letter_required_missing():
    result = calculate_application_quality_score(
        cover_letter=None,
        cover_letter_analysis=None,
        portfolio_url=None,
        linkedin_url=None,
        custom_answer_analysis=None,
        require_cover_letter=True,
        require_portfolio=False,
        require_linkedin=False,
        custom_questions=[],
    )
    assert result["cover_letter_score"] == 0

def test_app_quality_strong_cover_letter():
    result = calculate_application_quality_score(
        cover_letter="A" * 300,
        cover_letter_analysis={
            "word_count": 250,
            "mentions_role_title": True,
            "has_specific_example": True,
            "is_generic": False,
        },
        portfolio_url=None,
        linkedin_url=None,
        custom_answer_analysis=None,
        require_cover_letter=True,
        require_portfolio=False,
        require_linkedin=False,
        custom_questions=[],
    )
    assert result["cover_letter_score"] == 5

def test_app_quality_github_portfolio():
    result = calculate_application_quality_score(
        cover_letter=None,
        cover_letter_analysis=None,
        portfolio_url="https://github.com/janedoe",
        linkedin_url=None,
        custom_answer_analysis=None,
        require_cover_letter=False,
        require_portfolio=True,
        require_linkedin=False,
        custom_questions=[],
    )
    assert result["portfolio_score"] == 3

def test_app_quality_custom_questions_answered_well():
    result = calculate_application_quality_score(
        cover_letter=None,
        cover_letter_analysis=None,
        portfolio_url=None,
        linkedin_url=None,
        custom_answer_analysis=[
            {"question_index": 0, "word_count": 120,
             "is_relevant": True, "has_specific_example": True},
            {"question_index": 1, "word_count": 90,
             "is_relevant": True, "has_specific_example": False},
        ],
        require_cover_letter=False,
        require_portfolio=False,
        require_linkedin=False,
        custom_questions=["Question 1", "Question 2"],
    )
    assert result["custom_answers_score"] > 3

def test_app_quality_total_capped_at_15():
    result = calculate_application_quality_score(
        cover_letter="word " * 250,
        cover_letter_analysis={
            "word_count": 250, "mentions_role_title": True,
            "has_specific_example": True, "is_generic": False
        },
        portfolio_url="https://github.com/test",
        linkedin_url="https://linkedin.com/in/test",
        custom_answer_analysis=[
            {"question_index": 0, "word_count": 150,
             "is_relevant": True, "has_specific_example": True}
        ],
        require_cover_letter=True,
        require_portfolio=True,
        require_linkedin=True,
        custom_questions=["Question 1"],
    )
    assert result["total"] <= 15

# ---------------------------------------------------------------
# End-to-end score assembly — Test Case 1 (Jane Smith)
# Senior Backend Engineer, requires Python/React/AWS, 5yr exp, Bachelor's
# ---------------------------------------------------------------

def test_jane_smith_total_score():
    exp = score_experience(12, 5, JANE_JOBS, "fintech")
    skills = score_skills(JANE_SKILLS_DETAILED, ["Python", "React", "AWS"],
                          [], 3)
    edu = calculate_education_score(JANE_EDUCATION, "bachelor", 12, "engineering")
    app = calculate_application_quality_score(
        None, None, None, None, None,
        False, False, False, []
    )
    from scoring import extract_seniority_level
    role_level = 10 if abs(
        extract_seniority_level("Senior Software Engineer") -
        extract_seniority_level("Senior Backend Engineer")
    ) == 0 else 8

    total = exp["total"] + skills["total"] + edu["total"] + role_level + app["total"]
    assert total >= 75, f"Jane's total score was {total}, expected >= 75"

# ---------------------------------------------------------------
# End-to-end score assembly — Test Case 2 (Mike, junior frontend)
# Junior Frontend Developer, requires HTML/CSS/JS, 1yr exp, no degree req
# ---------------------------------------------------------------

MIKE_SKILLS_DETAILED = [
    {"name": "html", "years_used": 2.0, "last_used_year": 2024, "job_index": 0},
    {"name": "css", "years_used": 2.0, "last_used_year": 2024, "job_index": 0},
    {"name": "javascript", "years_used": 2.0, "last_used_year": 2024, "job_index": 0},
    {"name": "php", "years_used": 2.0, "last_used_year": 2024, "job_index": 0},
    {"name": "wordpress", "years_used": 2.0, "last_used_year": 2024, "job_index": 0},
]

def test_mike_skills_match():
    result = score_skills(
        skills_detailed=MIKE_SKILLS_DETAILED,
        required_skills=["HTML", "CSS", "JavaScript"],
        nice_to_have_skills=[],
        job_seniority_level=1,
    )
    assert result["required_score"] == 20
    assert "js" in result["matched_required"] or "javascript" in result["matched_required"]

def test_mike_education_no_degree_low_exp():
    result = calculate_education_score([], "none", 5, "engineering")
    assert result["total"] >= 8

def test_mike_total_score_reasonable():
    exp = score_experience(5, 1, [], None)
    skills = score_skills(MIKE_SKILLS_DETAILED, ["HTML", "CSS", "JavaScript"], [], 1)
    edu = calculate_education_score([], "none", 5, "engineering")
    app = calculate_application_quality_score(
        None, None, None, None, None,
        False, False, False, []
    )
    total = exp["total"] + skills["total"] + edu["total"] + 8 + app["total"]
    assert total >= 50, f"Mike's total score was {total}, expected >= 50"

# ---------------------------------------------------------------
# End-to-end score assembly — Test Case 3 (Alex, minimal resume)
# Mid Python Developer, requires Python, 3yr exp, Bachelor's req
# ---------------------------------------------------------------

ALEX_SKILLS_DETAILED = [
    {"name": "python", "years_used": None, "last_used_year": None, "job_index": None},
    {"name": "excel", "years_used": None, "last_used_year": None, "job_index": None},
]

def test_alex_python_matched():
    result = score_skills(
        skills_detailed=ALEX_SKILLS_DETAILED,
        required_skills=["Python"],
        nice_to_have_skills=[],
        job_seniority_level=2,
    )
    assert result["required_score"] > 0

def test_alex_education_no_degree_low_exp():
    result = calculate_education_score(
        [{"degree": "none", "field_of_study": None,
          "institution": None, "year": None}],
        "bachelor",
        2,
        "engineering"
    )
    assert result["degree_score"] == 0

def test_alex_total_score_below_50():
    exp = score_experience(2, 3, [], None)
    skills = score_skills(ALEX_SKILLS_DETAILED,
                          ["Python", "Django", "PostgreSQL", "Docker"], [], 2)
    edu = calculate_education_score(
        [{"degree": "none", "field_of_study": None,
          "institution": None, "year": None}],
        "bachelor", 2, "engineering"
    )
    app = calculate_application_quality_score(
        None, None, None, None, None,
        True, True, False, []
    )
    total = exp["total"] + skills["total"] + edu["total"] + 4 + app["total"]
    assert total <= 50, f"Alex's total score was {total}, expected <= 50"
