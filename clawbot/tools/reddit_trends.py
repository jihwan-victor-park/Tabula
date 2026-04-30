"""Reddit social signal tool — uses PRAW when credentials are set, mock otherwise."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from clawbot.schemas.trend import RedditSignal, RedditTrendResult

# Subreddits likely to surface SMB-relevant product demand signals
_CATEGORY_SUBREDDITS: dict[str, list[str]] = {
    "default": ["deals", "frugal", "BuyItForLife"],
    "power tools": ["Tools", "DIY", "woodworking", "HomeImprovement"],
    "gardening": ["gardening", "vegetablegardening", "landscaping"],
    "hardware": ["Tools", "HomeImprovement", "DIY", "fixit"],
    "kitchen": ["Cooking", "KitchenConfidential", "mealprep"],
    "clothing": ["malefashionadvice", "femalefashionadvice", "frugalmalefashion"],
    "electronics": ["gadgets", "hardware", "pcmasterrace"],
    "sports": ["sports", "Fitness", "running", "cycling"],
    "automotive": ["MechanicAdvice", "AutoDetailing", "cars"],
    "beauty": ["SkincareAddiction", "MakeupAddiction", "beauty"],
}


def _get_subreddits(category: str) -> list[str]:
    lower = category.lower()
    for key, subs in _CATEGORY_SUBREDDITS.items():
        if key in lower or lower in key:
            return subs
    return _CATEGORY_SUBREDDITS["default"]


def _mock_result(keyword: str) -> RedditTrendResult:
    """Return placeholder data when Reddit credentials are unavailable."""
    return RedditTrendResult(
        keyword=keyword,
        top_posts=[
            RedditSignal(
                subreddit="DIY",
                post_title=f"Best {keyword} picks this season?",
                score=342,
                num_comments=87,
                url="https://reddit.com/r/DIY/demo",
                created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
            RedditSignal(
                subreddit="frugal",
                post_title=f"Where to buy {keyword} on sale",
                score=218,
                num_comments=45,
                url="https://reddit.com/r/frugal/demo",
                created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        ],
        mention_count=2,
        sentiment_summary="[mock data — set REDDIT_CLIENT_ID/SECRET to enable live signals]",
    )


def get_reddit_trends(keyword: str, category: str = "default") -> RedditTrendResult:
    """
    Search Reddit for recent hot posts mentioning the keyword.

    Falls back to mock data when REDDIT_CLIENT_ID is not configured.

    Args:
        keyword: Product or category term to search for.
        category: Product category hint used to select relevant subreddits.

    Returns:
        RedditTrendResult with top posts and a short sentiment summary.
    """
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    user_agent = os.getenv("REDDIT_USER_AGENT", "TrendAgent/1.0")

    if not client_id or not client_secret:
        return _mock_result(keyword)

    try:
        import praw  # lazy import so the module loads even without praw installed

        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )

        subreddits = _get_subreddits(category)
        combined = "+".join(subreddits)
        sub = reddit.subreddit(combined)

        posts: list[RedditSignal] = []
        for submission in sub.search(keyword, sort="hot", time_filter="month", limit=10):
            posts.append(
                RedditSignal(
                    subreddit=submission.subreddit.display_name,
                    post_title=submission.title,
                    score=submission.score,
                    num_comments=submission.num_comments,
                    url=f"https://reddit.com{submission.permalink}",
                    created_utc=datetime.fromtimestamp(
                        submission.created_utc, tz=timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            )

        # Simple sentiment: high score-to-comment ratio = positive engagement
        avg_score = sum(p.score for p in posts) / max(len(posts), 1)
        if avg_score > 500:
            sentiment = "Strong positive buzz"
        elif avg_score > 100:
            sentiment = "Moderate positive interest"
        else:
            sentiment = "Low engagement"

        return RedditTrendResult(
            keyword=keyword,
            top_posts=posts,
            mention_count=len(posts),
            sentiment_summary=sentiment,
        )

    except Exception as exc:
        return RedditTrendResult(
            keyword=keyword,
            top_posts=[],
            mention_count=0,
            sentiment_summary=f"Reddit fetch failed: {exc}",
        )
