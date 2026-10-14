import { useLayoutEffect, useRef, useState } from 'react';

export const pageRevealFrames = [{ opacity: 0, filter: 'blur(10px)', transform: 'translateY(6px)' }, { opacity: 1, filter: 'blur(0px)', transform: 'translateY(0)' }];
export const pageRevealTiming = { duration: 850, easing: 'ease-in-out' };

export function masonryLayout(ids: readonly string[], heights: Record<string, number>, width: number) {
  const columns = Math.max(1, Math.floor((width + 20) / 380));
  const cardWidth = Math.max(0, (width - (columns - 1) * 20) / columns);
  const bottoms = Array<number>(columns).fill(0);
  const positions: Record<string, { x: number; y: number; width: number }> = {};
  for (const id of ids) {
    const column = bottoms.indexOf(Math.min(...bottoms));
    positions[id] = { x: column * (cardWidth + 20), y: bottoms[column], width: cardWidth };
    bottoms[column] += (heights[id] ?? 400) + 20;
  }
  return { positions, height: ids.length ? Math.max(...bottoms) - 20 : 0 };
}

export function usePanelLayout(wantedIds: string[], allIds: string[], active: boolean, reduceMotion: boolean) {
  const container = useRef<HTMLDivElement>(null);
  const [displayedIds, setDisplayedIds] = useState(wantedIds);
  const [width, setWidth] = useState(0);
  const [heights, setHeights] = useState<Record<string, number>>({});
  const latestWanted = useRef(new Set(wantedIds));
  latestWanted.current = new Set(wantedIds);
  const targets = useRef(new Map(wantedIds.map(id => [id, true])));
  const animations = useRef(new Map<string, Animation>());
  const wantedKey = JSON.stringify(wantedIds), allKey = JSON.stringify(allIds), displayedKey = JSON.stringify(displayedIds);

  useLayoutEffect(() => {
    const root = container.current;
    if (!root || !active) return;
    const measure = () => {
      setWidth(root.getBoundingClientRect().width);
      setHeights(current => {
        const next = { ...current };
        let changed = false;
        for (const card of root.querySelectorAll<HTMLElement>('.home-panel-item')) {
          const id = card.dataset.panelId!;
          const height = card.querySelector('.panel-reveal')?.getBoundingClientRect().height;
          if (height && Math.abs((current[id] ?? 0) - height) > .5) { next[id] = height; changed = true; }
        }
        return changed ? next : current;
      });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    for (const content of root.querySelectorAll('.panel-reveal')) observer.observe(content);
    measure();
    return () => observer.disconnect();
  }, [allKey, active]);

  useLayoutEffect(() => {
    setDisplayedIds(current => {
      const sameCards = current.length === wantedIds.length && current.every(id => wantedIds.includes(id));
      const next = !active || reduceMotion || sameCards ? wantedIds : [...current.filter(id => allIds.includes(id)), ...wantedIds.filter(id => !current.includes(id))];
      return JSON.stringify(current) === JSON.stringify(next) ? current : next;
    });
  }, [wantedKey, allKey, active, reduceMotion]);

  useLayoutEffect(() => {
    const root = container.current;
    if (!root) return;
    for (const id of allIds) {
      const card = [...root.querySelectorAll<HTMLElement>('.home-panel-item')].find(item => item.dataset.panelId === id);
      const content = card?.querySelector('.panel-reveal');
      if (!content) continue;
      const displayed = displayedIds.includes(id), wanted = latestWanted.current.has(id);
      if (!displayed || !active || reduceMotion) {
        animations.current.get(id)?.cancel(); animations.current.delete(id);
        targets.current.set(id, displayed && wanted);
        continue;
      }
      if (targets.current.get(id) === wanted) continue;
      const previous = animations.current.get(id);
      const style = getComputedStyle(content);
      const from = { opacity: style.opacity, filter: style.filter, transform: style.transform };
      previous?.cancel();
      const frames = wanted ? previous ? [from, pageRevealFrames[1]] : pageRevealFrames : [from, pageRevealFrames[0]];
      const animation = content.animate(frames, { ...pageRevealTiming, fill: 'forwards' });
      animations.current.set(id, animation); targets.current.set(id, wanted);
      void animation.finished.then(() => {
        if (animations.current.get(id) !== animation) return;
        if (!latestWanted.current.has(id)) setDisplayedIds(current => {
          const remaining = current.filter(item => item !== id);
          return remaining.length === latestWanted.current.size ? [...latestWanted.current] : remaining;
        });
        else { animation.cancel(); animations.current.delete(id); }
      }).catch(() => { /* Reversing a transition cancels its old completion. */ });
    }
  }, [wantedKey, allKey, displayedKey, active, reduceMotion]);

  useLayoutEffect(() => () => {
    for (const animation of animations.current.values()) animation.cancel();
    animations.current.clear();
  }, []);

  const enteringIds = new Set(displayedIds.filter(id => latestWanted.current.has(id) && targets.current.get(id) !== true));
  return { container, displayedIds, enteringIds, ...masonryLayout(displayedIds, heights, width) };
}
