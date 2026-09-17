import { useEffect, useRef } from "react";

export function RainOverlay() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let width = (canvas.width =
      canvas.parentElement?.clientWidth || window.innerWidth);
    let height = (canvas.height =
      canvas.parentElement?.clientHeight || window.innerHeight);

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width =
        canvas.parentElement?.clientWidth || window.innerWidth;
      height = canvas.height =
        canvas.parentElement?.clientHeight || window.innerHeight;
    };
    window.addEventListener("resize", handleResize);

    const dropCount = 120;
    const drops: Array<{
      x: number;
      y: number;
      speed: number;
      length: number;
      opacity: number;
    }> = [];

    for (let i = 0; i < dropCount; i++) {
      drops.push({
        x: Math.random() * width,
        y: Math.random() * height,
        speed: 14 + Math.random() * 10,
        length: 12 + Math.random() * 16,
        opacity: 0.2 + Math.random() * 0.35,
      });
    }

    const render = () => {
      ctx.clearRect(0, 0, width, height);

      for (let i = 0; i < drops.length; i++) {
        const d = drops[i];
        ctx.beginPath();
        ctx.strokeStyle = `rgba(185, 205, 230, ${d.opacity})`;
        ctx.lineWidth = 1.2;
        ctx.lineCap = "round";
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x - 2, d.y + d.length);
        ctx.stroke();

        d.y += d.speed;
        d.x -= 2;

        if (d.y > height) {
          d.y = -d.length;
          d.x = Math.random() * (width + 50);
        }
        if (d.x < -10) {
          d.x = width + 10;
        }
      }

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none z-10 w-full h-full"
    />
  );
}

