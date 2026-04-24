import { useRef, useCallback } from "react";

export function useDragScroll<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T>(null);
  const isDragging = useRef(false);
  const startX = useRef(0);
  const startScrollLeft = useRef(0);

  const onMouseDown = useCallback((e: React.MouseEvent<T>) => {
    const target = e.target as HTMLElement;
    // dnd-kit marks draggable elements with role="button" via useDraggable attributes
    if (target.closest('[role="button"]')) return;
    isDragging.current = true;
    startX.current = e.clientX;
    startScrollLeft.current = ref.current?.scrollLeft ?? 0;
  }, []);

  const onMouseMove = useCallback((e: React.MouseEvent<T>) => {
    if (!isDragging.current || !ref.current) return;
    e.preventDefault();
    const delta = e.clientX - startX.current;
    ref.current.scrollLeft = startScrollLeft.current - delta;
  }, []);

  const stopDrag = useCallback(() => {
    isDragging.current = false;
  }, []);

  return {
    ref,
    onMouseDown,
    onMouseMove,
    onMouseUp: stopDrag,
    onMouseLeave: stopDrag,
  };
}
