import { ReactNode, useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";

interface TooltipProps {
  children: ReactNode;
  content: string | ReactNode;
  position?: "top" | "bottom" | "left" | "right";
  className?: string;
}

export function Tooltip({
  children,
  content,
  position = "top",
  className = "",
}: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0, width: 0, height: 0 });
  const containerRef = useRef<HTMLDivElement>(null);
  
  // Also track opacity to allow a smooth fade in after rendering
  const [isAnimating, setIsAnimating] = useState(false);

  const updatePosition = () => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setCoords({
      top: rect.top,
      left: rect.left,
      width: rect.width,
      height: rect.height,
    });
  };

  useEffect(() => {
    if (isVisible) {
      // Small delay to allow CSS transition to take effect
      const t = setTimeout(() => setIsAnimating(true), 10);
      
      // Update position on scroll just in case
      const handleScroll = () => updatePosition();
      window.addEventListener('scroll', handleScroll, true); // Use capture phase to catch all scrolls
      
      return () => {
        clearTimeout(t);
        window.removeEventListener('scroll', handleScroll, true);
      };
    } else {
      setIsAnimating(false);
    }
  }, [isVisible]);

  const handleMouseEnter = () => {
    updatePosition();
    setIsVisible(true);
  };

  const getStyles = () => {
    let top = 0;
    let left = 0;
    let transform = "";

    switch (position) {
      case "top":
        top = coords.top - 8;
        left = coords.left + coords.width / 2;
        transform = "translate(-50%, -100%)";
        break;
      case "bottom":
        top = coords.top + coords.height + 8;
        left = coords.left + coords.width / 2;
        transform = "translate(-50%, 0)";
        break;
      case "left":
        top = coords.top + coords.height / 2;
        left = coords.left - 8;
        transform = "translate(-100%, -50%)";
        break;
      case "right":
        top = coords.top + coords.height / 2;
        left = coords.left + coords.width + 8;
        transform = "translate(0, -50%)";
        break;
    }

    return { top, left, transform };
  };

  const arrowClasses = {
    top: "top-full left-1/2 -translate-x-1/2 border-t-zinc-800 dark:border-t-white",
    bottom:
      "bottom-full left-1/2 -translate-x-1/2 border-b-zinc-800 dark:border-b-white",
    left: "left-full top-1/2 -translate-y-1/2 border-l-zinc-800 dark:border-l-white",
    right:
      "right-full top-1/2 -translate-y-1/2 border-r-zinc-800 dark:border-r-white",
  };

  return (
    <div
      className="relative inline-flex items-center justify-center"
      ref={containerRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={() => setIsVisible(false)}
    >
      {children}
      {isVisible &&
        createPortal(
          <div
            className={`fixed z-[9999] pointer-events-none transition-opacity duration-200 ${
              isAnimating ? "opacity-100" : "opacity-0"
            } ${className}`}
            style={getStyles()}
          >
            <div className="bg-zinc-800 dark:bg-white text-white dark:text-zinc-900 text-[10px] font-bold px-3 py-2 rounded-lg shadow-xl max-w-55 w-max whitespace-normal text-center leading-tight">
              {content}
            </div>
            <div
              className={`absolute w-0 h-0 border-[5px] border-transparent ${arrowClasses[position]}`}
            />
          </div>,
          document.body
        )}
    </div>
  );
}
