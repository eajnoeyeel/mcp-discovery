import { PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer } from 'recharts';
import type { GEOScore } from '@/types/database';

const dimensionLabels: Record<string, string> = {
  clarity: 'Clarity',
  disambiguation: 'Disambig',
  parameter_coverage: 'Params',
  boundary: 'Boundary',
  stats: 'Stats',
  precision: 'Precision',
};

export default function GEOScoreRadar({ geoScore, size = 300 }: { geoScore: GEOScore; size?: number }) {
  const data = Object.entries(dimensionLabels).map(([key, label]) => ({
    dimension: label,
    value: geoScore[key as keyof GEOScore] as number,
  }));

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} cx="50%" cy="50%">
          <PolarGrid stroke="hsl(var(--border))" />
          <PolarAngleAxis dataKey="dimension" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }} />
          <PolarRadiusAxis angle={90} domain={[0, 1]} tick={false} axisLine={false} />
          <Radar
            name="GEO"
            dataKey="value"
            stroke="hsl(var(--primary))"
            fill="hsl(var(--primary))"
            fillOpacity={0.25}
            strokeWidth={2}
          />
        </RadarChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <span className="text-2xl font-bold text-foreground">{(geoScore.total * 100).toFixed(0)}</span>
      </div>
    </div>
  );
}
