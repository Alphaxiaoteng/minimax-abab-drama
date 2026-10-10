import type { EngineKind } from "../core/contract";

interface Props {
  engine: EngineKind;
  onChange(next: EngineKind): void;
}

const OPTIONS: Array<{ value: EngineKind; label: string }> = [
  { value: "three", label: "Three.js" },
  { value: "css", label: "CSS" },
];

export function EngineToggle({ engine, onChange }: Props) {
  return (
    <div className="engine-toggle" role="radiogroup" aria-label="渲染引擎">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={engine === opt.value}
          className={`engine-btn${engine === opt.value ? " active" : ""}`}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}