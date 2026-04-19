import { useRef, useEffect, useCallback } from "react";

/**
 * Layered cloud images from both sides of the screen.
 * Uses soft SVG cloud assets (overlapping ellipses with gaussian blur).
 * Many instances at varying depths, sizes, and positions for a natural sky feel.
 */

const CLOUD_SRCS = [
  "/clouds/cloud1.svg",
  "/clouds/cloud2.svg",
  "/clouds/cloud3.svg",
  "/clouds/cloud4.svg",
  "/clouds/cloud5.svg",
];

interface CloudInstance {
  src: string;
  side: "left" | "right";
  top: string;
  width: number;      // px
  offset: number;     // how far off-screen edge (negative = more hidden)
  depth: number;      // 1=far, 2=mid, 3=near — affects parallax + opacity
  opacity: number;
  animDuration: string;
  animName: string;
  flip?: boolean;     // mirror horizontally for variety
}

const CLOUDS: CloudInstance[] = [
  // ══════════════════ Left side ══════════════════
  // Deep background — large, wide, dense vertical coverage for solid fill during envelope
  { src: CLOUD_SRCS[4], side: "left", top: "-10%", width: 850, offset: -120, depth: 1, opacity: 0.25, animDuration: "100s", animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[1], side: "left", top: "0%",   width: 800, offset: -100, depth: 1, opacity: 0.22, animDuration: "95s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[3], side: "left", top: "10%",  width: 820, offset: -130, depth: 1, opacity: 0.24, animDuration: "92s",  animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[0], side: "left", top: "20%",  width: 780, offset: -110, depth: 1, opacity: 0.22, animDuration: "88s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[2], side: "left", top: "30%",  width: 840, offset: -140, depth: 1, opacity: 0.25, animDuration: "85s",  animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[4], side: "left", top: "40%",  width: 790, offset: -100, depth: 1, opacity: 0.22, animDuration: "90s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[1], side: "left", top: "50%",  width: 830, offset: -120, depth: 1, opacity: 0.24, animDuration: "96s",  animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[3], side: "left", top: "60%",  width: 800, offset: -130, depth: 1, opacity: 0.22, animDuration: "86s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[0], side: "left", top: "70%",  width: 850, offset: -110, depth: 1, opacity: 0.25, animDuration: "93s",  animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[2], side: "left", top: "80%",  width: 810, offset: -100, depth: 1, opacity: 0.22, animDuration: "87s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[4], side: "left", top: "90%",  width: 830, offset: -120, depth: 1, opacity: 0.24, animDuration: "91s",  animName: "cloud-drift-slow" },
  // Midground — tighter spacing, wider
  { src: CLOUD_SRCS[0], side: "left", top: "-4%",  width: 520, offset: -80,  depth: 2, opacity: 0.5,  animDuration: "55s", animName: "cloud-drift-left" },
  { src: CLOUD_SRCS[2], side: "left", top: "8%",   width: 480, offset: -70,  depth: 2, opacity: 0.45, animDuration: "48s", animName: "cloud-drift-left", flip: true },
  { src: CLOUD_SRCS[3], side: "left", top: "20%",  width: 460, offset: -60,  depth: 2, opacity: 0.5,  animDuration: "52s", animName: "cloud-drift-left" },
  { src: CLOUD_SRCS[4], side: "left", top: "32%",  width: 500, offset: -80,  depth: 2, opacity: 0.45, animDuration: "50s", animName: "cloud-drift-left", flip: true },
  { src: CLOUD_SRCS[1], side: "left", top: "44%",  width: 470, offset: -65,  depth: 2, opacity: 0.48, animDuration: "54s", animName: "cloud-drift-left" },
  { src: CLOUD_SRCS[0], side: "left", top: "56%",  width: 510, offset: -75,  depth: 2, opacity: 0.42, animDuration: "46s", animName: "cloud-drift-left", flip: true },
  { src: CLOUD_SRCS[2], side: "left", top: "68%",  width: 490, offset: -70,  depth: 2, opacity: 0.5,  animDuration: "51s", animName: "cloud-drift-left" },
  { src: CLOUD_SRCS[3], side: "left", top: "80%",  width: 520, offset: -80,  depth: 2, opacity: 0.45, animDuration: "49s", animName: "cloud-drift-left", flip: true },
  // Foreground — crisp, bright, close
  { src: CLOUD_SRCS[1], side: "left", top: "-2%",  width: 520, offset: -50,  depth: 3, opacity: 0.88, animDuration: "42s", animName: "cloud-drift-left" },
  { src: CLOUD_SRCS[4], side: "left", top: "10%",  width: 580, offset: -60,  depth: 3, opacity: 0.92, animDuration: "38s", animName: "cloud-drift-left", flip: true },
  { src: CLOUD_SRCS[2], side: "left", top: "22%",  width: 500, offset: -40,  depth: 3, opacity: 0.88, animDuration: "44s", animName: "cloud-drift-left" },
  { src: CLOUD_SRCS[3], side: "left", top: "34%",  width: 560, offset: -55,  depth: 3, opacity: 0.9,  animDuration: "40s", animName: "cloud-drift-left", flip: true },
  { src: CLOUD_SRCS[0], side: "left", top: "46%",  width: 530, offset: -45,  depth: 3, opacity: 0.86, animDuration: "43s", animName: "cloud-drift-left" },
  { src: CLOUD_SRCS[4], side: "left", top: "58%",  width: 570, offset: -60,  depth: 3, opacity: 0.92, animDuration: "36s", animName: "cloud-drift-left", flip: true },
  { src: CLOUD_SRCS[1], side: "left", top: "70%",  width: 540, offset: -50,  depth: 3, opacity: 0.88, animDuration: "41s", animName: "cloud-drift-left" },
  { src: CLOUD_SRCS[2], side: "left", top: "82%",  width: 590, offset: -65,  depth: 3, opacity: 0.9,  animDuration: "39s", animName: "cloud-drift-left", flip: true },
  { src: CLOUD_SRCS[3], side: "left", top: "92%",  width: 520, offset: -45,  depth: 3, opacity: 0.86, animDuration: "42s", animName: "cloud-drift-left" },

  // ══════════════════ Right side ══════════════════
  // Deep background — mirrors left for full screen coverage
  { src: CLOUD_SRCS[2], side: "right", top: "-8%",  width: 830, offset: -110, depth: 1, opacity: 0.25, animDuration: "98s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[0], side: "right", top: "2%",   width: 810, offset: -130, depth: 1, opacity: 0.22, animDuration: "93s",  animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[4], side: "right", top: "12%",  width: 790, offset: -100, depth: 1, opacity: 0.24, animDuration: "90s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[1], side: "right", top: "22%",  width: 840, offset: -120, depth: 1, opacity: 0.22, animDuration: "87s",  animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[3], side: "right", top: "32%",  width: 800, offset: -140, depth: 1, opacity: 0.25, animDuration: "94s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[0], side: "right", top: "42%",  width: 820, offset: -110, depth: 1, opacity: 0.22, animDuration: "89s",  animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[2], side: "right", top: "52%",  width: 850, offset: -130, depth: 1, opacity: 0.24, animDuration: "91s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[4], side: "right", top: "62%",  width: 790, offset: -100, depth: 1, opacity: 0.22, animDuration: "86s",  animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[1], side: "right", top: "72%",  width: 830, offset: -120, depth: 1, opacity: 0.25, animDuration: "95s",  animName: "cloud-drift-slow", flip: true },
  { src: CLOUD_SRCS[3], side: "right", top: "82%",  width: 810, offset: -110, depth: 1, opacity: 0.22, animDuration: "88s",  animName: "cloud-drift-slow" },
  { src: CLOUD_SRCS[0], side: "right", top: "92%",  width: 840, offset: -130, depth: 1, opacity: 0.24, animDuration: "92s",  animName: "cloud-drift-slow", flip: true },
  // Midground
  { src: CLOUD_SRCS[3], side: "right", top: "-2%",  width: 500, offset: -75,  depth: 2, opacity: 0.48, animDuration: "50s", animName: "cloud-drift-right", flip: true },
  { src: CLOUD_SRCS[0], side: "right", top: "10%",  width: 520, offset: -80,  depth: 2, opacity: 0.52, animDuration: "46s", animName: "cloud-drift-right" },
  { src: CLOUD_SRCS[1], side: "right", top: "22%",  width: 470, offset: -65,  depth: 2, opacity: 0.48, animDuration: "53s", animName: "cloud-drift-right", flip: true },
  { src: CLOUD_SRCS[4], side: "right", top: "34%",  width: 490, offset: -70,  depth: 2, opacity: 0.5,  animDuration: "49s", animName: "cloud-drift-right" },
  { src: CLOUD_SRCS[2], side: "right", top: "46%",  width: 460, offset: -60,  depth: 2, opacity: 0.45, animDuration: "51s", animName: "cloud-drift-right", flip: true },
  { src: CLOUD_SRCS[3], side: "right", top: "58%",  width: 510, offset: -80,  depth: 2, opacity: 0.48, animDuration: "47s", animName: "cloud-drift-right" },
  { src: CLOUD_SRCS[0], side: "right", top: "70%",  width: 480, offset: -70,  depth: 2, opacity: 0.5,  animDuration: "52s", animName: "cloud-drift-right", flip: true },
  { src: CLOUD_SRCS[1], side: "right", top: "82%",  width: 520, offset: -75,  depth: 2, opacity: 0.45, animDuration: "48s", animName: "cloud-drift-right" },
  // Foreground
  { src: CLOUD_SRCS[2], side: "right", top: "-3%",  width: 560, offset: -55,  depth: 3, opacity: 0.9,  animDuration: "40s", animName: "cloud-drift-right" },
  { src: CLOUD_SRCS[4], side: "right", top: "8%",   width: 600, offset: -65,  depth: 3, opacity: 0.92, animDuration: "36s", animName: "cloud-drift-right", flip: true },
  { src: CLOUD_SRCS[0], side: "right", top: "20%",  width: 520, offset: -45,  depth: 3, opacity: 0.88, animDuration: "43s", animName: "cloud-drift-right" },
  { src: CLOUD_SRCS[1], side: "right", top: "32%",  width: 570, offset: -55,  depth: 3, opacity: 0.9,  animDuration: "39s", animName: "cloud-drift-right", flip: true },
  { src: CLOUD_SRCS[3], side: "right", top: "44%",  width: 540, offset: -50,  depth: 3, opacity: 0.86, animDuration: "42s", animName: "cloud-drift-right" },
  { src: CLOUD_SRCS[2], side: "right", top: "56%",  width: 590, offset: -60,  depth: 3, opacity: 0.92, animDuration: "37s", animName: "cloud-drift-right", flip: true },
  { src: CLOUD_SRCS[4], side: "right", top: "68%",  width: 530, offset: -45,  depth: 3, opacity: 0.88, animDuration: "41s", animName: "cloud-drift-right" },
  { src: CLOUD_SRCS[0], side: "right", top: "80%",  width: 580, offset: -60,  depth: 3, opacity: 0.9,  animDuration: "38s", animName: "cloud-drift-right", flip: true },
  { src: CLOUD_SRCS[1], side: "right", top: "90%",  width: 550, offset: -50,  depth: 3, opacity: 0.86, animDuration: "40s", animName: "cloud-drift-right" },
];

export default function CloudLayers({ intensity = "full", parting = false, envelope = false }: { intensity?: "full" | "subtle" | "none"; parting?: boolean; envelope?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const layerRefs = useRef<(HTMLDivElement | null)[]>([]);

  // Envelope: clouds slide inward past center to fully cover the screen
  // Parting: clouds slide outward to frame the content
  function calcOffset(cloud: CloudInstance, isPart: boolean, isEnvelope: boolean): number {
    const sign = cloud.side === "left" ? -1 : 1;
    if (isPart) return sign * cloud.depth * 50;
    if (isEnvelope) {
      // Dynamically calculate how far each cloud must move to reach past center.
      // A cloud's visible far edge sits at (offset + width) px from its side.
      // We need it to reach at least 65% of the viewport width (15% overlap past center).
      const vw = window.innerWidth;
      const visibleFarEdge = cloud.offset + cloud.width; // how far cloud extends into viewport
      const target = vw * 0.65; // push 15% past center for solid overlap
      const needed = Math.max(100, target - visibleFarEdge);
      // Depth-based parallax: far clouds slightly less, near clouds slightly more
      const depthScale = [0, 0.92, 0.96, 1.0][cloud.depth];
      return -sign * needed * depthScale;
    }
    return 0;
  }

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!containerRef.current) return;
    const cx = window.innerWidth / 2;
    const cy = window.innerHeight / 2;
    const dx = (e.clientX - cx) / cx;
    const dy = (e.clientY - cy) / cy;

    layerRefs.current.forEach((el, i) => {
      if (!el) return;
      const cloud = CLOUDS[i];
      const mx = dx * cloud.depth * 10;
      const my = dy * cloud.depth * 6;
      // Read current data attributes for live parting/envelope state
      const isPart = el.dataset.part === "1";
      const isEnv = el.dataset.envelope === "1";
      const offset = calcOffset(cloud, isPart, isEnv);
      el.style.transform = `translate(${mx + offset}px, ${my}px)`;
    });
  }, []);

  // Apply parting/envelope transform whenever props change
  useEffect(() => {
    layerRefs.current.forEach((el, i) => {
      if (!el) return;
      const cloud = CLOUDS[i];
      // Store state on the element so mousemove handler can read it
      el.dataset.part = parting ? "1" : "0";
      el.dataset.envelope = envelope ? "1" : "0";
      const offset = calcOffset(cloud, parting, envelope);
      el.style.transform = `translate(${offset}px, 0px)`;
    });
  }, [parting, envelope]);

  useEffect(() => {
    if (intensity === "none") return;
    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, [handleMouseMove, intensity]);

  if (intensity === "none") return null;

  const scale = intensity === "subtle" ? 0.5 : 1;

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 overflow-hidden pointer-events-none"
      aria-hidden="true"
      style={{
        zIndex: envelope ? 20 : 0,
        transition: "z-index 0s",
      }}
    >
      {CLOUDS.map((cloud, i) => {
        // During envelope, boost opacity of back/mid layers to create a solid wall
        let effectiveOpacity = cloud.opacity * scale;
        if (envelope) {
          const boost = [0, 0.55, 0.35, 0][cloud.depth]; // depth 1 gets biggest boost
          effectiveOpacity = Math.min(1, effectiveOpacity + boost);
        }
        return (
        <div
          key={i}
          ref={(el) => { layerRefs.current[i] = el; }}
          className="absolute"
          style={{
            [cloud.side === "left" ? "left" : "right"]: `${cloud.offset}px`,
            top: cloud.top,
            width: `${cloud.width}px`,
            opacity: effectiveOpacity,
            transition: "transform 1.4s cubic-bezier(0.22, 1, 0.36, 1), opacity 1.2s ease",
          }}
        >
          {/* Inner wrapper for CSS drift animation — separate from JS transform on parent */}
          <div
            style={{
              animation: `${cloud.animName} ${cloud.animDuration} ease-in-out infinite`,
            }}
          >
            <img
              src={cloud.src}
              alt=""
              className="w-full h-auto"
              style={{
                transform: cloud.flip ? "scaleX(-1)" : undefined,
              }}
              draggable={false}
            />
          </div>
        </div>
        );
      })}
    </div>
  );
}
