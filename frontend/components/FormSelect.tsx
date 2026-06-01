import * as React from "react";
import { cn } from "@/lib/utils";

type Props = React.SelectHTMLAttributes<HTMLSelectElement>;

export function FormSelect({ className, children, ...props }: Props) {
  return (
    <select
      className={cn(
        "h-9 rounded-md border border-neutral-300 bg-white py-1 pl-3 pr-8 text-sm",
        className
      )}
      {...props}
    >
      {children}
    </select>
  );
}
