import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { HelpCircle } from "lucide-react";

const WIDTH = 280;
const MARGIN = 10;

/** A "?" bubble that explains one control in plain language. */
export default function Help({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState({ top: 0, left: 0 });
  const id = useId();
  const wrap = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);

  // The cards around these controls clip their overflow, so the bubble is
  // positioned against the viewport instead of its parent.
  useLayoutEffect(() => {
    if (!open || !button.current) return;
    const place = () => {
      const r = button.current?.getBoundingClientRect();
      if (!r) return;
      const height = bubble.current?.offsetHeight ?? 0;
      const below = r.bottom + 8;
      const flip = below + height > window.innerHeight - MARGIN && r.top > height;
      setAt({
        top: flip ? r.top - height - 8 : below,
        left: Math.min(
          Math.max(MARGIN, r.left + r.width / 2 - WIDTH / 2),
          window.innerWidth - WIDTH - MARGIN,
        ),
      });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (
        !wrap.current?.contains(e.target as Node) &&
        !bubble.current?.contains(e.target as Node)
      )
        setOpen(false);
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <span className="help" ref={wrap}>
      <button
        type="button"
        ref={button}
        className="help-button"
        aria-label={`What is ${title}?`}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
      >
        <HelpCircle size={14} />
      </button>
      {open && (
        <span
          className="help-bubble"
          id={id}
          role="tooltip"
          ref={bubble}
          style={{ top: at.top, left: at.left, width: WIDTH }}
        >
          <strong>{title}</strong>
          {children}
        </span>
      )}
    </span>
  );
}
