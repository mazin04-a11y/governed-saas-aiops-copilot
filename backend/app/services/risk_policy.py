from app.schemas.records import OperationalRecommendation


HIGH_RISK_KEYWORDS = (
    "block",
    "disable",
    "delete",
    "rotate",
    "restart",
    "deploy",
    "rollback",
    "firewall",
    "authentication",
    "production",
    "customer-facing",
)


def recommendation_requires_approval(recommendation: OperationalRecommendation) -> bool:
    text = f"{recommendation.title} {recommendation.rationale}".lower()
    policy_match = any(keyword in text for keyword in HIGH_RISK_KEYWORDS)
    return recommendation.risk_level == "high" or recommendation.requires_human_approval or policy_match


def report_requires_approval(recommendations: list[OperationalRecommendation]) -> bool:
    return any(recommendation_requires_approval(item) for item in recommendations)

