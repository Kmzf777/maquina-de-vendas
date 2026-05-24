import { useRef, useCallback, useState, useEffect } from "react";

export function useDragScroll<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T>(null);
  const isDraggingRef = useRef(false);
  const [isDraggingScroll, setIsDraggingScroll] = useState(false);
  const startX = useRef(0);
  const startScrollLeft = useRef(0);

  const stopDrag = useCallback(() => {
    isDraggingRef.current = false;
    setIsDraggingScroll(false);
    window.removeEventListener("mouseup", stopDrag);
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent<T>) => {
    const target = e.target as HTMLElement;
    // dnd-kit marks draggable elements with role="button" via useDraggable attributes
    if (target.closest('[role="button"]')) return;
    isDraggingRef.current = true;
    setIsDraggingScroll(true);
    startX.current = e.clientX;
    startScrollLeft.current = ref.current?.scrollLeft ?? 0;
    // Catches mouseup outside the container (fast drag past edge)
    window.addEventListener("mouseup", stopDrag, { once: true });
  }, [stopDrag]);

  const onMouseMove = useCallback((e: React.MouseEvent<T>) => {
    if (!isDraggingRef.current || !ref.current) return;
    e.preventDefault();
    const delta = e.clientX - startX.current;
    ref.current.scrollLeft = startScrollLeft.current - delta;
  }, []);

  // Remove window listener if component unmounts mid-drag
  useEffect(() => {
    return () => { window.removeEventListener("mouseup", stopDrag); };
  }, [stopDrag]);

  return {
    ref,
    isDraggingScroll,
    onMouseDown,
    onMouseMove,
    onMouseUp: stopDrag,
    onMouseLeave: stopDrag,
  };
}
