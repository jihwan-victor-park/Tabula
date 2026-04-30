import { useEffect, useMemo, useState } from "react";

export type Point = { x: number; y: number };

export type LayoutData = {
  w: number;
  h: number;
  mapPositions: Point[];
  circlePositions: Point[];
  center: Point;
  radius: number;
};

const N = 8;

const MAP_PCT: [number, number][] = [
  [0.75, 0.28],
  [0.23, 0.39],
  [0.29, 0.52],
  [0.82, 0.18],
  [0.88, 0.38],
  [0.78, 0.64],
  [0.67, 0.56],
  [0.18, 0.24],
];

export function useLayout(): LayoutData {
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight });

  useEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return useMemo(() => {
    const { w, h } = size;
    const cx = w * 0.50;
    const cy = h * 0.50;
    const radius = Math.min(w, h) * 0.32;

    const mapPositions = MAP_PCT.map(([fx, fy]) => ({ x: w * fx, y: h * fy }));

    const circlePositions: Point[] = [];
    for (let i = 0; i < N; i++) {
      const angle = -Math.PI / 2 + (i * 2 * Math.PI) / N;
      circlePositions.push({
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      });
    }

    return { w, h, mapPositions, circlePositions, center: { x: cx, y: cy }, radius };
  }, [size]);
}
