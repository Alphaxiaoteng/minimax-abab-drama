/**
 * 智能交通 Agent 信息面板
 * Traffic Agent Info Panel Component
 */
import React from 'react';

export interface TrafficAgentInfo {
  id: string;
  speed: number;      // km/h
  target: string;
  state: 'moving' | 'stopped' | 'slowing';
  avoidanceStrategy?: string;
}

export const TrafficInfoPanel: React.FC<{
  agentInfo: TrafficAgentInfo | null;
  onClose?: () => void;
}> = ({ agentInfo, onClose }) => {
  if (!agentInfo) return null;

  return (
    <div className="panel traffic-info-panel" role="region" aria-label="交通 Agent 详情">
      <h3>Traffic Agent #{agentInfo.id}</h3>
      <dl>
        <dt>速度 Speed:</dt>
        <dd>{agentInfo.speed} km/h</dd>

        <dt>目标 Target:</dt>
        <dd>{agentInfo.target}</dd>

        <dt>状态 State:</dt>
        <dd>{agentInfo.state.toUpperCase()}</dd>

        {agentInfo.avoidanceStrategy && (
          <>
            <dt>避堵策略 Avoidance Strategy:</dt>
            <dd>{agentInfo.avoidanceStrategy}</dd>
          </>
        )}
      </dl>
      {onClose && (
        <button onClick={onClose} className="traffic-close-btn" aria-label="关闭">
          ✕
        </button>
      )}
    </div>
  );
};
