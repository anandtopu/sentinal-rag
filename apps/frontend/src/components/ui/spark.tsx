/**
 * Inline SVG sparklines. `MiniSpark` is fixed-size for metric tiles and cards;
 * `TrendSpark` is fluid-width with an optional threshold line for trend panels.
 *
 * Both render nothing when there isn't at least two points — a deliberate
 * "no data" path so panels degrade rather than draw a misleading flat line.
 */

interface MiniSparkProps {
  data: number[];
  w?: number;
  h?: number;
  stroke?: string;
  fill?: string;
}

export function MiniSpark({
  data,
  w = 100,
  h = 28,
  stroke = 'currentColor',
  fill,
}: MiniSparkProps) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const stepX = w / (data.length - 1);
  const pts = data.map((v, i): [number, number] => [
    i * stepX,
    h - ((v - min) / range) * (h - 4) - 2,
  ]);
  const line = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ');
  const area = `M0,${h} ${pts.map((p) => `L${p[0]},${p[1]}`).join(' ')} L${w},${h} Z`;
  return (
    <svg width={w} height={h} className="block" role="img" aria-label="trend sparkline">
      {fill && <path d={area} fill={fill} opacity={0.18} />}
      <path
        d={line}
        stroke={stroke}
        strokeWidth={1.5}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface TrendSparkProps {
  data: number[];
  /** Fixed value range; defaults to padded min/max of the data. */
  min?: number;
  max?: number;
  threshold?: number;
  stroke?: string;
  height?: number;
}

export function TrendSpark({
  data,
  min,
  max,
  threshold,
  stroke = 'currentColor',
  height = 80,
}: TrendSparkProps) {
  if (!data || data.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-xs text-muted-foreground"
        style={{ height }}
      >
        Not enough data points yet.
      </div>
    );
  }
  const w = 320;
  const h = height;
  const lo = min ?? Math.min(...data);
  const hi = max ?? Math.max(...data);
  const range = hi - lo || 1;
  const step = w / (data.length - 1);
  const y = (v: number) => h - ((v - lo) / range) * h;
  const pts = data.map((v, i): [number, number] => [i * step, y(v)]);
  const line = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0]},${p[1]}`).join(' ');
  const area = `M0,${h} ${pts.map((p) => `L${p[0]},${p[1]}`).join(' ')} L${w},${h} Z`;
  return (
    <svg
      width="100%"
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="metric trend over time"
    >
      <path d={area} fill={stroke} opacity={0.15} />
      {threshold !== undefined && (
        <line
          x1={0}
          x2={w}
          y1={y(threshold)}
          y2={y(threshold)}
          stroke="hsl(var(--muted-foreground))"
          strokeDasharray="3 3"
          strokeWidth={1}
        />
      )}
      <path d={line} stroke={stroke} strokeWidth={1.6} fill="none" strokeLinecap="round" />
    </svg>
  );
}
