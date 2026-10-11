// Reciprocal Rank Fusion (RRF) Scoring Implementation with Detailed Breakdown
// See: https://plg.uwaterloo.ca/~gvcormac/cormack2005_rrf.pdf

export interface RankedItem {
  id?: string;
  source: string;
  rank: number;
  item: unknown;
  score?: number; // Source-specific BM25-like score
}

export interface RRFScoredItem extends RankedItem {
  id: string;
  rrfScore: number;
  sourceScores: Record<string, number>;
}

export const RRF_K = 60; // Standard k parameter for RRF

export function calculateRRF(
  itemsBySource: Record<string, RankedItem[]>,
  k: number = RRF_K
): Record<string, RRFScoredItem> {
  const result = new Map<string, RRFScoredItem>();

  // Calculate RRF scores
  for (const [source, items] of Object.entries(itemsBySource)) {
    for (let rank = 0; rank < items.length; rank++) {
      const item = items[rank];
      if (!item) continue;
      const itemId = item.id || JSON.stringify(item.item);

      // RRF formula: 1 / (k + rank)
      const rrfContribution = 1 / (k + rank);

      if (!result.has(itemId)) {
        result.set(itemId, {
          source: item.source,
          rank: item.rank,
          item: item.item,
          score: item.score,
          id: itemId,
          rrfScore: rrfContribution,
          sourceScores: { [source]: item.score ?? 0 },
        });
      } else {
        const existing = result.get(itemId)!;
        existing.rrfScore += rrfContribution;
        existing.sourceScores[source] = item.score ?? 0;
      }
    }
  }

  // Sort by RRF score descending
  const sorted = Array.from(result.values()).sort((a, b) => b.rrfScore - a.rrfScore);

  return sorted.reduce((acc, item) => {
    acc[item.id] = item;
    return acc;
  }, {} as Record<string, RRFScoredItem>);
}

export function getScoringBreakdown(itemId: string, scoredMap: Record<string, RRFScoredItem>): string {
  const item = scoredMap[itemId];
  if (!item) return "No scoring data available";

  let breakdown = `### Scoring Breakdown for Item\n\n`;
  breakdown += `- **ID**: ${itemId}\n`;
  breakdown += `- **Final RRF Score**: ${item.rrfScore.toFixed(4)}\n\n`;
  breakdown += `#### Source Contributions\n`;

  for (const [source, score] of Object.entries(item.sourceScores || {})) {
    const rank = item.rank;
    const rrfContribution = 1 / (RRF_K + rank);
    breakdown += `- **${source}**: Rank ${rank + 1}, BM25=${score.toFixed(2)}, RRF contribution=${rrfContribution.toFixed(4)}\n`;
  }

  breakdown += `\n#### Formula Explanation\n`;
  breakdown += `RRF Score = Σ(1 / (k + rank)) where k=${RRF_K}\n`;
  breakdown += `Rank is 0-indexed (top result has rank=0)\n`;

  return breakdown;
}

export function visualizeRRF(scoredMap: Record<string, RRFScoredItem>): object {
  const visualization = [];

  for (const [itemId, item] of Object.entries(scoredMap)) {
    if (Object.keys(item.sourceScores || {}).length > 1) {
      const sourceEntries = Object.entries(item.sourceScores || {});
      const primary = sourceEntries.reduce(
        (a, b) => (b[1] > a[1] ? b : a),
        ["unknown", 0]
      )[0];

      visualization.push({
        id: itemId,
        rrfScore: item.rrfScore,
        sources: item.sourceScores,
        primarySource: primary,
      });
    }
  }

  return visualization.sort((a, b) => b.rrfScore - a.rrfScore).slice(0, 10);
}
