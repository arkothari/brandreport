from pydantic import BaseModel, Field
from typing import Optional, List


class EvaluationRequest(BaseModel):
    query: str = Field(..., min_length=5, description="The category question")
    brand: str = Field(..., min_length=1, description="The brand to evaluate")
    num_samples: int = Field(default=3, ge=1, le=5, description="Queries per provider")
    providers: List[str] = Field(
        default=["claude", "chatgpt", "gemini", "perplexity"],
        description="Provider names to include in the evaluation",
    )
    locale: str = Field(default="Global (no region)", description="Geographic market context")


class BrandPositioning(BaseModel):
    framing: str          # "authoritative" | "neutral" | "hedged" | "not_mentioned"
    attributes: List[str] # qualities the AI associates with the brand
    context_summary: str  # 1-2 sentence description of how the brand is positioned
    representative_quotes: List[str]  # verbatim sentences from responses


class CompetitorInfo(BaseModel):
    name: str
    mention_count: int
    avg_position: float
    visibility_score: float


class ProviderResult(BaseModel):
    provider_name: str    # "claude" | "chatgpt" | "gemini" | "perplexity"
    provider_label: str   # "Claude (Anthropic)" etc.
    provider_color: str   # hex color for UI
    mention_rate: float
    avg_position: Optional[float]
    visibility_score: float
    responses: List[str]  # all N responses from this provider


class Recommendation(BaseModel):
    category: str
    action: str
    rationale: str
    effort: str  # "quick" | "medium" | "long"
    priority: str  # "high" | "medium" | "low"
    suggestion: Optional[str] = None  # backwards-compat, no longer populated


class SimulationRequest(BaseModel):
    query: str = Field(..., min_length=5)
    brand: str = Field(..., min_length=1)
    change_description: str = Field(..., min_length=5, description="The hypothetical change to simulate")
    num_samples: int = Field(default=3, ge=1, le=5)
    providers: List[str] = Field(default=["claude", "chatgpt", "gemini", "perplexity"])
    locale: str = Field(default="Global (no region)")


class SimulationResult(BaseModel):
    change_description: str
    visibility_score: float
    mention_rate: float
    avg_position: Optional[float]
    framing: str
    attributes: List[str]
    context_summary: str
    representative_quotes: List[str]
    provider_results: List[ProviderResult]


class WatchlistRequest(BaseModel):
    query: str = Field(..., min_length=5)
    brand: str = Field(..., min_length=1)
    competitors: List[str] = Field(..., min_length=1, max_length=5, description="1–5 competitor brand names")
    num_samples: int = Field(default=3, ge=1, le=5)
    providers: List[str] = Field(default=["claude", "chatgpt", "gemini", "perplexity"])
    locale: str = Field(default="Global (no region)")


class WatchlistEntry(BaseModel):
    name: str
    is_brand: bool
    visibility_score: float
    mention_rate: float
    avg_position: Optional[float]
    framing: str
    attributes: List[str]


class WatchlistResponse(BaseModel):
    query: str
    brand: str
    entries: List[WatchlistEntry]


class OpportunityRequest(BaseModel):
    query: str = Field(..., min_length=5)
    brand: str = Field(..., min_length=1)
    locale: str = Field(default="Global (no region)")


class OpportunityDimension(BaseModel):
    dimension: str
    angle_query: str
    visibility_score: float
    mention_rate: float
    avg_position: Optional[float]
    signal: str  # "strength" | "opportunity" | "gap"


class OpportunityResponse(BaseModel):
    brand: str
    original_query: str
    dimensions: List[OpportunityDimension]


class EvaluationResponse(BaseModel):
    query: str
    brand: str
    locale: str
    # Overall metrics (aggregated across all providers)
    mention_rate: float
    avg_position: Optional[float]
    visibility_score: float
    rank_among_competitors: Optional[int]
    total_competitors: int
    competitors: List[CompetitorInfo]
    sentiment_score: float
    sentiment_label: str
    sentiment_context: str
    brand_positioning: BrandPositioning
    # Per-provider breakdown (each carries all its responses)
    provider_results: List[ProviderResult]
    recommendations: List[Recommendation]
