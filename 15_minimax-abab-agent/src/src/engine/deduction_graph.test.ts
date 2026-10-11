import { describe, it, expect } from "vitest";
import { ClueDeductionGraph } from "./deduction_graph";

describe("ClueDeductionGraph and Proof Path Solver", () => {
  it("finds the highest confidence proof path from crime evidence to culprit confession", () => {
    const graph = new ClueDeductionGraph();

    // 案发现场物证
    graph.addNode({
      id: "evidence_bloody_knife",
      type: "PHYSICAL_EVIDENCE",
      label: "沾血的手术刀（刻有编号 042）",
      confidence: 1.0,
    });

    // 中间证言与推论
    graph.addNode({
      id: "testimony_nurse",
      type: "TESTIMONY",
      label: "护士证言：042 号手术刀仅主治医师赵某可领用",
      confidence: 0.95,
      sourcePersonaId: "nurse_lin",
    });

    graph.addNode({
      id: "hypothesis_timeline",
      type: "HYPOTHESIS",
      label: "嫌疑人赵某案发时段不在其声称的办公室",
      confidence: 0.90,
    });

    // 终极破案目标
    graph.addNode({
      id: "culprit_conviction",
      type: "HYPOTHESIS",
      label: "赵医生具有作案时间与唯一作案工具",
      confidence: 0.95,
    });

    // 建立因果支持边
    graph.addEdge({
      fromId: "evidence_bloody_knife",
      toId: "testimony_nurse",
      relation: "CORROBORATES",
      weight: 0.95,
    });

    graph.addEdge({
      fromId: "testimony_nurse",
      toId: "hypothesis_timeline",
      relation: "ENTAILS",
      weight: 0.90,
    });

    graph.addEdge({
      fromId: "hypothesis_timeline",
      toId: "culprit_conviction",
      relation: "ENTAILS",
      weight: 0.92,
    });

    const result = graph.findStrongestProofPath("evidence_bloody_knife", "culprit_conviction");
    expect(result.hasProof).toBe(true);
    expect(result.pathNodes).toEqual([
      "evidence_bloody_knife",
      "testimony_nurse",
      "hypothesis_timeline",
      "culprit_conviction",
    ]);
    expect(result.chainConfidence).toBeGreaterThan(0.60);
    expect(result.unresolvedContradictions).toBe(0);
  });

  it("returns no proof when path is blocked by refuted relations or disconnected nodes", () => {
    const graph = new ClueDeductionGraph();

    graph.addNode({
      id: "fake_alibi",
      type: "TESTIMONY",
      label: "伪造的电影票根",
      confidence: 0.5,
    });

    graph.addNode({
      id: "innocence",
      type: "HYPOTHESIS",
      label: "嫌疑人完全无罪",
      confidence: 0.8,
    });

    graph.addEdge({
      fromId: "fake_alibi",
      toId: "innocence",
      relation: "REFUTES",
      weight: 0.9,
    });

    const res = graph.findStrongestProofPath("fake_alibi", "innocence");
    expect(res.hasProof).toBe(false);
    expect(res.pathNodes).toEqual([]);
  });
});
