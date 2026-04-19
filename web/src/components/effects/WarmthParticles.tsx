/** Warm particles floating upward — used in warming overlay */
export default function WarmthParticles() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
      {Array.from({ length: 20 }).map((_, i) => (
        <div
          key={i}
          className="absolute rounded-full"
          style={{
            width: `${2 + Math.random() * 4}px`,
            height: `${2 + Math.random() * 4}px`,
            bottom: "-10px",
            left: `${10 + Math.random() * 80}%`,
            background: `rgba(232, 185, 49, ${0.3 + Math.random() * 0.4})`,
            animation: `float-up ${8 + Math.random() * 12}s linear infinite`,
            animationDelay: `${Math.random() * 10}s`,
          }}
        />
      ))}
    </div>
  );
}
