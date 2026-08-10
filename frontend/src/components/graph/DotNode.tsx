import { type NodeProps, Handle, Position } from '@xyflow/react';

export const KIND_COLORS: Record<string, string> = {
  planet: '#f97316',
  decision: '#eab308',
  fact: '#22c55e',
  summary: '#a855f7',
  turn: '#06b6d4',
  concept: '#7c3aed',
  example: '#00bcd4',
  symbol: '#60a5fa',
  function: '#60a5fa',
  method: '#60a5fa',
  class: '#a855f7',
  module: '#22c55e',
  variable: '#eab308',
  import: '#f97316',
  constant: '#06b6d4',
  interface: '#7c3aed',
  type_alias: '#7c3aed',
  arrow: '#94a3b8',
};

export interface DotData {
  label: string;
  kind: string;
  color?: string;
  planet?: string;
  note?: unknown;
  showLabel?: boolean;
}

export const colorFor = (hex?: string, kind?: string): string =>
  hex || KIND_COLORS[kind || ''] || '#757575';

function short(str: string, max: number): string {
  return str.length > max ? `${str.slice(0, Math.max(0, max - 1))}\u2026` : str;
}

/** Obsidian-style node: a small coloured dot. Labels appear on hover/selection
 * so the view stays uncluttered (no rectangle labels hanging off every node). */
export const DotNode = ({ data, selected }: NodeProps) => {
  const d = data as unknown as DotData;
  const color = colorFor(d.color, d.kind);
  const isPlanet = d.kind === 'planet';
  const size = isPlanet ? 22 : 12;
  const show = !!(d.showLabel || selected || isPlanet);
  const glow = `0 0 ${isPlanet ? 12 : 7}px ${color}99${selected ? `, 0 0 0 6px ${color}33` : ''}`;
  const handleStyle = {
    width: 0,
    height: 0,
    minWidth: 0,
    minHeight: 0,
    background: 'transparent',
    border: 'none',
    boxShadow: 'none',
    opacity: 0,
  };
  return (
    <div
      className="nodrag nopan"
      title={d.label}
      style={{ display: 'inline-flex', alignItems: 'center', gap: show ? 8 : 0, cursor: 'pointer' }}
    >
      <Handle type="source" position={Position.Top} style={handleStyle} />
      <Handle type="target" position={Position.Bottom} style={handleStyle} />
      <div
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          border: `${isPlanet ? 3 : 2}px solid ${color}`,
          backgroundColor: `${color}22`,
          boxShadow: glow,
        }}
      />
      {show && (
        <span
          className="nodrag nopan text-[10px] leading-tight font-mono"
          style={{ color: '#cbd5e1', textShadow: '0 0 5px #000', whiteSpace: 'nowrap' }}
          title={d.label}
        >
          {short(d.label, isPlanet ? 40 : 24)}
        </span>
      )}
    </div>
  );
};
