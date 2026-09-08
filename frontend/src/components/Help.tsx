import { useEffect, useId, useRef, useState } from "react";
import { HelpCircle } from "lucide-react";

/** A "?" bubble that explains one control in plain language. */
export default function Help({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const wrap = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
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
        className="help-button"
        aria-label={`What is ${title}?`}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
      >
        <HelpCircle size={14} />
      </button>
      {open && (
        <span className="help-bubble" id={id} role="tooltip">
          <strong>{title}</strong>
          {children}
        </span>
      )}
    </span>
  );
}
