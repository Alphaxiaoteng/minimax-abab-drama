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
    <div className="panel traffic-info-panel" role="region" aria-label="交通智能体详情">
      <h3>🚗 智能网联车辆 #{agentInfo.id}</h3>
      <dl>
        <dt>巡航车速</dt>
        <dd>{agentInfo.speed} km/h</dd>

        <dt>调度目标</dt>
        <dd>{agentInfo.target}</dd>

        <dt>当前状态</dt>
        <dd>{agentInfo.state === 'moving' ? '正常行驶' : agentInfo.state === 'slowing' ? '减速避让' : '停车等待'}</dd>

        {agentInfo.avoidanceStrategy && (
          <>
            <dt>协同避障策略</dt>
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
