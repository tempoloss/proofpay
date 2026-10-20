import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/cn";

const fieldClass =
  "w-full rounded-lg border border-line bg-canvas px-3 text-fg text-sm outline-none transition-[border-color,box-shadow] placeholder:text-faint focus:border-line-strong focus:ring-2 focus:ring-proof/20 aria-[invalid=true]:border-fail/50";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(fieldClass, "h-10", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={cn(fieldClass, "min-h-24 py-2.5 leading-relaxed", className)} {...props} />;
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: ReactNode;
  htmlFor: string;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block font-medium text-[13px] text-fg">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-fail text-xs">{error}</p>
      ) : hint ? (
        <p className="text-faint text-xs leading-relaxed">{hint}</p>
      ) : null}
    </div>
  );
}
