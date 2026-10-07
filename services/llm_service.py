import re
import json
from typing import List, Dict, Optional
import anthropic


class LLMService:
    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.fast_model = "claude-haiku-4-5-20251001"
        self.smart_model = "claude-sonnet-5"

    async def query_about_category(self, question: str) -> str:
        """Send a category question to Claude and get a ranked response."""
        response = await self.client.messages.create(
            model=self.fast_model,
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": (
                    f"{question}\n\n"
                    "Provide a comprehensive answer with the top options ranked. "
                    "Use numbered rankings (1., 2., 3. …) where appropriate."
                )
            }]
        )
        return response.content[0].text

    def extract_mentions(self, text: str, brand: str) -> Dict:
        """Extract brand mention position and frequency from a response."""
        text_lower = text.lower()
        brand_lower = brand.lower()

        # Also try the first word(s) of multi-word brands as a core match
        brand_words = brand_lower.split()
        brand_core = " ".join(brand_words[:2]) if len(brand_words) > 1 else brand_words[0]

        full_match = brand_lower in text_lower
        core_match = (brand_core != brand_lower) and (brand_core in text_lower) and len(brand_core) > 3
        mentioned = full_match or core_match
        search_term = brand_lower if full_match else brand_core

        position = None
        if mentioned:
            # Try explicit numbered-list position first
            numbered = re.compile(
                r'(?:^|\n)\s*(\d+)[.\)]\s+(?:[^\n]{0,60})?' + re.escape(search_term),
                re.IGNORECASE | re.MULTILINE,
            )
            m = numbered.search(text_lower)
            if m:
                position = int(m.group(1))
            else:
                # Fall back to order of first occurrence
                idx = text_lower.find(search_term)
                before = text[:idx]
                markers = re.findall(r'\n\n|\d+[.\)]|\*\*|-\s', before)
                position = max(1, len(markers))

        count = text_lower.count(search_term) if mentioned else 0
        return {"mentioned": mentioned, "position": position, "count": count}

    async def extract_competitors(self, responses: List[str], brand: str) -> List[str]:
        """Ask Claude to identify competitor brands mentioned across the responses."""
        combined = "\n---\n".join(responses)[:3000]
        prompt = (
            f'Extract all brand, company, and product names from these AI responses. '
            f'Exclude "{brand}". Return ONLY a JSON array of unique proper names.\n\n'
            f"Responses:\n{combined}"
        )
        response = await self.client.messages.create(
            model=self.fast_model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        try:
            text = response.content[0].text.strip()
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if m:
                brands = json.loads(m.group())
                # Only keep names that actually appear in the raw responses (hallucination guard)
                all_text = " ".join(responses).lower()
                return [b for b in brands if isinstance(b, str) and 1 < len(b) < 60 and b.lower() in all_text]
        except Exception:
            pass
        return []

    async def analyze_sentiment(self, responses: List[str], brand: str) -> Dict:
        """Rate the AI's sentiment toward the brand across all responses."""
        combined = "\n---\n".join(responses)[:2000]
        prompt = (
            f'Analyze the overall sentiment toward "{brand}" in these AI responses. '
            f'If "{brand}" is not mentioned, use score 0 and label "neutral".\n\n'
            f'Return ONLY valid JSON: {{"score": 0.7, "label": "positive", "context": "one sentence"}}\n\n'
            f"Responses:\n{combined}"
        )
        response = await self.client.messages.create(
            model=self.fast_model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        try:
            text = response.content[0].text.strip()
            m = re.search(r'\{[^{}]+\}', text, re.DOTALL)
            if m:
                result = json.loads(m.group())
                if "score" in result and "label" in result:
                    return result
        except Exception:
            pass
        return {"score": 0.0, "label": "neutral", "context": "Sentiment could not be determined."}

    async def analyze_brand_positioning(self, responses: List[str], brand: str, query: str) -> Dict:
        """Analyze how the brand is framed — not just mentioned — across all responses."""
        combined = "\n\n---\n\n".join(responses[:9])[:4000]
        prompt = f"""Analyze how "{brand}" is positioned in these AI-generated responses to the query: "{query}"

RESPONSES:
{combined}

Return ONLY a JSON object with this exact structure:
{{
  "framing": "authoritative" | "neutral" | "hedged" | "not_mentioned",
  "attributes": ["up to 5 short qualities the AI associates with {brand}"],
  "context_summary": "1-2 sentences describing how {brand} is positioned relative to competitors",
  "representative_quotes": ["up to 3 verbatim sentences from the responses that mention {brand}"]
}}

Framing definitions:
- authoritative: Brand is recommended first or described as "best / leading / top choice"
- neutral: Brand listed among options without strong endorsement
- hedged: Brand mentioned with qualifiers like "some prefer", "depending on your needs", "for specific use cases"
- not_mentioned: Brand does not appear in any response

Only use verbatim text for representative_quotes — copy the sentences exactly as they appear.
Return only the JSON object, no other text."""
        response = await self.client.messages.create(
            model=self.fast_model,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}]
        )
        try:
            text = response.content[0].text.strip()
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                result = json.loads(m.group())
                if "framing" in result:
                    result.setdefault("attributes", [])
                    result.setdefault("context_summary", "")
                    result.setdefault("representative_quotes", [])
                    result["representative_quotes"] = self._verify_quotes(
                        result["representative_quotes"], responses
                    )
                    return result
        except Exception:
            pass
        return {
            "framing": "not_mentioned",
            "attributes": [],
            "context_summary": "Positioning analysis could not be determined.",
            "representative_quotes": [],
        }

    def _verify_quotes(self, quotes: List[str], responses: List[str]) -> List[str]:
        """Remove quotes that don't appear in the raw responses (hallucination guard)."""
        combined = " ".join(responses).lower()
        verified = []
        window = 30
        for quote in quotes:
            q = re.sub(r'\s+', ' ', quote.strip().lower())
            # Normalize curly quotes to straight
            q = q.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
            if len(q) <= window:
                if q in combined:
                    verified.append(quote)
            else:
                # Accept if any 30-char chunk of the quote appears in responses
                if any(q[i:i+window] in combined for i in range(0, len(q) - window + 1, 10)):
                    verified.append(quote)
        return verified

    async def generate_opportunity_dimensions(self, query: str, brand: str) -> List[Dict]:
        """Generate 6 distinct query angles to map brand visibility across dimensions."""
        prompt = f"""You are a GEO (Generative Engine Optimization) strategist.

Given the original query "{query}" and brand "{brand}", generate exactly 6 natural query variations that explore different dimensions of this category.

Cover meaningfully different angles such as: value/price, specific audience (business, families, budget, etc.), trust/reputation, features/capabilities, mobile/technology experience, geographic or situational context.

Return ONLY a JSON array of exactly 6 objects:
[
  {{"dimension": "2-4 word label", "angle_query": "the full query a user would type"}}
]

Rules: each query must feel natural; no two queries should overlap significantly; dimension label must be short (2-4 words)."""
        response = await self.client.messages.create(
            model=self.fast_model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        try:
            text = response.content[0].text.strip()
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if m:
                dims = json.loads(m.group())
                if isinstance(dims, list):
                    valid = [d for d in dims if "dimension" in d and "angle_query" in d]
                    if valid:
                        return valid[:6]
        except Exception:
            pass
        return []

    async def generate_recommendations(self, eval_data: Dict) -> List[Dict]:
        """Generate GEO improvement recommendations using Claude Sonnet."""
        above = eval_data.get("competitors_above", [])
        above_scores = eval_data.get("competitors_above_scores", [])
        framing = eval_data.get("framing", "not_mentioned")
        attributes = eval_data.get("attributes", [])
        quotes = eval_data.get("representative_quotes", [])
        context_summary = eval_data.get("context_summary", "")
        sentiment_context = eval_data.get("sentiment_context", "")

        above_str = ", ".join(
            f"{c['name']} (score {c['score']:.0f})" for c in above_scores
        ) if above_scores else "None"

        quotes_str = "\n".join(f'  - "{q}"' for q in quotes[:3]) if quotes else "  (none found)"
        attrs_str = ", ".join(attributes) if attributes else "none identified"

        prompt = f"""You are a GEO (Generative Engine Optimization) strategist. Your job is to give brutally specific, immediately executable recommendations — not generic advice.

CURRENT STATE
Brand: {eval_data['brand']}
Query evaluated: "{eval_data['query']}"
Visibility score: {eval_data['visibility_score']:.1f}/100  |  Mention rate: {eval_data['mention_rate']:.0%}  |  Avg position: {eval_data.get('avg_position') or 'not ranked'}
AI framing of brand: {framing}
Attributes AI associates with this brand: {attrs_str}
Sentiment: {eval_data.get('sentiment_label', 'neutral')} — {sentiment_context}
How brand is described: {context_summary}

HOW COMPETITORS RANK HIGHER
{above_str}

WHAT AI RESPONSES ACTUALLY SAY ABOUT THIS BRAND
{quotes_str}

TASK
Generate exactly 5 recommendations. Each must be grounded in the data above — reference specific gaps, competitors, or quote patterns.

Rules:
1. "action" must be a single concrete sentence starting with a verb (e.g. "Publish a dedicated comparison page titled '{eval_data['brand']} vs [competitor] for [use case]'")
2. "rationale" must explain WHY this specific action moves the GEO needle for this exact brand/query combination — mention the specific gap or pattern it addresses
3. "effort" = "quick" (< 1 week), "medium" (1–4 weeks), or "long" (1–3 months)
4. "category" = one of: Content Gap, Framing Fix, Competitor Response, Authority Building, Review & UGC
5. "priority" = "high", "medium", or "low" based on visibility impact

Return ONLY a valid JSON array of exactly 5 objects:
[
  {{
    "category": "...",
    "action": "single imperative sentence",
    "rationale": "2 sentences explaining the GEO impact for this specific brand/query",
    "effort": "quick | medium | long",
    "priority": "high | medium | low"
  }}
]"""
        response = await self.client.messages.create(
            model=self.smart_model,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        try:
            text = response.content[0].text.strip()
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if m:
                recs = json.loads(m.group())
                if isinstance(recs, list) and recs:
                    return recs
        except Exception:
            pass

        brand = eval_data["brand"]
        query = eval_data["query"]
        return [
            {
                "category": "Content Gap",
                "action": f"Publish a dedicated long-form page answering '{query}' with {brand}'s specific differentiators and use-case examples.",
                "rationale": f"AI models surface brands whose web content directly and authoritatively answers the query. If {brand} lacks this page, it cannot be cited.",
                "effort": "medium",
                "priority": "high",
            },
            {
                "category": "Authority Building",
                "action": f"Pitch {brand} case studies or data reports to 3 top-tier industry publications this quarter.",
                "rationale": "AI training data weights authoritative third-party citations heavily. Earned mentions in publications like TechCrunch, G2, or niche trade press directly increase mention rate.",
                "effort": "long",
                "priority": "high",
            },
            {
                "category": "Review & UGC",
                "action": f"Run a structured campaign to collect 50 detailed reviews on G2 and Reddit that mention {brand}'s specific capabilities relevant to '{query}'.",
                "rationale": "User-generated content on high-DA forums is a primary training signal. Reviews that name specific features align {brand}'s profile with the query intent.",
                "effort": "medium",
                "priority": "medium",
            },
            {
                "category": "Framing Fix",
                "action": f"Update {brand}'s Wikipedia and Wikidata entry to explicitly include the use-case keywords from '{query}'.",
                "rationale": "Knowledge graph entries directly shape how AI models frame a brand. Missing or vague category associations keep the brand in 'hedged' or 'neutral' framing.",
                "effort": "quick",
                "priority": "medium",
            },
            {
                "category": "Competitor Response",
                "action": f"Create a comparison landing page '{brand} vs [top competitor]' targeting the exact query angle.",
                "rationale": "Comparison content is heavily indexed and cited by AI responses when users search competitive queries. It forces {brand} into the conversation alongside higher-ranked rivals.",
                "effort": "medium",
                "priority": "low",
            },
        ]
