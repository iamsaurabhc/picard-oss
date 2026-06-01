import { cn } from "@/lib/utils";

type Props = {
  children: React.ReactNode;
  className?: string;
  maxWidth?: "3xl" | "4xl" | "none";
};

export function PageShell({ children, className, maxWidth = "4xl" }: Props) {
  return (
    <div
      className={cn(
        "p-6 md:p-8",
        maxWidth === "3xl" && "mx-auto max-w-3xl",
        maxWidth === "4xl" && "mx-auto max-w-4xl",
        className
      )}
    >
      {children}
    </div>
  );
}
