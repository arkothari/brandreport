import asyncio
from typing import Optional, Dict, List
from services.llm_service import LLMService
from services.providers.base import LLMProvider


class BrandEvaluator:
    def __init__(self, llm_service: LLMService, providers: List[LLMProvider]):
        self.llm = llm_service
        self.providers = providers

    async def evaluate(
        self,
        query: str,
        brand: str,
        num_samples: int,
        providers: List[LLMProvider],
        locale: str = "Global (no region)",
    ) -> Dict:
        # Apply locale context to the query sent to AI providers
        if locale and locale != "Global (no region)":
            localized_query = f"{query} (Answer from the perspective of someone based in {locale}.)"
        else:
            localized_query = query

        # Step 1: Query every provider concurrently (each runs num_samples queries in parallel)
        async def query_provider(provider: LLMProvider):
            responses = list(await asyncio.gather(
                *[provider.query(localized_query) for _ in range(num_samples)]
            ))
            return provider, responses

        raw_results = await asyncio.gather(*[query_provider(p) for p in providers])

        # Step 2: Per-provider metrics
        provider_data: List[Dict] = []
        all_responses: List[str] = []

        for provider, responses in raw_results:
            mentions = [self.llm.extract_mentions(r, brand) for r in responses]
            hits = [m for m in mentions if m["mentioned"]]
            mention_rate = len(hits) / num_samples
            positions = [m["position"] for m in hits if m["position"] is not None]
            avg_pos = sum(positions) / len(positions) if positions else None

            provider_data.append({
                "provider_name": provider.name,
                "provider_label": provider.label,
                "provider_color": provider.color,
                "mention_rate": mention_rate,
                "avg_position": avg_pos,
                "visibility_score": self._score(mention_rate, avg_pos),
                "responses": responses,
            })
            all_responses.extend(responses)

        # Step 3: Aggregate metrics across all providers
        all_mentions = [self.llm.extract_mentions(r, brand) for r in all_responses]
        total_hits = sum(1 for m in all_mentions if m["mentioned"])
        overall_mention_rate = total_hits / len(all_mentions) if all_mentions else 0.0
        all_positions = [m["position"] for m in all_mentions if m["mentioned"] and m["position"]]
        overall_avg_pos = sum(all_positions) / len(all_positions) if all_positions else None
        overall_visibility = self._score(overall_mention_rate, overall_avg_pos)

        # Step 4: Competitor extraction + sentiment + positioning (concurrent)
        competitor_names, sentiment, positioning = await asyncio.gather(
            self.llm.extract_competitors(all_responses, brand),
            self.llm.analyze_sentiment(all_responses, brand),
            self.llm.analyze_brand_positioning(all_responses, brand, query),
        )

        # Step 5: Score each competitor across all responses
        competitor_data: List[Dict] = []
        for name in competitor_names[:12]:
            comp_mentions = [self.llm.extract_mentions(r, name) for r in all_responses]
            comp_hits = [m for m in comp_mentions if m["mentioned"]]
            if not comp_hits:
                continue
            comp_rate = len(comp_hits) / len(all_responses)
            comp_pos = [m["position"] for m in comp_hits if m["position"] is not None]
            comp_avg = sum(comp_pos) / len(comp_pos) if comp_pos else 5.0
            competitor_data.append({
                "name": name,
                "mention_count": len(comp_hits),
                "avg_position": round(comp_avg, 1),
                "visibility_score": round(self._score(comp_rate, comp_avg), 1),
            })

        competitor_data.sort(key=lambda x: x["visibility_score"], reverse=True)

        # Step 6: Brand rank
        rank: Optional[int] = None
        competitors_above: List[str] = []
        if overall_mention_rate > 0:
            better = [c for c in competitor_data if c["visibility_score"] > overall_visibility]
            rank = len(better) + 1
            competitors_above = [c["name"] for c in better[:5]]

        # Step 7: Recommendations (uses Claude via llm_service)
        recommendations = await self.llm.generate_recommendations({
            "brand": brand,
            "query": query,
            "mention_rate": overall_mention_rate,
            "avg_position": overall_avg_pos,
            "visibility_score": overall_visibility,
            "rank": rank,
            "competitors_above": competitors_above,
            "competitors_above_scores": [
                {"name": c["name"], "score": c["visibility_score"]}
                for c in competitor_data if c["visibility_score"] > overall_visibility
            ][:5],
            "sentiment_label": sentiment.get("label", "neutral"),
            "sentiment_score": sentiment.get("score", 0.0),
            "sentiment_context": sentiment.get("context", ""),
            "framing": positioning.get("framing", "not_mentioned"),
            "attributes": positioning.get("attributes", []),
            "context_summary": positioning.get("context_summary", ""),
            "representative_quotes": positioning.get("representative_quotes", []),
        })

        # Step 8: Build provider result list (store all responses in full)
        provider_results = []
        for pd in provider_data:
            provider_results.append({
                "provider_name": pd["provider_name"],
                "provider_label": pd["provider_label"],
                "provider_color": pd["provider_color"],
                "mention_rate": round(pd["mention_rate"], 3),
                "avg_position": round(pd["avg_position"], 1) if pd["avg_position"] is not None else None,
                "visibility_score": round(pd["visibility_score"], 1),
                "responses": pd["responses"],
            })

        return {
            "query": query,
            "brand": brand,
            "locale": locale,
            "mention_rate": round(overall_mention_rate, 3),
            "avg_position": round(overall_avg_pos, 1) if overall_avg_pos is not None else None,
            "visibility_score": round(overall_visibility, 1),
            "rank_among_competitors": rank,
            "total_competitors": len(competitor_data),
            "competitors": competitor_data,
            "sentiment_score": round(sentiment.get("score", 0.0), 2),
            "sentiment_label": sentiment.get("label", "neutral"),
            "sentiment_context": sentiment.get("context", ""),
            "brand_positioning": positioning,
            "provider_results": provider_results,
            "recommendations": recommendations,
        }

    async def simulate(
        self,
        query: str,
        brand: str,
        change_description: str,
        num_samples: int,
        providers: List[LLMProvider],
        locale: str = "Global (no region)",
    ) -> Dict:
        # Build the hypothetical query — inject the change context so providers respond
        # as if the change already happened. This is directional, not predictive.
        change_context = f"(For this response, assume that {brand} has {change_description}.)"
        if locale and locale != "Global (no region)":
            localized_query = (
                f"{query} {change_context} "
                f"(Answer from the perspective of someone based in {locale}.)"
            )
        else:
            localized_query = f"{query} {change_context}"

        # Step 1: Query every provider concurrently
        async def query_provider(provider: LLMProvider):
            responses = list(await asyncio.gather(
                *[provider.query(localized_query) for _ in range(num_samples)]
            ))
            return provider, responses

        raw_results = await asyncio.gather(*[query_provider(p) for p in providers])

        # Step 2: Per-provider metrics
        provider_data: List[Dict] = []
        all_responses: List[str] = []

        for provider, responses in raw_results:
            mentions = [self.llm.extract_mentions(r, brand) for r in responses]
            hits = [m for m in mentions if m["mentioned"]]
            mention_rate = len(hits) / num_samples
            positions = [m["position"] for m in hits if m["position"] is not None]
            avg_pos = sum(positions) / len(positions) if positions else None

            provider_data.append({
                "provider_name": provider.name,
                "provider_label": provider.label,
                "provider_color": provider.color,
                "mention_rate": mention_rate,
                "avg_position": avg_pos,
                "visibility_score": self._score(mention_rate, avg_pos),
                "responses": responses,
            })
            all_responses.extend(responses)

        # Step 3: Aggregate metrics across all providers
        all_mentions = [self.llm.extract_mentions(r, brand) for r in all_responses]
        total_hits = sum(1 for m in all_mentions if m["mentioned"])
        overall_mention_rate = total_hits / len(all_mentions) if all_mentions else 0.0
        all_positions = [m["position"] for m in all_mentions if m["mentioned"] and m["position"]]
        overall_avg_pos = sum(all_positions) / len(all_positions) if all_positions else None
        overall_visibility = self._score(overall_mention_rate, overall_avg_pos)

        # Step 4: Positioning analysis only (skip competitors + sentiment — faster run)
        positioning = await self.llm.analyze_brand_positioning(all_responses, brand, query)

        # Step 5: Build provider result list
        provider_results = []
        for pd in provider_data:
            provider_results.append({
                "provider_name": pd["provider_name"],
                "provider_label": pd["provider_label"],
                "provider_color": pd["provider_color"],
                "mention_rate": round(pd["mention_rate"], 3),
                "avg_position": round(pd["avg_position"], 1) if pd["avg_position"] is not None else None,
                "visibility_score": round(pd["visibility_score"], 1),
                "responses": pd["responses"],
            })

        return {
            "change_description": change_description,
            "visibility_score": round(overall_visibility, 1),
            "mention_rate": round(overall_mention_rate, 3),
            "avg_position": round(overall_avg_pos, 1) if overall_avg_pos is not None else None,
            "framing": positioning.get("framing", "not_mentioned"),
            "attributes": positioning.get("attributes", []),
            "context_summary": positioning.get("context_summary", ""),
            "representative_quotes": positioning.get("representative_quotes", []),
            "provider_results": provider_results,
        }

    async def opportunity_map(
        self,
        query: str,
        brand: str,
        locale: str = "Global (no region)",
    ) -> Dict:
        # Step 1: Generate 6 angle queries
        dimensions = await self.llm.generate_opportunity_dimensions(query, brand)
        if not dimensions:
            raise ValueError("Could not generate opportunity dimensions — try again.")

        # Step 2: Score each dimension with 2 Claude samples (runs all 12 queries concurrently)
        async def score_dimension(dim: Dict) -> Dict:
            angle = dim["angle_query"]
            localized = (
                f"{angle} (Answer from the perspective of someone based in {locale}.)"
                if locale and locale != "Global (no region)" else angle
            )
            responses = list(await asyncio.gather(
                self.llm.query_about_category(localized),
                self.llm.query_about_category(localized),
            ))
            mentions = [self.llm.extract_mentions(r, brand) for r in responses]
            hits = [m for m in mentions if m["mentioned"]]
            mention_rate = len(hits) / len(responses)
            positions = [m["position"] for m in hits if m["position"] is not None]
            avg_pos = sum(positions) / len(positions) if positions else None
            score = self._score(mention_rate, avg_pos)

            if score >= 55:
                signal = "strength"
            elif score >= 20:
                signal = "opportunity"
            else:
                signal = "gap"

            return {
                "dimension":      dim["dimension"],
                "angle_query":    dim["angle_query"],
                "visibility_score": round(score, 1),
                "mention_rate":   mention_rate,
                "avg_position":   round(avg_pos, 1) if avg_pos is not None else None,
                "signal":         signal,
            }

        results = list(await asyncio.gather(*[score_dimension(d) for d in dimensions]))
        signal_order = {"strength": 0, "opportunity": 1, "gap": 2}
        results.sort(key=lambda x: (signal_order.get(x["signal"], 3), -x["visibility_score"]))

        return {"brand": brand, "original_query": query, "dimensions": results}

    async def watchlist(
        self,
        query: str,
        brand: str,
        competitors: List[str],
        num_samples: int,
        providers: List[LLMProvider],
        locale: str = "Global (no region)",
    ) -> Dict:
        if locale and locale != "Global (no region)":
            localized_query = f"{query} (Answer from the perspective of someone based in {locale}.)"
        else:
            localized_query = query

        # Query all providers once — all brands share the same responses
        async def query_provider(provider: LLMProvider):
            return list(await asyncio.gather(
                *[provider.query(localized_query) for _ in range(num_samples)]
            ))

        provider_responses = await asyncio.gather(*[query_provider(p) for p in providers])
        all_responses = [r for responses in provider_responses for r in responses]

        # Score every brand concurrently — mentions are sync, positioning is async
        async def score_brand(name: str, is_brand: bool) -> Dict:
            mentions = [self.llm.extract_mentions(r, name) for r in all_responses]
            hits = [m for m in mentions if m["mentioned"]]
            mention_rate = len(hits) / len(all_responses) if all_responses else 0.0
            positions = [m["position"] for m in hits if m["position"] is not None]
            avg_pos = sum(positions) / len(positions) if positions else None
            positioning = await self.llm.analyze_brand_positioning(all_responses, name, query)
            return {
                "name": name,
                "is_brand": is_brand,
                "visibility_score": round(self._score(mention_rate, avg_pos), 1),
                "mention_rate": round(mention_rate, 3),
                "avg_position": round(avg_pos, 1) if avg_pos is not None else None,
                "framing": positioning.get("framing", "not_mentioned"),
                "attributes": positioning.get("attributes", []),
            }

        clean_competitors = [c.strip() for c in competitors if c.strip()]
        entries = list(await asyncio.gather(
            score_brand(brand, True),
            *[score_brand(c, False) for c in clean_competitors],
        ))
        entries.sort(key=lambda x: x["visibility_score"], reverse=True)

        return {"query": query, "brand": brand, "entries": entries}

    def _score(self, mention_rate: float, avg_position: Optional[float]) -> float:
        """Composite visibility score 0–100.
        60 pts from mention rate, 40 pts from position (rank 1 = full, rank 10+ ≈ 0).
        """
        mention_component = mention_rate * 60.0
        position_component = 0.0
        if avg_position is not None and avg_position > 0:
            position_component = max(0.0, 40.0 * (1.0 - (avg_position - 1.0) / 9.0))
        return min(100.0, mention_component + position_component)
