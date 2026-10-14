import { describe, expect, it } from 'vitest';
import { masonryLayout, pageRevealTiming } from './panelLayout';

describe('stable masonry', () => {
  it('fills the space under the shortest card without moving existing cards', () => {
    const heights = { sales: 560, offer: 380, pricing: 450, delivery: 480 };
    const first = masonryLayout(['sales', 'offer', 'pricing'], heights, 1180);
    const next = masonryLayout(['sales', 'offer', 'pricing', 'delivery'], heights, 1180);
    for (const id of ['sales', 'offer', 'pricing']) expect(next.positions[id]).toEqual(first.positions[id]);
    expect(next.positions.delivery).toEqual({ x: 400, y: 400, width: 380 });
    expect(next.height).toBe(880);
  });
  it('stacks in selection order on mobile and closes the removed-card gap', () => {
    const heights = { a: 200, b: 100, c: 300 };
    expect(masonryLayout(['a', 'b', 'c'], heights, 360).positions.c.y).toBe(340);
    expect(masonryLayout(['a', 'c'], heights, 360).positions.c.y).toBe(220);
    expect(masonryLayout([], heights, 360).height).toBe(0);
    expect(pageRevealTiming).toEqual({ duration: 850, easing: 'ease-in-out' });
  });
});
