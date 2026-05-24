import { useRef, useCallback, useState } from "react";

export function useDragScroll<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T>(null);
  const isDraggingRef = useRef(false);
  const [isDraggingScroll, setIsDraggingScroll] = useState(false);
  const startX = useRef(0);
  const startScrollLeft = useRef(0);

  const onMouseDown = useCallback((e: React.MouseEvent<T>) => {
    const target = e.target as HTMLElement;
    // dnd-kit marks draggable elements with role="button" via useDraggable attributes
    if (target.closest('[role="button"]')) return;
    isDraggingRef.current = true;
    setIsDraggingScroll(true);
    startX.current = e.clientX;
    startScrollLeft.current = ref.current?.scrollLeft ?? 0;
  }, []);

  const onMouseMove = useCallback((e: React.MouseEvent<T>) => {
    if (!isDraggingRef.current || !ref.current) return;
    e.preventDefault();
    const delta = e.clientX - startX.current;
    ref.current.scrollLeft = startScrollLeft.current - delta;
  }, []);

  const stopDrag = useCallback(() => {
    isDraggingRef.current = false;
    setIsDraggingScroll(false);
  }, []);

  return {
    ref,
    isDraggingScroll,
    onMouseDown,
    onMouseMove,
    onMouseUp: stopDrag,
    onMouseLeave: stopDrag,
  };
}
