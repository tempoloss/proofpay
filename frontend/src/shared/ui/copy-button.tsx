import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "./button";

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <Button
      size="sm"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
      }}
    >
      {copied ? <Check className="text-proof" aria-hidden /> : <Copy aria-hidden />}
      {copied ? "Copied" : label}
    </Button>
  );
}
