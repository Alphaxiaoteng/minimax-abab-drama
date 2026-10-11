/**
 * deduction_graph.ts - 镜厅推理剧线索演绎有向图与破案证明链寻路引擎。
 *
 * 采用严密的图论与证据逻辑演绎：
 * 1. ClueDeductionGraph: 证据/证言/假设/矛盾四元节点与支持(ENTAILS)、反驳(REFUTES)、佐证(CORROBORATES)加权边。
 * 2. ShortestProofPath: 基于 Dijkstra 变体寻找从初始案发现场物证至真凶认罪的最短确凿证据链。
 * 3. 证据闭包完整度与破案置信度计算。
 */

export type ClueNodeType = "PHYSICAL_EVIDENCE" | "TESTIMONY" | "HYPOTHESIS" | "CONTRADICTION";
export type ClueEdgeRelation = "ENTAILS" | "REFUTES" | "CORROBORATES";

export interface ClueNode {
  id: string;
  type: ClueNodeType;
  label: string;
  confidence: number; // 初始可信度 [0.0, 1.0]
  sourcePersonaId?: string;
}

export interface ClueEdge {
  fromId: string;
  toId: string;
  relation: ClueEdgeRelation;
  weight: number; // 逻辑因果强度 [0.1, 1.0]
}

export interface ProofPathResult {
  hasProof: boolean;
  pathNodes: string[];
  chainConfidence: number;
  unresolvedContradictions: number;
}

export class ClueDeductionGraph {
  private nodes: Map<string, ClueNode> = new Map();
  private adjacency: Map<string, ClueEdge[]> = new Map();

  addNode(node: ClueNode): void {
    this.nodes.set(node.id, { ...node, confidence: Math.max(0.0, Math.min(1.0, node.confidence)) });
    if (!this.adjacency.has(node.id)) {
      this.adjacency.set(node.id, []);
    }
  }

  addEdge(edge: ClueEdge): void {
    if (!this.nodes.has(edge.fromId) || !this.nodes.has(edge.toId)) {
      throw new Error(`Cannot add edge between non-existent nodes: ${edge.fromId} -> ${edge.toId}`);
    }
    this.adjacency.get(edge.fromId)!.push(edge);
  }

  getNode(id: string): ClueNode | undefined {
    return this.nodes.get(id);
  }

  /**
   * 采用 Dijkstra 变体算法寻找最高置信度的因果证明链
   */
  findStrongestProofPath(startNodeId: string, targetNodeId: string): ProofPathResult {
    if (!this.nodes.has(startNodeId) || !this.nodes.has(targetNodeId)) {
      return { hasProof: false, pathNodes: [], chainConfidence: 0.0, unresolvedContradictions: 0 };
    }

    // 优先队列模拟：记录最大乘积置信度
    const bestConfidence: Map<string, number> = new Map();
    const predecessor: Map<string, string> = new Map();

    for (const id of this.nodes.keys()) {
      bestConfidence.set(id, 0.0);
    }
    bestConfidence.set(startNodeId, this.nodes.get(startNodeId)!.confidence);

    const visited: Set<string> = new Set();
    const queue: string[] = [startNodeId];

    while (queue.length > 0) {
      // 选取当前置信度最高的节点
      queue.sort((a, b) => bestConfidence.get(b)! - bestConfidence.get(a)!);
      const curr = queue.shift()!;

      if (curr === targetNodeId) break;
      if (visited.has(curr)) continue;
      visited.add(curr);

      const edges = this.adjacency.get(curr) || [];
      for (const edge of edges) {
        // 反驳关系不构成支持证明链
        if (edge.relation === "REFUTES") continue;

        const targetNode = this.nodes.get(edge.toId)!;
        const currentConf = bestConfidence.get(curr)!;
        const newConf = currentConf * edge.weight * targetNode.confidence;

        if (newConf > bestConfidence.get(edge.toId)!) {
          bestConfidence.set(edge.toId, newConf);
          predecessor.set(edge.toId, curr);
          queue.push(edge.toId);
        }
      }
    }

    const targetConf = bestConfidence.get(targetNodeId) || 0.0;
    if (targetConf <= 0.0) {
      return { hasProof: false, pathNodes: [], chainConfidence: 0.0, unresolvedContradictions: 0 };
    }

    // 回溯路径
    const path: string[] = [];
    let curr: string | undefined = targetNodeId;
    while (curr) {
      path.unshift(curr);
      curr = predecessor.get(curr);
    }

    // 统计图中未解决的矛盾节点数量
    let contradictionCount = 0;
    for (const node of this.nodes.values()) {
      if (node.type === "CONTRADICTION") contradictionCount++;
    }

    return {
      hasProof: true,
      pathNodes: path,
      chainConfidence: Math.round(targetConf * 1000) / 1000,
      unresolvedContradictions: contradictionCount,
    };
  }
}
