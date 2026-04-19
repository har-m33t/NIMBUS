import { motion } from "framer-motion";

/**
 * Word-by-word text reveal effect for captions.
 * Each word fades in and slides up with a staggered delay.
 */
export default function TextReveal({
  text,
  className = "",
  delayPerWord = 0.04,
}: {
  text: string;
  className?: string;
  delayPerWord?: number;
}) {
  const words = text.split(" ");

  return (
    <span className={className}>
      {words.map((word, i) => (
        <motion.span
          key={`${word}-${i}`}
          initial={{ opacity: 0, y: 6, filter: "blur(4px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{
            duration: 0.3,
            delay: i * delayPerWord,
            ease: "easeOut",
          }}
          className="inline-block mr-[0.25em]"
        >
          {word}
        </motion.span>
      ))}
    </span>
  );
}
